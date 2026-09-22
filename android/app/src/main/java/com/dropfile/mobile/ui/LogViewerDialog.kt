package com.dropfile.mobile.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Typeface
import android.view.ViewGroup
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.dropfile.mobile.data.AppLogger

object LogViewerDialog {

    fun show(context: Context) {
        val scrollView = ScrollView(context).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            setPadding(32, 16, 32, 16)
        }

        val tvLogs = TextView(context).apply {
            typeface = Typeface.MONOSPACE
            textSize = 12f
            setTextIsSelectable(true)
            text = AppLogger.getLogs()
        }
        scrollView.addView(tvLogs)

        MaterialAlertDialogBuilder(context)
            .setTitle("📋 Журнал работы (Логи)")
            .setView(scrollView)
            .setPositiveButton("Скопировать") { _, _ ->
                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val clip = ClipData.newPlainText("DropFile Logs", AppLogger.getLogs())
                clipboard.setPrimaryClip(clip)
                Toast.makeText(context, "Логи скопированы в буфер обмена", Toast.LENGTH_SHORT).show()
            }
            .setNeutralButton("Очистить") { _, _ ->
                AppLogger.clear()
                Toast.makeText(context, "Журнал очищен", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("Закрыть", null)
            .show()
    }
}
