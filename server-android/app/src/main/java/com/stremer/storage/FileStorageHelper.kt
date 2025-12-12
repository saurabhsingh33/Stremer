package com.stremer.storage

import android.app.Activity
import android.os.Build
import android.os.Environment
import java.io.File

/**
 * FileStorageHelper provides direct File API access to the full device storage
 * when MANAGE_ALL_FILES permission is available (API 30+).
 * Falls back gracefully if permission not granted.
 */
class FileStorageHelper(private val activity: Activity) {
    private var rootPath: String? = null

    fun canUseFullAccess(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return false
        return try {
            activity.checkSelfPermission("android.permission.MANAGE_ALL_FILES") ==
                android.content.pm.PackageManager.PERMISSION_GRANTED
        } catch (e: Exception) {
            false
        }
    }

    fun setRoot(path: String) {
        // Validate the path exists and is a directory
        val file = File(path)
        if (file.exists() && file.isDirectory) {
            rootPath = path
        } else {
            throw IllegalArgumentException("Invalid path: $path")
        }
    }

    fun getRootPath(): String? = rootPath

    fun getRootFile(): File? = rootPath?.let { File(it) }

    private fun resolve(path: String): File? {
        val root = rootPath?.let { File(it) } ?: return null
        if (path.trim('/').isEmpty()) return root

        val target = File(root, path.trim('/'))
        // Security check: ensure the resolved path is within the root
        if (!target.canonicalPath.startsWith(root.canonicalPath)) {
            return null
        }
        return if (target.exists()) target else null
    }

    fun listFiles(path: String = ""): List<com.stremer.files.FileItem> {
        val target = resolve(path) ?: return emptyList()
        if (!target.isDirectory) return emptyList()

        return try {
            target.listFiles()?.mapNotNull { file ->
                try {
                    com.stremer.files.FileItem(
                        name = file.name,
                        type = if (file.isDirectory) "dir" else "file",
                        size = if (file.isFile) file.length() else null,
                        lastModified = file.lastModified(),
                        path = buildPath(path, file.name)
                    )
                } catch (e: Exception) {
                    null
                }
            } ?: emptyList()
        } catch (e: Exception) {
            android.util.Log.e("FileStorageHelper", "Error listing files: ${e.message}")
            emptyList()
        }
    }

    fun getFile(path: String): File? = resolve(path)

    fun getFileInfo(path: String): com.stremer.files.FileItem? {
        val file = getFile(path) ?: return null
        return try {
            com.stremer.files.FileItem(
                name = file.name,
                type = if (file.isDirectory) "dir" else "file",
                size = if (file.isFile) file.length() else null,
                lastModified = file.lastModified(),
                path = "/${path.trim('/')}"
            )
        } catch (e: Exception) {
            null
        }
    }

    private fun buildPath(parent: String, name: String): String {
        val base = parent.trim('/')
        return if (base.isEmpty()) "/$name" else "/$base/$name"
    }

    fun deleteFile(path: String): Boolean {
        return getFile(path)?.deleteRecursively() ?: false
    }

    fun copyFile(src: String, dst: String): Boolean {
        val srcFile = getFile(src) ?: return false
        val dstPath = dst.trim('/')
        val dstSegments = dstPath.split('/').toMutableList()
        val dstName = dstSegments.removeLastOrNull() ?: return false

        var parent = rootPath?.let { File(it) } ?: return false
        for (seg in dstSegments) {
            val next = File(parent, seg)
            if (!next.exists()) {
                if (!next.mkdir()) return false
            }
            parent = next
        }

        val dstFile = File(parent, dstName)
        return try {
            srcFile.copyTo(dstFile, overwrite = true)
            true
        } catch (e: Exception) {
            false
        }
    }

    fun renameFile(path: String, newName: String): Boolean {
        val file = getFile(path) ?: return false
        val parent = file.parentFile ?: return false
        val newFile = File(parent, newName)
        return file.renameTo(newFile)
    }

    fun openInputStream(path: String) = getFile(path)?.inputStream()

    fun createDirectory(parentPath: String, name: String): Boolean {
        val parent = resolve(parentPath) ?: return false
        if (!parent.isDirectory) return false
        val newDir = File(parent, name)
        return if (!newDir.exists()) {
            newDir.mkdir()
        } else {
            false
        }
    }

    fun getExternalStoragePath(): String? {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.getExternalStorageDirectory().absolutePath
        } else {
            null
        }
    }

    fun rootDisplayName(): String? {
        val path = rootPath ?: return null
        return File(path).name.takeIf { it.isNotEmpty() } ?: path
    }
}
