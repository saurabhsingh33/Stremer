package com.stremer.api

import kotlinx.serialization.Serializable

@Serializable
data class MetaResponse(
    val name: String,
    val type: String, // "file" or "dir"
    val mime: String? = null,
    val size: Long? = null,
    val lastModified: Long? = null,
    val width: Int? = null,
    val height: Int? = null,
    val durationMs: Long? = null,
    val itemCount: Int? = null,
)
