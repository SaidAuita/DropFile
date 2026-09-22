package com.dropfile.mobile

import android.app.Activity
import android.content.ClipData
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.dropfile.mobile.api.FileBrowserApi
import com.dropfile.mobile.data.AppLogger
import com.dropfile.mobile.data.ConfigManager
import com.dropfile.mobile.data.HistoryManager
import com.dropfile.mobile.databinding.ActivityMainBinding
import com.dropfile.mobile.ui.HistoryAdapter
import com.dropfile.mobile.ui.LogViewerDialog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var configManager: ConfigManager
    private lateinit var historyManager: HistoryManager
    private lateinit var historyAdapter: HistoryAdapter
    private val api = FileBrowserApi()

    // File picker for picking files from within the app
    private val pickFilesLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val data = result.data!!
            val uris = ArrayList<Uri>()

            if (data.clipData != null) {
                val clip = data.clipData!!
                for (i in 0 until clip.itemCount) {
                    uris.add(clip.getItemAt(i).uri)
                }
            } else if (data.data != null) {
                uris.add(data.data!!)
            }

            if (uris.isNotEmpty()) {
                AppLogger.i("MainActivity", "Files picked: count=${uris.size}, starting SendActivity")
                val sendIntent = Intent(this, SendActivity::class.java).apply {
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    if (uris.size == 1) {
                        action = Intent.ACTION_SEND
                        putExtra(Intent.EXTRA_STREAM, uris[0])
                        clipData = ClipData.newRawUri("file", uris[0])
                    } else {
                        action = Intent.ACTION_SEND_MULTIPLE
                        putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
                        val clip = ClipData.newRawUri("file", uris[0])
                        for (i in 1 until uris.size) {
                            clip.addItem(ClipData.Item(uris[i]))
                        }
                        clipData = clip
                    }
                    type = "*/*"
                }

                try {
                    startActivity(sendIntent)
                } catch (e: Exception) {
                    AppLogger.e("MainActivity", "Failed to start SendActivity", e)
                    Toast.makeText(this, "Ошибка запуска: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AppLogger.init(applicationContext)
        AppLogger.i("MainActivity", "onCreate started")

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        configManager = ConfigManager(this)
        historyManager = HistoryManager(this)

        setupRecyclerView()

        binding.btnLogs.setOnClickListener {
            LogViewerDialog.show(this)
        }

        binding.btnSettings.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        binding.cardSend.setOnClickListener {
            openFilePicker()
        }

        binding.btnQuickTest.setOnClickListener {
            checkConnectionStatus()
        }

        binding.btnClearHistory.setOnClickListener {
            historyManager.clearHistory()
            loadHistory()
        }
    }

    override fun onResume() {
        super.onResume()
        updateConfigCard()
        loadHistory()
        checkConnectionStatus()
    }

    private fun setupRecyclerView() {
        historyAdapter = HistoryAdapter()
        binding.rvHistory.layoutManager = LinearLayoutManager(this)
        binding.rvHistory.adapter = historyAdapter
    }

    private fun loadHistory() {
        val items = historyManager.getHistory()
        if (items.isEmpty()) {
            binding.tvEmptyHistory.visibility = View.VISIBLE
            binding.rvHistory.visibility = View.GONE
        } else {
            binding.tvEmptyHistory.visibility = View.GONE
            binding.rvHistory.visibility = View.VISIBLE
            historyAdapter.updateItems(items)
        }
    }

    private fun updateConfigCard() {
        val config = configManager.getConfig()
        if (!config.isConfigured) {
            binding.tvStatusTitle.text = getString(R.string.server_not_configured)
            binding.tvServerUrl.text = "Нажмите здесь или вверху, чтобы настроить"
            binding.tvTargetFolder.text = "Папка по умолчанию: /Exchange/Mobile"
            binding.statusIndicator.setBackgroundColor(ContextCompat.getColor(this, R.color.status_warning))
            binding.cardStatus.setOnClickListener {
                startActivity(Intent(this, SettingsActivity::class.java))
            }
        } else {
            binding.tvStatusTitle.text = getString(R.string.connection_status)
            binding.tvServerUrl.text = "Сервер: ${config.serverUrl}"
            binding.tvTargetFolder.text = "Папка: ${config.targetFolder}"
            binding.cardStatus.setOnClickListener(null)
        }
    }

    private fun checkConnectionStatus() {
        val config = configManager.getConfig()
        if (!config.isConfigured) return

        binding.btnQuickTest.isEnabled = false

        lifecycleScope.launch(Dispatchers.IO) {
            val result = api.testConnection(config.serverUrl, config.username, config.password)
            withContext(Dispatchers.Main) {
                binding.btnQuickTest.isEnabled = true
                if (result.isSuccess) {
                    binding.tvStatusTitle.text = getString(R.string.server_online)
                    binding.statusIndicator.setBackgroundColor(ContextCompat.getColor(this@MainActivity, R.color.status_success))
                } else {
                    binding.tvStatusTitle.text = getString(R.string.server_offline)
                    binding.statusIndicator.setBackgroundColor(ContextCompat.getColor(this@MainActivity, R.color.status_error))
                }
            }
        }
    }

    private fun openFilePicker() {
        val config = configManager.getConfig()
        if (!config.isConfigured) {
            Toast.makeText(this, "Сначала настройте подключение к серверу", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, SettingsActivity::class.java))
            return
        }

        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        }
        pickFilesLauncher.launch(intent)
    }
}
