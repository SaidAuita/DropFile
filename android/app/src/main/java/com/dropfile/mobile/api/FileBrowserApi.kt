package com.dropfile.mobile.api

import com.dropfile.mobile.data.AppLogger
import com.dropfile.mobile.data.RemoteItem
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okio.BufferedSink
import java.io.InputStream
import java.io.OutputStream
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

class FileBrowserApi {

    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(180, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    private val gson = Gson()

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

    private fun encodePath(rawPath: String): String {
        val clean = "/" + rawPath.trim('/')
        if (clean == "/") return ""
        return clean.split("/").joinToString("/") { segment ->
            if (segment.isEmpty()) "" else URLEncoder.encode(segment, "UTF-8").replace("+", "%20")
        }
    }

    /**
     * Lists files and folders in the remote directory using GET /api/resources/{path}.
     * Returns a sorted list: directories first, then files.
     */
    fun listDirectory(
        serverUrl: String,
        username: String,
        password: String,
        remotePath: String
    ): Result<List<RemoteItem>> {
        return runCatching {
            val token = cachedToken ?: login(serverUrl, username, password)
            val cleanUrl = serverUrl.trimEnd('/')
            val encoded = encodePath(remotePath)
            val url = "$cleanUrl/api/resources$encoded"

            AppLogger.i("FileBrowserApi", "Listing directory: $url")

            val request = Request.Builder()
                .url(url)
                .addHeader("X-Auth", token)
                .get()
                .build()

            client.newCall(request).execute().use { response ->
                if (response.code == 401 || response.code == 403) {
                    cachedToken = null
                    val newToken = login(serverUrl, username, password)
                    val retryRequest = Request.Builder()
                        .url(url)
                        .addHeader("X-Auth", newToken)
                        .get()
                        .build()
                    return@use client.newCall(retryRequest).execute().use { retryResp ->
                        parseDirectoryListing(retryResp.body?.string().orEmpty(), remotePath)
                    }
                }

                if (!response.isSuccessful) {
                    throw IllegalStateException("Ошибка получения списка (${response.code}): ${response.message}")
                }

                val jsonBody = response.body?.string().orEmpty()
                parseDirectoryListing(jsonBody, remotePath)
            }
        }
    }

    private fun parseDirectoryListing(jsonBody: String, parentPath: String): List<RemoteItem> {
        val jsonObject = JsonParser.parseString(jsonBody).asJsonObject
        val itemsArray = jsonObject.getAsJsonArray("items") ?: return emptyList()

        val list = mutableListOf<RemoteItem>()
        val cleanParent = "/" + parentPath.trim('/')

        for (el in itemsArray) {
            val itemObj = el.asJsonObject
            val name = itemObj.get("name")?.asString ?: continue
            val isDir = itemObj.get("isDir")?.asBoolean ?: false
            val size = itemObj.get("size")?.asLong ?: 0L
            val modified = itemObj.get("modified")?.asString
            val fullItemPath = if (cleanParent == "/") "/$name" else "$cleanParent/$name"

            list.add(
                RemoteItem(
                    name = name,
                    path = fullItemPath,
                    isDir = isDir,
                    sizeBytes = size,
                    modified = modified
                )
            )
        }

        // Sort: directories first, then alphabetical
        return list.sortedWith(
            compareByDescending<RemoteItem> { it.isDir }
                .thenBy { it.name.lowercase() }
        )
    }

    /**
     * Retrieves an existing share link or generates a new one via FileBrowser API.
     * Returns the full public URL e.g. "https://photo.keenetic.link/share/abcdef"
     */
    fun getOrCreateShareLink(
        serverUrl: String,
        username: String,
        password: String,
        remotePath: String
    ): Result<String> {
        return runCatching {
            val token = cachedToken ?: login(serverUrl, username, password)
            val cleanUrl = serverUrl.trimEnd('/')
            val encoded = encodePath(remotePath)
            val shareUrl = "$cleanUrl/api/share$encoded"

            AppLogger.i("FileBrowserApi", "Checking/creating share link for: $remotePath")

            // 1. Check if public share link already exists
            val getReq = Request.Builder()
                .url(shareUrl)
                .addHeader("X-Auth", token)
                .get()
                .build()

            client.newCall(getReq).execute().use { resp ->
                if (resp.isSuccessful) {
                    val body = resp.body?.string().orEmpty()
                    val elem = JsonParser.parseString(body)
                    if (elem.isJsonArray) {
                        val arr = elem.asJsonArray
                        if (arr.size() > 0) {
                            val first = arr[0].asJsonObject
                            if (first.has("hash")) {
                                val hash = first.get("hash").asString
                                AppLogger.i("FileBrowserApi", "Found existing share link hash: $hash")
                                return@runCatching "$cleanUrl/share/$hash"
                            }
                        }
                    }
                }
            }

            // 2. Create new public share link (empty JSON object {})
            val emptyBody = RequestBody.create("application/json; charset=utf-8".toMediaTypeOrNull(), "{}")
            val postReq = Request.Builder()
                .url(shareUrl)
                .addHeader("X-Auth", token)
                .post(emptyBody)
                .build()

            client.newCall(postReq).execute().use { resp ->
                if (resp.isSuccessful) {
                    val body = resp.body?.string().orEmpty()
                    val obj = JsonParser.parseString(body).asJsonObject
                    if (obj.has("hash")) {
                        val hash = obj.get("hash").asString
                        AppLogger.i("FileBrowserApi", "Created new share link hash: $hash")
                        return@runCatching "$cleanUrl/share/$hash"
                    }
                }
                // Fallback to web link inside files
                AppLogger.w("FileBrowserApi", "Could not create share hash, falling back to files link")
                "$cleanUrl/files$encoded"
            }
        }
    }

    /**
     * Deletes a remote file or folder via DELETE /api/resources/{path}.
     */
    fun deleteResource(
        serverUrl: String,
        username: String,
        password: String,
        remotePath: String
    ): Result<Boolean> {
        return runCatching {
            val token = cachedToken ?: login(serverUrl, username, password)
            val cleanUrl = serverUrl.trimEnd('/')
            val encoded = encodePath(remotePath)
            val url = "$cleanUrl/api/resources$encoded"

            AppLogger.i("FileBrowserApi", "Deleting resource: $url")

            val request = Request.Builder()
                .url(url)
                .addHeader("X-Auth", token)
                .delete()
                .build()

            client.newCall(request).execute().use { resp ->
                if (resp.isSuccessful || resp.code == 404) {
                    AppLogger.i("FileBrowserApi", "Resource deleted successfully (${resp.code})")
                    true
                } else {
                    throw IllegalStateException("Ошибка удаления (${resp.code}): ${resp.message}")
                }
            }
        }
    }

    /**
     * Downloads a file from the server via GET /api/raw/{path}.
     */
    fun downloadFile(
        serverUrl: String,
        username: String,
        password: String,
        remotePath: String,
        outputStream: OutputStream,
        onProgress: (bytesDownloaded: Long, totalBytes: Long) -> Unit
    ): Result<Long> {
        return runCatching {
            val token = cachedToken ?: login(serverUrl, username, password)
            val cleanUrl = serverUrl.trimEnd('/')
            val encoded = encodePath(remotePath)
            val url = "$cleanUrl/api/raw$encoded"

            AppLogger.i("FileBrowserApi", "Downloading file: $url")

            val request = Request.Builder()
                .url(url)
                .addHeader("X-Auth", token)
                .get()
                .build()

            client.newCall(request).execute().use { resp ->
                if (!resp.isSuccessful) {
                    throw IllegalStateException("Ошибка скачивания (${resp.code}): ${resp.message}")
                }

                val body = resp.body ?: throw IllegalStateException("Пустой ответ от сервера")
                val totalLength = body.contentLength()
                val source = body.byteStream()

                val buffer = ByteArray(64 * 1024)
                var bytesRead: Int
                var totalRead = 0L

                outputStream.use { out ->
                    source.use { input ->
                        while (input.read(buffer).also { bytesRead = it } != -1) {
                            out.write(buffer, 0, bytesRead)
                            totalRead += bytesRead
                            onProgress(totalRead, totalLength)
                        }
                    }
                    out.flush()
                }

                AppLogger.i("FileBrowserApi", "Downloaded $totalRead bytes successfully")
                totalRead
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
        val encodedPath = encodePath(fullPath)

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
