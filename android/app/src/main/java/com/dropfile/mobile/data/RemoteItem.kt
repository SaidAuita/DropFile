package com.dropfile.mobile.data

import com.google.gson.annotations.SerializedName

enum class RemoteFileType {
    FOLDER,
    IMAGE,
    VIDEO,
    AUDIO,
    ARCHIVE,
    DOCUMENT,
    OTHER
}

data class RemoteItem(
    @SerializedName("name")
    val name: String,

    @SerializedName("path")
    val path: String = "",

    @SerializedName("isDir")
    val isDir: Boolean = false,

    @SerializedName("size")
    val sizeBytes: Long = 0L,

    @SerializedName("modified")
    val modified: String? = null
) {
    val fileType: RemoteFileType
        get() {
            if (isDir) return RemoteFileType.FOLDER
            val ext = name.substringAfterLast(".", "").lowercase()
            return when (ext) {
                "jpg", "jpeg", "png", "webp", "gif", "bmp", "heic", "raw", "dng", "tiff", "svg" -> RemoteFileType.IMAGE
                "mp4", "mov", "mkv", "avi", "webm", "flv", "wmv", "m4v" -> RemoteFileType.VIDEO
                "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma" -> RemoteFileType.AUDIO
                "zip", "7z", "rar", "tar", "gz", "bz2", "xz" -> RemoteFileType.ARCHIVE
                "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "csv", "json" -> RemoteFileType.DOCUMENT
                else -> RemoteFileType.OTHER
            }
        }
}
