package com.stremer.files

import kotlinx.serialization.Serializable

@Serializable
data class FileItem(
    val name: String,
    val type: String, // "file" or "dir"
    val size: Long? = null
)
