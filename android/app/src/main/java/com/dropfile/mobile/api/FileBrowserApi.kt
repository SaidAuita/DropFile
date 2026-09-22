package com.dropfile.mobile.api

import com.dropfile.mobile.data.AppLogger
import com.google.gson.JsonObject
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okio.BufferedSink
import java.io.InputStream
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

class FileBrowserApi {

    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(180, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    @Volatile
    private var cachedToken: String? = null

    fun testConnection(serverUrl: String, username: String, password: String): Result<String> {
        return try {
            AppLogger.i("FileBrowserApi", "Testing connection to: $serverUrl, user: $username")
            val token = login(serverUrl, username, password)
            cachedToken = token
            AppLogger.i("FileBrowserApi", "Test connection successful! Token received.")
            Result.success("Соединение успешно! Авторизация пройдена.")
        } catch (e: Exception) {
            AppLogger.e("FileBrowserApi", "Test connection failed: ${e.message}", e)
            Result.failure(e)
        }
    }

    @Throws(Exception::class)
    fun login(serverUrl: String, username: String, password: String): String {
        val cleanUrl = serverUrl.trimEnd('/')
        val url = "$cleanUrl/api/login"
        AppLogger.i("FileBrowserApi", "Sending POST to: $url (user: $username)")

        val json = JsonObject().apply {
            addProperty("username", username)
            addProperty("password", password)
        }

        val body = RequestBody.create("application/json; charset=utf-8".toMediaTypeOrNull(), json.toString())
        val request = Request.Builder()
            .url(url)
            .post(body)
            .build()

        client.newCall(request).execute().use { response ->
            AppLogger.i("FileBrowserApi", "Login response HTTP code: ${response.code}")
            if (response.isSuccessful) {
                val token = response.body?.string()?.trim()?.trim('"')
                if (!token.isNullOrBlank()) {
                    cachedToken = token
                    return token
                }
                throw IllegalStateException("Сервер вернул пустой токен авторизации")
            } else if (response.code == 403) {
                throw IllegalArgumentException("Ошибка 403: Неверное имя пользователя или пароль")
            } else if (response.code == 404) {
                throw IllegalArgumentException("Ошибка 404: API FileBrowser не найден по адресу $serverUrl")
            } else {
                throw IllegalStateException("Сервер вернул статус ${response.code}: ${response.message}")
            }
        }
    }

    @Throws(Exception::class)
    fun uploadStream(
        serverUrl: String,
        username: String,
        password: String,
        remoteFolder: String,
        filename: String,
        inputStream: InputStream,
        totalBytes: Long,
        onProgress: (bytesSent: Long, total: Long) -> Unit
    ) {
        val token = cachedToken ?: login(serverUrl, username, password)

        val cleanUrl = serverUrl.trimEnd('/')
        val folder = "/" + remoteFolder.trim('/').trim()
        val fullPath = if (folder == "/") "/$filename" else "$folder/$filename"

        // URL encode each segment of the path preserving slashes
        val encodedPath = fullPath.split("/").joinToString("/") { segment ->
            if (segment.isEmpty()) "" else URLEncoder.encode(segment, "UTF-8").replace("+", "%20")
        }

        val uploadUrl = "$cleanUrl/api/resources$encodedPath?override=true"
        AppLogger.i("FileBrowserApi", "Uploading stream to: $uploadUrl (size: $totalBytes bytes)")

        val streamingBody = object : RequestBody() {
            override fun contentType() = "application/octet-stream".toMediaTypeOrNull()

            override fun contentLength(): Long = if (totalBytes > 0) totalBytes else -1

            override fun writeTo(sink: BufferedSink) {
                val buffer = ByteArray(64 * 1024)
                var bytesSent = 0L
                var read: Int
                inputStream.use { input ->
                    while (input.read(buffer).also { read = it } != -1) {
                        sink.write(buffer, 0, read)
                        bytesSent += read
                        onProgress(bytesSent, totalBytes)
                    }
                }
                sink.flush()
            }
        }

        val request = Request.Builder()
            .url(uploadUrl)
            .addHeader("X-Auth", token)
            .post(streamingBody)
            .build()

        client.newCall(request).execute().use { response ->
            AppLogger.i("FileBrowserApi", "Upload response HTTP code: ${response.code}")
            if (response.code == 401 || response.code == 403) {
                AppLogger.w("FileBrowserApi", "Token expired (${response.code}), retrying login...")
                cachedToken = null
                val newToken = login(serverUrl, username, password)
                val retryRequest = Request.Builder()
                    .url(uploadUrl)
                    .addHeader("X-Auth", newToken)
                    .post(streamingBody)
                    .build()
                client.newCall(retryRequest).execute().use { retryResponse ->
                    AppLogger.i("FileBrowserApi", "Retry upload response HTTP code: ${retryResponse.code}")
                    if (!retryResponse.isSuccessful) {
                        throw IllegalStateException("Ошибка загрузки (${retryResponse.code}): ${retryResponse.message}")
                    }
                }
            } else if (!response.isSuccessful) {
                throw IllegalStateException("Ошибка загрузки (${response.code}): ${response.message}")
            }
        }
    }
}
