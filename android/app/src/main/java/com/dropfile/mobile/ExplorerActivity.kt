package com.dropfile.mobile

import android.app.DownloadManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.view.View
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.dropfile.mobile.api.FileBrowserApi
import com.dropfile.mobile.data.AppConfig
import com.dropfile.mobile.data.AppLogger
import com.dropfile.mobile.data.ConfigManager
import com.dropfile.mobile.data.RemoteFileType
import com.dropfile.mobile.data.RemoteItem
import com.dropfile.mobile.databinding.ActivityExplorerBinding
import com.dropfile.mobile.ui.HistoryAdapter
import com.dropfile.mobile.ui.LogViewerDialog
import com.dropfile.mobile.ui.RemoteItemAdapter
import com.google.android.material.bottomsheet.BottomSheetDialog
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

class ExplorerActivity : AppCompatActivity() {

    private lateinit var binding: ActivityExplorerBinding
    private lateinit var configManager: ConfigManager
    private lateinit var adapter: RemoteItemAdapter
    private val api = FileBrowserApi()

    private var currentPath: String = "/Exchange/Mobile"
    private lateinit var config: AppConfig

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AppLogger.init(applicationContext)
        AppLogger.i("ExplorerActivity", "onCreate started")

        binding = ActivityExplorerBinding.inflate(layoutInflater)
        setContentView(binding.root)

        configManager = ConfigManager(this)
        config = configManager.getConfig()

        if (!config.isConfigured) {
            Toast.makeText(this, "Сначала настройте подключение к серверу", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        currentPath = if (config.targetFolder.isNotBlank()) config.targetFolder else "/Exchange/Mobile"

        setupToolbar()
        setupRecyclerView()
        setupNavigation()

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (currentPath != "/" && currentPath != config.targetFolder) {
                    navigateUp()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })

        loadDirectory(currentPath)
    }

    private fun setupToolbar() {
        binding.toolbar.setNavigationOnClickListener {
            finish()
        }

        binding.btnJumpTarget.setOnClickListener {
            loadDirectory(config.targetFolder)
        }

        binding.btnLogs.setOnClickListener {
            LogViewerDialog.show(this)
        }

        binding.swipeRefresh.setOnRefreshListener {
            loadDirectory(currentPath, isPullToRefresh = true)
        }
    }

    private fun setupRecyclerView() {
        adapter = RemoteItemAdapter(
            onItemClick = { item ->
                if (item.isDir) {
                    loadDirectory(item.path)
                } else {
                    showItemActionDialog(item)
                }
            },
            onItemMenuClick = { item ->
                showItemActionDialog(item)
            }
        )

        binding.rvExplorerItems.layoutManager = LinearLayoutManager(this)
        binding.rvExplorerItems.adapter = adapter
    }

    private fun setupNavigation() {
        binding.btnUpFolder.setOnClickListener {
            navigateUp()
        }
    }

    private fun navigateUp() {
        val clean = "/" + currentPath.trim('/')
        if (clean == "/" || clean.isEmpty()) return

        val parent = clean.substringBeforeLast("/").ifEmpty { "/" }
        AppLogger.i("ExplorerActivity", "Navigating up: from '$currentPath' to '$parent'")
        loadDirectory(parent)
    }

    private fun loadDirectory(path: String, isPullToRefresh: Boolean = false) {
        val targetPath = "/" + path.trim('/')
        AppLogger.i("ExplorerActivity", "Loading directory: $targetPath")

        if (!isPullToRefresh) {
            binding.loadingIndicator.visibility = View.VISIBLE
        }
        binding.tvEmptyExplorer.visibility = View.GONE

        lifecycleScope.launch(Dispatchers.IO) {
            val result = api.listDirectory(config.serverUrl, config.username, config.password, targetPath)

            withContext(Dispatchers.Main) {
                binding.loadingIndicator.visibility = View.GONE
                binding.swipeRefresh.isRefreshing = false

                result.onSuccess { items ->
                    currentPath = targetPath
                    binding.tvCurrentPath.text = currentPath
                    binding.btnUpFolder.isEnabled = currentPath != "/"

                    adapter.updateItems(items)

                    if (items.isEmpty()) {
                        binding.tvEmptyExplorer.visibility = View.VISIBLE
                    } else {
                        binding.tvEmptyExplorer.visibility = View.GONE
                    }
                    AppLogger.i("ExplorerActivity", "Successfully loaded $targetPath: ${items.size} items")
                }.onFailure { err ->
                    AppLogger.e("ExplorerActivity", "Failed to load directory $targetPath", err)
                    Toast.makeText(
                        this@ExplorerActivity,
                        "Ошибка загрузки: ${err.localizedMessage ?: err.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }

    private fun showItemActionDialog(item: RemoteItem) {
        val dialog = BottomSheetDialog(this)
        val dialogView = layoutInflater.inflate(R.layout.dialog_remote_actions, null)
        dialog.setContentView(dialogView)

        val ivIcon = dialogView.findViewById<ImageView>(R.id.dialogItemIcon)
        val tvTitle = dialogView.findViewById<TextView>(R.id.dialogItemTitle)
        val tvSubtitle = dialogView.findViewById<TextView>(R.id.dialogItemSubtitle)

        val actionCopy = dialogView.findViewById<View>(R.id.actionCopyLink)
        val actionShare = dialogView.findViewById<View>(R.id.actionShareLink)
        val actionDownload = dialogView.findViewById<View>(R.id.actionDownload)
        val actionDelete = dialogView.findViewById<View>(R.id.actionDelete)

        tvTitle.text = item.name

        if (item.isDir) {
            ivIcon.setImageResource(R.drawable.ic_folder)
            tvSubtitle.text = "Папка • ${item.path}"
            actionDownload.visibility = View.GONE // folders are downloaded as zip via public link
        } else {
            when (item.fileType) {
                RemoteFileType.IMAGE -> ivIcon.setImageResource(R.drawable.ic_file_image)
                RemoteFileType.VIDEO -> ivIcon.setImageResource(R.drawable.ic_file_video)
                RemoteFileType.AUDIO -> ivIcon.setImageResource(R.drawable.ic_file_audio)
                RemoteFileType.ARCHIVE -> ivIcon.setImageResource(R.drawable.ic_file_archive)
                else -> ivIcon.setImageResource(R.drawable.ic_file)
            }
            tvSubtitle.text = "${HistoryAdapter.formatFileSize(item.sizeBytes)} • ${item.path}"
            actionDownload.visibility = View.VISIBLE
        }

        // 1. Copy Public Link
        actionCopy.setOnClickListener {
            dialog.dismiss()
            generateAndHandleShareLink(item, copyToClipboardOnly = true)
        }

        // 2. Share Public Link via Android system sheet
        actionShare.setOnClickListener {
            dialog.dismiss()
            generateAndHandleShareLink(item, copyToClipboardOnly = false)
        }

        // 3. Download to Phone
        actionDownload.setOnClickListener {
            dialog.dismiss()
            downloadItemToPhone(item)
        }

        // 4. Delete from Server
        actionDelete.setOnClickListener {
            dialog.dismiss()
            confirmAndDeleteItem(item)
        }

        dialog.show()
    }

    private fun generateAndHandleShareLink(item: RemoteItem, copyToClipboardOnly: Boolean) {
        val progressToast = Toast.makeText(this, "Создание ссылки...", Toast.LENGTH_SHORT)
        progressToast.show()

        lifecycleScope.launch(Dispatchers.IO) {
            val result = api.getOrCreateShareLink(config.serverUrl, config.username, config.password, item.path)

            withContext(Dispatchers.Main) {
                result.onSuccess { shareUrl ->
                    AppLogger.i("ExplorerActivity", "Share link ready: $shareUrl")

                    if (copyToClipboardOnly) {
                        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        val clip = ClipData.newPlainText("DropFile Share Link", shareUrl)
                        clipboard.setPrimaryClip(clip)
                        Toast.makeText(this@ExplorerActivity, "🔗 Ссылка скопирована в буфер!", Toast.LENGTH_SHORT).show()
                    } else {
                        val shareIntent = Intent(Intent.ACTION_SEND).apply {
                            type = "text/plain"
                            putExtra(Intent.EXTRA_SUBJECT, item.name)
                            putExtra(Intent.EXTRA_TEXT, shareUrl)
                        }
                        startActivity(Intent.createChooser(shareIntent, "Поделиться ссылкой на «${item.name}»"))
                    }
                }.onFailure { err ->
                    AppLogger.e("ExplorerActivity", "Failed to create share link for ${item.path}", err)
                    Toast.makeText(this@ExplorerActivity, "Ошибка создания ссылки: ${err.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun downloadItemToPhone(item: RemoteItem) {
        Toast.makeText(this, "Начало скачивания: ${item.name}...", Toast.LENGTH_SHORT).show()

        lifecycleScope.launch(Dispatchers.IO) {
            val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            var targetFile = File(downloadsDir, item.name)

            // If file already exists, create unique name
            var counter = 1
            while (targetFile.exists()) {
                val base = item.name.substringBeforeLast(".")
                val ext = item.name.substringAfterLast(".", "")
                val suffix = if (ext.isNotEmpty()) ".$ext" else ""
                targetFile = File(downloadsDir, "${base}_$counter$suffix")
                counter++
            }

            val result = runCatching {
                FileOutputStream(targetFile).use { fos ->
                    api.downloadFile(config.serverUrl, config.username, config.password, item.path, fos) { downloaded, total ->
                        // Progress callback
                    }.getOrThrow()
                }
            }

            withContext(Dispatchers.Main) {
                result.onSuccess {
                    AppLogger.i("ExplorerActivity", "Downloaded ${item.name} to ${targetFile.absolutePath}")
                    Toast.makeText(this@ExplorerActivity, "✓ Скачано в Загрузки: ${targetFile.name}", Toast.LENGTH_LONG).show()
                }.onFailure { err ->
                    AppLogger.e("ExplorerActivity", "Download failed for ${item.path}", err)
                    targetFile.delete()
                    Toast.makeText(this@ExplorerActivity, "Ошибка скачивания: ${err.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun confirmAndDeleteItem(item: RemoteItem) {
        val typeWord = if (item.isDir) "папку" else "файл"
        MaterialAlertDialogBuilder(this)
            .setTitle("Удалить $typeWord?")
            .setMessage("Вы уверены, что хотите удалить «${item.name}» с сервера?")
            .setPositiveButton("Удалить") { _, _ ->
                lifecycleScope.launch(Dispatchers.IO) {
                    val result = api.deleteResource(config.serverUrl, config.username, config.password, item.path)
                    withContext(Dispatchers.Main) {
                        result.onSuccess {
                            Toast.makeText(this@ExplorerActivity, "Удалено: ${item.name}", Toast.LENGTH_SHORT).show()
                            loadDirectory(currentPath)
                        }.onFailure { err ->
                            Toast.makeText(this@ExplorerActivity, "Ошибка удаления: ${err.message}", Toast.LENGTH_LONG).show()
                        }
                    }
                }
            }
            .setNegativeButton("Отмена", null)
            .show()
    }
}
