package com.dropfile.mobile

import android.app.Activity
import android.content.Intent
import android.database.Cursor
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.dropfile.mobile.api.FileBrowserApi
import com.dropfile.mobile.data.AppConfig
import com.dropfile.mobile.data.ConfigManager
import com.dropfile.mobile.data.HistoryManager
import com.dropfile.mobile.data.UploadItem
import com.dropfile.mobile.databinding.ActivitySendBinding
import com.dropfile.mobile.ui.HistoryAdapter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class SendActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySendBinding
    private lateinit var configManager: ConfigManager
    private lateinit var historyManager: HistoryManager
    private val api = FileBrowserApi()

    private val filesToUpload = mutableListOf<FileInfo>()
    private var uploadJob: Job? = null

    data class FileInfo(
        val uri: Uri,
        val filename: String,
        val sizeBytes: Long
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySendBinding.inflate(layoutInflater)
        setContentView(binding.root)

        configManager = ConfigManager(this)
        historyManager = HistoryManager(this)

        val config = configManager.getConfig()
        if (!config.isConfigured) {
            Toast.makeText(this, "Пожалуйста, настройте подключение к серверу", Toast.LENGTH_LONG).show()
            startActivity(Intent(this, SettingsActivity::class.java))
            finish()
            return
        }

        binding.tvDestinationFolder.text = "Папка: ${config.targetFolder}"

        binding.btnCancel.setOnClickListener {
            uploadJob?.cancel()
            finish()
        }

        binding.btnStartSend.setOnClickListener {
            startUpload(config)
        }

        extractFilesFromIntent(intent)
    }

    private fun extractFilesFromIntent(intent: Intent) {
        filesToUpload.clear()

        when (intent.action) {
            Intent.ACTION_SEND -> {
                val uri = intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
                    ?: intent.clipData?.getItemAt(0)?.uri
                if (uri != null) {
                    resolveFileInfo(uri)?.let { filesToUpload.add(it) }
                }
            }
            Intent.ACTION_SEND_MULTIPLE -> {
                val uris = intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)
                if (uris != null) {
                    for (u in uris) {
                        resolveFileInfo(u)?.let { filesToUpload.add(it) }
                    }
                } else if (intent.clipData != null) {
                    val clip = intent.clipData!!
                    for (i in 0 until clip.itemCount) {
                        val u = clip.getItemAt(i).uri
                        resolveFileInfo(u)?.let { filesToUpload.add(it) }
                    }
                }
            }
        }

        if (filesToUpload.isEmpty()) {
            Toast.makeText(this, "Нет файлов для отправки", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        val totalBytes = filesToUpload.sumOf { it.sizeBytes }
        val count = filesToUpload.size
        val fileWord = if (count == 1) "файл" else if (count in 2..4) "файла" else "файлов"
        binding.tvFilesSummary.text = "$count $fileWord (${HistoryAdapter.formatFileSize(totalBytes)})"
        binding.tvStatusDetail.text = "Готово к отправке"
        binding.progressBar.progress = 0

        // Auto start upload immediately for fast 1-tap experience
        val config = configManager.getConfig()
        startUpload(config)
    }

    private fun resolveFileInfo(uri: Uri): FileInfo? {
        return try {
            var name: String? = null
            var size: Long = -1L

            if (uri.scheme == "content") {
                val cursor: Cursor? = contentResolver.query(uri, null, null, null, null)
                cursor?.use {
                    if (it.moveToFirst()) {
                        val nameIndex = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        val sizeIndex = it.getColumnIndex(OpenableColumns.SIZE)
                        if (nameIndex != -1) name = it.getString(nameIndex)
                        if (sizeIndex != -1) size = it.getLong(sizeIndex)
                    }
                }
            }

            if (name.isNullOrBlank()) {
                name = uri.lastPathSegment ?: "file_${System.currentTimeMillis()}"
            }
            if (size < 0) {
                // Try estimating from stream
                try {
                    contentResolver.openAssetFileDescriptor(uri, "r")?.use {
                        size = it.length
                    }
                } catch (_: Exception) {}
            }

            FileInfo(uri = uri, filename = name!!, sizeBytes = size)
        } catch (e: Exception) {
            null
        }
    }

    private fun startUpload(config: AppConfig) {
        binding.btnStartSend.visibility = View.GONE
        binding.btnCancel.text = getString(R.string.cancel)
        binding.progressBar.isIndeterminate = false

        val totalBatchBytes = filesToUpload.sumOf { if (it.sizeBytes > 0) it.sizeBytes else 0L }
        var uploadedBatchBytes = 0L

        uploadJob = lifecycleScope.launch(Dispatchers.IO) {
            var allSuccess = true
            var failureMessage: String? = null

            for ((index, file) in filesToUpload.withIndex()) {
                withContext(Dispatchers.Main) {
                    binding.tvStatusDetail.text = "Отправка (${index + 1}/${filesToUpload.size}): ${file.filename}"
                }

                val uploadResult = runCatching {
                    val inputStream = contentResolver.openInputStream(file.uri)
                        ?: throw IllegalStateException("Не удалось открыть ${file.filename}")

                    api.uploadStream(
                        serverUrl = config.serverUrl,
                        username = config.username,
                        password = config.password,
                        remoteFolder = config.targetFolder,
                        filename = file.filename,
                        inputStream = inputStream,
                        totalBytes = file.sizeBytes
                    ) { fileBytesSent, _ ->
                        if (totalBatchBytes > 0) {
                            val currentTotal = uploadedBatchBytes + fileBytesSent
                            val percent = ((currentTotal * 100) / totalBatchBytes).toInt().coerceIn(0, 100)
                            binding.progressBar.post {
                                binding.progressBar.progress = percent
                            }
                        }
                    }
                }

                if (uploadResult.isSuccess) {
                    uploadedBatchBytes += if (file.sizeBytes > 0) file.sizeBytes else 0L
                    historyManager.addItem(
                        UploadItem(
                            filename = file.filename,
                            sizeBytes = file.sizeBytes,
                            targetFolder = config.targetFolder,
                            isSuccess = true
                        )
                    )
                } else {
                    allSuccess = false
                    val error = uploadResult.exceptionOrNull()
                    failureMessage = error?.localizedMessage ?: error?.message ?: "Неизвестная ошибка"
                    historyManager.addItem(
                        UploadItem(
                            filename = file.filename,
                            sizeBytes = file.sizeBytes,
                            targetFolder = config.targetFolder,
                            isSuccess = false,
                            errorMessage = failureMessage
                        )
                    )
                    break
                }
            }

            withContext(Dispatchers.Main) {
                if (allSuccess) {
                    binding.progressBar.progress = 100
                    binding.tvStatusDetail.text = "✓ " + getString(R.string.send_success)
                    binding.ivSendIcon.setImageResource(R.drawable.ic_check_circle)
                    binding.ivSendIcon.setColorFilter(ContextCompat.getColor(this@SendActivity, R.color.status_success))
                    binding.btnCancel.text = getString(R.string.close)

                    Toast.makeText(this@SendActivity, "Успешно отправлено в DropFile!", Toast.LENGTH_SHORT).show()

                    if (config.autoClose) {
                        delay(900)
                        finish()
                    }
                } else {
                    binding.tvStatusDetail.text = "Ошибка: $failureMessage"
                    binding.ivSendIcon.setImageResource(R.drawable.ic_error)
                    binding.ivSendIcon.setColorFilter(ContextCompat.getColor(this@SendActivity, R.color.status_error))
                    binding.btnCancel.text = getString(R.string.close)
                    binding.btnStartSend.visibility = View.VISIBLE
                    binding.btnStartSend.text = "Повторить"
                }
            }
        }
    }

    override fun onDestroy() {
        uploadJob?.cancel()
        super.onDestroy()
    }
}
