package com.dropfile.mobile.data

import android.content.Context
import android.content.SharedPreferences
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

class HistoryManager(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val gson = Gson()

    fun getHistory(): List<UploadItem> {
        val json = prefs.getString(KEY_HISTORY, null) ?: return emptyList()
        return try {
            val type = object : TypeToken<List<UploadItem>>() {}.type
            gson.fromJson<List<UploadItem>>(json, type) ?: emptyList()
        } catch (e: Exception) {
            emptyList()
        }
    }

    fun addItem(item: UploadItem) {
        val current = getHistory().toMutableList()
        current.add(0, item) // add newest to front
        if (current.size > MAX_HISTORY_ITEMS) {
            current.removeAt(current.size - 1)
        }
        prefs.edit().putString(KEY_HISTORY, gson.toJson(current)).apply()
    }

    fun clearHistory() {
        prefs.edit().remove(KEY_HISTORY).apply()
    }

    companion object {
        private const val PREFS_NAME = "dropfile_mobile_history"
        private const val KEY_HISTORY = "history_items"
        private const val MAX_HISTORY_ITEMS = 50
    }
}
