package com.dropfile.mobile.data

import android.content.Context
import android.content.SharedPreferences
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import java.io.InputStream
import java.io.InputStreamReader

class ConfigManager(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val gson: Gson = GsonBuilder().setPrettyPrinting().create()

    fun getConfig(): AppConfig {
        return AppConfig(
            serverUrl = prefs.getString(KEY_SERVER_URL, "") ?: "",
            username = prefs.getString(KEY_USERNAME, "") ?: "",
            password = prefs.getString(KEY_PASSWORD, "") ?: "",
            targetFolder = prefs.getString(KEY_TARGET_FOLDER, "/Exchange/Mobile") ?: "/Exchange/Mobile",
            autoClose = prefs.getBoolean(KEY_AUTO_CLOSE, true)
        )
    }

    fun saveConfig(config: AppConfig) {
        prefs.edit()
            .putString(KEY_SERVER_URL, cleanUrl(config.serverUrl))
            .putString(KEY_USERNAME, config.username.trim())
            .putString(KEY_PASSWORD, config.password)
            .putString(KEY_TARGET_FOLDER, cleanFolder(config.targetFolder))
            .putBoolean(KEY_AUTO_CLOSE, config.autoClose)
            .apply()
    }

    fun importFromJsonStream(inputStream: InputStream): Result<AppConfig> {
        return runCatching {
            InputStreamReader(inputStream, Charsets.UTF_8).use { reader ->
                val config = gson.fromJson(reader, AppConfig::class.java)
                    ?: throw IllegalArgumentException("Пустой или невалидный JSON конфигурации")
                saveConfig(config)
                config
            }
        }
    }

    fun exportToJsonString(): String {
        return gson.toJson(getConfig())
    }

    companion object {
        private const val PREFS_NAME = "dropfile_mobile_prefs"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_USERNAME = "username"
        private const val KEY_PASSWORD = "password"
        private const val KEY_TARGET_FOLDER = "target_folder"
        private const val KEY_AUTO_CLOSE = "auto_close"

        fun cleanUrl(rawUrl: String): String {
            var url = rawUrl.trim()
            if (url.endsWith("/")) {
                url = url.substring(0, url.length - 1)
            }
            if (!url.startsWith("http://", ignoreCase = true) &&
                !url.startsWith("https://", ignoreCase = true) &&
                url.isNotEmpty()
            ) {
                url = "http://$url"
            }
            return url
        }

        fun cleanFolder(rawFolder: String): String {
            var folder = rawFolder.trim().replace("\\", "/")
            if (!folder.startsWith("/")) {
                folder = "/$folder"
            }
            while (folder.endsWith("/") && folder.length > 1) {
                folder = folder.substring(0, folder.length - 1)
            }
            return folder
        }
    }
}
