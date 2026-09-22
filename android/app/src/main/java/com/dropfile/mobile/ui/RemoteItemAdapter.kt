package com.dropfile.mobile.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.dropfile.mobile.R
import com.dropfile.mobile.data.RemoteFileType
import com.dropfile.mobile.data.RemoteItem

class RemoteItemAdapter(
    private var items: List<RemoteItem> = emptyList(),
    private val onItemClick: (RemoteItem) -> Unit,
    private val onItemMenuClick: (RemoteItem) -> Unit
) : RecyclerView.Adapter<RemoteItemAdapter.ViewHolder>() {

    fun updateItems(newItems: List<RemoteItem>) {
        items = newItems
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_remote_item, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        holder.bind(items[position])
    }

    override fun getItemCount(): Int = items.size

    inner class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val ivIcon: ImageView = itemView.findViewById(R.id.ivItemIcon)
        private val tvName: TextView = itemView.findViewById(R.id.tvItemName)
        private val tvDetails: TextView = itemView.findViewById(R.id.tvItemDetails)
        private val btnActions: ImageButton = itemView.findViewById(R.id.btnItemActions)

        fun bind(item: RemoteItem) {
            tvName.text = item.name

            if (item.isDir) {
                ivIcon.setImageResource(R.drawable.ic_folder)
                ivIcon.clearColorFilter()
                tvDetails.text = "Папка"
            } else {
                when (item.fileType) {
                    RemoteFileType.IMAGE -> ivIcon.setImageResource(R.drawable.ic_file_image)
                    RemoteFileType.VIDEO -> ivIcon.setImageResource(R.drawable.ic_file_video)
                    RemoteFileType.AUDIO -> ivIcon.setImageResource(R.drawable.ic_file_audio)
                    RemoteFileType.ARCHIVE -> ivIcon.setImageResource(R.drawable.ic_file_archive)
                    else -> ivIcon.setImageResource(R.drawable.ic_file)
                }
                ivIcon.clearColorFilter()

                val sizeFormatted = HistoryAdapter.formatFileSize(item.sizeBytes)
                val dateFormatted = item.modified?.take(10)?.replace("-", ".") ?: ""
                tvDetails.text = if (dateFormatted.isNotBlank()) "$sizeFormatted • $dateFormatted" else sizeFormatted
            }

            itemView.setOnClickListener {
                onItemClick(item)
            }

            btnActions.setOnClickListener {
                onItemMenuClick(item)
            }
        }
    }
}
