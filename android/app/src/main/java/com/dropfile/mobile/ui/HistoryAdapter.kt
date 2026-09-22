package com.dropfile.mobile.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.dropfile.mobile.R
import com.dropfile.mobile.data.UploadItem
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class HistoryAdapter(
    private var items: List<UploadItem> = emptyList()
) : RecyclerView.Adapter<HistoryAdapter.ViewHolder>() {

    private val dateFormat = SimpleDateFormat("dd.MM HH:mm", Locale.getDefault())

    fun updateItems(newItems: List<UploadItem>) {
        items = newItems
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_upload_history, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        holder.bind(items[position])
    }

    override fun getItemCount(): Int = items.size

    inner class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val ivIcon: ImageView = itemView.findViewById(R.id.ivItemIcon)
        private val tvFilename: TextView = itemView.findViewById(R.id.tvItemFilename)
        private val tvDetails: TextView = itemView.findViewById(R.id.tvItemDetails)
        private val ivStatus: ImageView = itemView.findViewById(R.id.ivItemStatus)

        fun bind(item: UploadItem) {
            tvFilename.text = item.filename
            val sizeFormatted = formatFileSize(item.sizeBytes)
            val dateFormatted = dateFormat.format(Date(item.timestamp))

            if (item.isSuccess) {
                tvDetails.text = "$sizeFormatted • $dateFormatted • ${item.targetFolder}"
                ivStatus.setImageResource(R.drawable.ic_check_circle)
                ivStatus.setColorFilter(ContextCompat.getColor(itemView.context, R.color.status_success))
            } else {
                val err = item.errorMessage ?: "Ошибка передачи"
                tvDetails.text = "$sizeFormatted • $dateFormatted • $err"
                ivStatus.setImageResource(R.drawable.ic_error)
                ivStatus.setColorFilter(ContextCompat.getColor(itemView.context, R.color.status_error))
            }

            // Set icon depending on file extension
            val lower = item.filename.lowercase()
            if (lower.endsWith(".jpg") || lower.endsWith(".jpeg") || lower.endsWith(".png") || lower.endsWith(".webp") || lower.endsWith(".gif")) {
                ivIcon.setImageResource(R.drawable.ic_file)
                ivIcon.setColorFilter(ContextCompat.getColor(itemView.context, R.color.primary))
            } else {
                ivIcon.setImageResource(R.drawable.ic_file)
                ivIcon.setColorFilter(ContextCompat.getColor(itemView.context, R.color.text_secondary))
            }
        }
    }

    companion object {
        fun formatFileSize(bytes: Long): String {
            if (bytes <= 0) return "0 Б"
            if (bytes < 1024) return "$bytes Б"
            val kb = bytes / 1024.0
            if (kb < 1024) return String.format(Locale.US, "%.1f КБ", kb)
            val mb = kb / 1024.0
            if (mb < 1024) return String.format(Locale.US, "%.1f МБ", mb)
            val gb = mb / 1024.0
            return String.format(Locale.US, "%.2f ГБ", gb)
        }
    }
}
