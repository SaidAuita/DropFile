package com.dropfile.mobile.data

import com.google.gson.annotations.SerializedName

data class AppConfig(
    @SerializedName("server_url")
    val serverUrl: String = "",

    @SerializedName("username")
    val username: String = "",

    @SerializedName("password")
    val password: String = "",

    @SerializedName("target_folder")
    val targetFolder: String = "/Exchange/Mobile",

    @SerializedName("auto_close")
    val autoClose: Boolean = true
) {
    val isConfigured: Boolean
        get() = serverUrl.isNotBlank() && username.isNotBlank()
}
