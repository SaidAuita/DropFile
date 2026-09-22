package com.dropfile.mobile

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.dropfile.mobile.api.FileBrowserApi
import com.dropfile.mobile.data.AppConfig
import com.dropfile.mobile.data.ConfigManager
import com.dropfile.mobile.databinding.ActivitySettingsBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.OutputStreamWriter

class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding
    private lateinit var configManager: ConfigManager
    private val api = FileBrowserApi()

    // File picker for importing JSON config
    private val importConfigLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val uri: Uri? = result.data?.data
            if (uri != null) {
                importConfigFromUri(uri)
            }
        }
    }

    // File picker for exporting JSON config
    private val exportConfigLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val uri: Uri? = result.data?.data
            if (uri != null) {
                exportConfigToUri(uri)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        configManager = ConfigManager(this)

        binding.toolbar.setNavigationOnClickListener {
            finish()
        }

        loadSettingsToUi()

        binding.btnSaveSettings.setOnClickListener {
            saveSettingsFromUi()
        }

        binding.btnTestConnection.setOnClickListener {
            runConnectionTest()
        }

        binding.btnImportConfig.setOnClickListener {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
                putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/json", "text/plain", "text/json", "*/*"))
            }
            importConfigLauncher.launch(intent)
        }

        binding.btnExportConfig.setOnClickListener {
            val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/json"
                putExtra(Intent.EXTRA_TITLE, "dropfile_mobile_config.json")
            }
            exportConfigLauncher.launch(intent)
        }
    }

    private fun loadSettingsToUi() {
        val config = configManager.getConfig()
        binding.etServerUrl.setText(config.serverUrl)
        binding.etUsername.setText(config.username)
        binding.etPassword.setText(config.password)
        binding.etTargetFolder.setText(config.targetFolder)
        binding.switchAutoClose.isChecked = config.autoClose
    }

    private fun saveSettingsFromUi() {
        val serverUrl = binding.etServerUrl.text?.toString().orEmpty()
        val username = binding.etUsername.text?.toString().orEmpty()
        val password = binding.etPassword.text?.toString().orEmpty()
        val targetFolder = binding.etTargetFolder.text?.toString().orEmpty()
        val autoClose = binding.switchAutoClose.isChecked

        val config = AppConfig(
            serverUrl = serverUrl,
            username = username,
            password = password,
            targetFolder = if (targetFolder.isBlank()) "/Exchange/Mobile" else targetFolder,
            autoClose = autoClose
        )

        configManager.saveConfig(config)
        Toast.makeText(this, R.string.settings_saved, Toast.LENGTH_SHORT).show()
        finish()
    }

    private fun runConnectionTest() {
        val serverUrl = binding.etServerUrl.text?.toString().orEmpty().trim()
        val username = binding.etUsername.text?.toString().orEmpty().trim()
        val password = binding.etPassword.text?.toString().orEmpty()

        if (serverUrl.isBlank() || username.isBlank()) {
            Toast.makeText(this, "Укажите URL сервера и имя пользователя", Toast.LENGTH_SHORT).show()
            return
        }

        binding.btnTestConnection.isEnabled = false
        binding.btnTestConnection.text = getString(R.string.testing_connection)

        lifecycleScope.launch(Dispatchers.IO) {
            val result = api.testConnection(serverUrl, username, password)
            withContext(Dispatchers.Main) {
                binding.btnTestConnection.isEnabled = true
                binding.btnTestConnection.text = getString(R.string.test_connection)

                result.onSuccess { msg ->
                    Toast.makeText(this@SettingsActivity, msg, Toast.LENGTH_LONG).show()
                }.onFailure { err ->
                    Toast.makeText(
                        this@SettingsActivity,
                        "Ошибка: ${err.localizedMessage ?: err.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }

    private fun importConfigFromUri(uri: Uri) {
        lifecycleScope.launch(Dispatchers.IO) {
            val result = runCatching {
                contentResolver.openInputStream(uri)?.use { stream ->
                    configManager.importFromJsonStream(stream).getOrThrow()
                } ?: throw IllegalStateException("Не удалось открыть файл")
            }

            withContext(Dispatchers.Main) {
                result.onSuccess { importedConfig ->
                    loadSettingsToUi()
                    Toast.makeText(
                        this@SettingsActivity,
                        R.string.config_imported_success,
                        Toast.LENGTH_SHORT
                    ).show()
                    // Auto-run connection test after import
                    runConnectionTest()
                }.onFailure { err ->
                    Toast.makeText(
                        this@SettingsActivity,
                        "Ошибка импорта: ${err.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }

    private fun exportConfigToUri(uri: Uri) {
        lifecycleScope.launch(Dispatchers.IO) {
            val json = configManager.exportToJsonString()
            val result = runCatching {
                contentResolver.openOutputStream(uri)?.use { stream ->
                    OutputStreamWriter(stream, Charsets.UTF_8).use { writer ->
                        writer.write(json)
                    }
                } ?: throw IllegalStateException("Не удалось записать файл")
            }

            withContext(Dispatchers.Main) {
                result.onSuccess {
                    Toast.makeText(
                        this@SettingsActivity,
                        "Настройки экспортированы!",
                        Toast.LENGTH_SHORT
                    ).show()
                }.onFailure { err ->
                    Toast.makeText(
                        this@SettingsActivity,
                        "Ошибка экспорта: ${err.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }
}
