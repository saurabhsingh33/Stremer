package com.stremer.saf

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import androidx.documentfile.provider.DocumentFile

class SafHelper(private val activity: Activity) {
    var rootUri: Uri? = null

    fun setRoot(uri: Uri) {
        rootUri = uri
        activity.contentResolver.takePersistableUriPermission(
            uri,
            Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        )
    }

    private fun root(): DocumentFile? {
        val base = rootUri ?: return null
        return DocumentFile.fromTreeUri(activity, base)
    }

    private fun resolve(path: String): DocumentFile? {
        val docRoot = root() ?: return null
        val cleaned = path.trim('/')
        if (cleaned.isEmpty()) return docRoot
        var current: DocumentFile = docRoot
        val segments = cleaned.split('/')
        for (seg in segments) {
            val next = current.findFile(seg) ?: return null
            current = next
        }
        return current
    }

    fun listFiles(path: String = ""): List<com.stremer.files.FileItem> {
        android.util.Log.d("SafHelper", "listFiles called with path: '$path', rootUri: $rootUri")
        val target = resolve(path)
        if (target == null) {
            android.util.Log.e("SafHelper", "Failed to resolve path: '$path'")
            return emptyList()
        }
        val files = target.listFiles()
        android.util.Log.d("SafHelper", "Found ${files.size} files")
        if (files.isEmpty()) return emptyList()
        return files.mapNotNull { f ->
            try {
                com.stremer.files.FileItem(
                    name = f.name ?: "unknown",
                    type = if (f.isDirectory) "dir" else "file",
                    size = if (f.isFile) f.length() else null
                )
            } catch (e: Exception) {
                android.util.Log.e("SafHelper", "Error processing file: ${e.message}")
                null
            }
        }
    }

    fun getFile(path: String): DocumentFile? {
        return resolve(path)
    }

    fun getUri(path: String): Uri? {
        return getFile(path)?.uri
    }

    fun getFileInfo(path: String): com.stremer.files.FileItem? {
        val file = getFile(path) ?: return null
        return try {
            com.stremer.files.FileItem(
                name = file.name ?: "unknown",
                type = if (file.isDirectory) "dir" else "file",
                size = if (file.isFile) file.length() else null
            )
        } catch (e: Exception) {
            android.util.Log.e("SafHelper", "Error getting file info: ${e.message}")
            null
        }
    }

    fun deleteFile(path: String): Boolean {
        return getFile(path)?.delete() ?: false
    }

    fun copyFile(src: String, dst: String): Boolean {
        val srcFile = getFile(src) ?: return false
        val dstClean = dst.trim('/')
        val dstSegments = dstClean.split('/').toMutableList()
        val dstName = dstSegments.removeLastOrNull() ?: return false
        // Ensure parent directory exists (create missing)
        var parent = root() ?: return false
        for (seg in dstSegments) {
            val next = parent.findFile(seg) ?: parent.createDirectory(seg) ?: return false
            parent = next
        }
        val dstFile = parent.createFile(srcFile.type ?: "application/octet-stream", dstName) ?: return false
        val inStream = activity.contentResolver.openInputStream(srcFile.uri) ?: return false
        val outStream = activity.contentResolver.openOutputStream(dstFile.uri) ?: return false
        inStream.use { input ->
            outStream.use { output ->
                input.copyTo(output)
            }
        }
        return true
    }

    fun renameFile(path: String, newName: String): Boolean {
        val file = getFile(path) ?: return false
        return try {
            file.renameTo(newName)
        } catch (e: Exception) {
            android.util.Log.e("SafHelper", "Rename failed: ${e.message}")
            false
        }
    }

    fun openInputStream(path: String) = getFile(path)?.let { file ->
        activity.contentResolver.openInputStream(file.uri)
    }

    fun getContext(): android.content.Context = activity

    fun createDirectory(parentPath: String, name: String): Boolean {
        val parent = resolve(parentPath) ?: return false
        if (!parent.isDirectory) return false
        // Do not overwrite existing
        parent.findFile(name)?.let { return false }
        return try {
            parent.createDirectory(name) != null
        } catch (e: Exception) {
            android.util.Log.e("SafHelper", "Create directory failed: ${e.message}")
            false
        }
    }

    private fun guessMime(name: String): String {
        val lower = name.lowercase()
        return when {
            lower.endsWith(".txt") -> "text/plain"
            lower.endsWith(".md") -> "text/markdown"
            lower.endsWith(".json") -> "application/json"
            lower.endsWith(".jpg") || lower.endsWith(".jpeg") -> "image/jpeg"
            lower.endsWith(".png") -> "image/png"
            lower.endsWith(".gif") -> "image/gif"
            lower.endsWith(".mp4") -> "video/mp4"
            lower.endsWith(".mkv") -> "video/x-matroska"
            else -> "application/octet-stream"
        }
    }

    fun createFile(parentPath: String, name: String, mime: String? = null): Boolean {
        val parent = resolve(parentPath) ?: return false
        if (!parent.isDirectory) return false
        // Do not overwrite existing
        parent.findFile(name)?.let { return false }
        val chosenMime = mime ?: guessMime(name)
        return try {
            val df = parent.createFile(chosenMime, name) ?: return false
            // Create zero-byte file (stream closed immediately)
            activity.contentResolver.openOutputStream(df.uri)?.use { /* no-op */ }
            true
        } catch (e: Exception) {
            android.util.Log.e("SafHelper", "Create file failed: ${e.message}")
            false
        }
    }
}
