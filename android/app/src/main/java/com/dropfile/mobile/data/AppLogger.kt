package com.dropfile.mobile.data

import android.content.Context
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object AppLogger {
    private const val TAG = "DropFileMobile"
    private val buffer = mutableListOf<String>()
    private val dateFormat = SimpleDateFormat("HH:mm:ss.SSS", Locale.getDefault())
    private var logFile: File? = null

    fun init(context: Context) {
        if (logFile == null) {
            logFile = File(context.filesDir, "dropfile_debug.log")
            
            // Set up uncaught exception handler to record crashes
            val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
            Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
                e("CRASH", "FATAL CRASH in thread '${thread.name}': ${throwable.message}", throwable)
                defaultHandler?.uncaughtException(thread, throwable)
            }
            
            i("AppLogger", "=== DropFile Mobile Started ===")
            i("AppLogger", "Device: ${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}")
            i("AppLogger", "Android ${android.os.Build.VERSION.RELEASE} (API ${android.os.Build.VERSION.SDK_INT})")
        }
    }

    @Synchronized
    private fun addLogLine(level: String, tag: String, message: String) {
        val timestamp = dateFormat.format(Date())
        val line = "[$timestamp] [$level] [$tag] $message"
        buffer.add(line)
        if (buffer.size > 1000) {
            buffer.removeAt(0)
        }
        try {
            logFile?.appendText("$line\n")
        } catch (_: Exception) {}
    }

    fun i(tag: String, message: String) {
        Log.i(TAG, "[$tag] $message")
        addLogLine("INFO", tag, message)
    }

    fun d(tag: String, message: String) {
        Log.d(TAG, "[$tag] $message")
        addLogLine("DEBUG", tag, message)
    }

    fun w(tag: String, message: String) {
        Log.w(TAG, "[$tag] $message")
        addLogLine("WARN", tag, message)
    }

    fun e(tag: String, message: String, throwable: Throwable? = null) {
        val stackTrace = if (throwable != null) "\n" + Log.getStackTraceString(throwable) else ""
        Log.e(TAG, "[$tag] $message$stackTrace")
        addLogLine("ERROR", tag, "$message$stackTrace")
    }

    @Synchronized
    fun getLogs(): String {
        return if (buffer.isNotEmpty()) {
            buffer.joinToString("\n")
        } else {
            try {
                if (logFile?.exists() == true) logFile!!.readText() else "Логи пусты"
            } catch (e: Exception) {
                "Не удалось прочитать логи: ${e.message}"
            }
        }
    }

    @Synchronized
    fun clear() {
        buffer.clear()
        try {
            logFile?.writeText("")
        } catch (_: Exception) {}
        i("AppLogger", "Логи очищены")
    }
}
