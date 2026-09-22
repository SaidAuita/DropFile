package com.dropfile.mobile.data

data class UploadItem(
    val id: String = java.util.UUID.randomUUID().toString(),
    val filename: String,
    val sizeBytes: Long,
    val timestamp: Long = System.currentTimeMillis(),
    val targetFolder: String,
    val isSuccess: Boolean = true,
    val errorMessage: String? = null
)
