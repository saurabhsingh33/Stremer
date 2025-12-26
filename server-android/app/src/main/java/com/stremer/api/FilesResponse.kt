package com.stremer.api

import com.stremer.files.FileItem
import kotlinx.serialization.Serializable

@Serializable
data class FilesResponse(
    val items: List<FileItem>,
    val total: Int,
    val offset: Int,
    val limit: Int,
    val error: String? = null
)
