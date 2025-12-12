package com.stremer.di

import android.app.Activity
import com.stremer.auth.AuthManager
import com.stremer.saf.SafHelper
import com.stremer.storage.FileStorageHelper
import com.stremer.settings.SettingsRepository
import android.net.Uri
import com.stremer.files.FileItem
import kotlinx.coroutines.flow.MutableStateFlow

object ServiceLocator {
    private var saf: SafHelper? = null
    private var fileStorage: FileStorageHelper? = null
    private var useFileStorage = false
    var token: String? = null

    // Expose a Flow so UI can observe storage selection changes
    val rootSetFlow = MutableStateFlow(false)

    fun init(activity: Activity) {
        saf = SafHelper(activity)
        fileStorage = FileStorageHelper(activity)
        useFileStorage = fileStorage?.canUseFullAccess() ?: false

        SettingsRepository.init(activity)
        // Initialize flow with current state
        // Try to restore previously saved root URI from settings
        try {
            val stored = SettingsRepository.getRootUri()
            if (stored != null) {
                try {
                    if (useFileStorage) {
                        // Try to use file storage path
                        fileStorage?.setRoot(stored)
                        android.util.Log.d("ServiceLocator", "Using FileStorageHelper for full device access")
                    } else {
                        // Fall back to SAF
                        val uri = Uri.parse(stored)
                        saf?.setRoot(uri)
                        android.util.Log.d("ServiceLocator", "Using SAF for storage access")
                    }
                } catch (e: Exception) {
                    android.util.Log.e("ServiceLocator", "Failed to restore root: $stored", e)
                }
            }
        } catch (e: Exception) {
            // ignore
        }
        rootSetFlow.value = isRootSet()
    }

    fun setRoot(uri: Uri) {
        if (useFileStorage) {
            // Try to extract file path from URI or use string representation
            val path = try {
                uri.path ?: uri.toString()
            } catch (e: Exception) {
                uri.toString()
            }
            try {
                fileStorage?.setRoot(path)
                SettingsRepository.setRootUri(path)
                rootSetFlow.value = true
                return
            } catch (e: Exception) {
                android.util.Log.w("ServiceLocator", "Failed to set file path, falling back to SAF: ${e.message}")
            }
        }
        // Fall back to SAF
        saf?.setRoot(uri)
        android.util.Log.d("ServiceLocator", "Storage root set to: $uri")
        try {
            SettingsRepository.setRootUri(uri.toString())
        } catch (e: Exception) {
            // ignore
        }
        rootSetFlow.value = true
    }

    fun isRootSet(): Boolean {
        return if (useFileStorage) {
            fileStorage?.getRootPath() != null
        } else {
            saf?.rootUri != null
        }
    }

    fun validate(username: String?, password: String?): Boolean {
        if (username == null || password == null) return false
        return AuthManager.validate(username, password)
    }

    fun issueTokenFor(user: String) { token = "token-$user" }

    fun safList(path: String): List<FileItem> {
        val result = if (useFileStorage) {
            fileStorage?.listFiles(path) ?: emptyList()
        } else {
            saf?.listFiles(path) ?: emptyList()
        }
        android.util.Log.d("ServiceLocator", "safList($path) returned ${result.size} items")
        return result
    }

    fun getFileInfo(path: String): FileItem? {
        return if (useFileStorage) {
            fileStorage?.getFileInfo(path)
        } else {
            saf?.getFileInfo(path)
        }
    }

    fun openInputStream(path: String) = if (useFileStorage) {
        fileStorage?.openInputStream(path)
    } else {
        saf?.openInputStream(path)
    }

    fun getUri(path: String) = saf?.getUri(path)

    fun context(): android.content.Context? = saf?.getContext()

    fun getDocumentFile(path: String): androidx.documentfile.provider.DocumentFile? = saf?.getFile(path)

    fun delete(path: String) = if (useFileStorage) {
        fileStorage?.deleteFile(path) ?: false
    } else {
        saf?.deleteFile(path) ?: false
    }

    fun copy(src: String, dst: String) = if (useFileStorage) {
        fileStorage?.copyFile(src, dst) ?: false
    } else {
        saf?.copyFile(src, dst) ?: false
    }

    fun rename(path: String, newName: String) = if (useFileStorage) {
        fileStorage?.renameFile(path, newName) ?: false
    } else {
        saf?.renameFile(path, newName) ?: false
    }

    fun mkdir(parentPath: String, name: String) = if (useFileStorage) {
        fileStorage?.createDirectory(parentPath, name) ?: false
    } else {
        saf?.createDirectory(parentPath, name) ?: false
    }

    fun createFile(parentPath: String, name: String, mime: String? = null) = saf?.createFile(parentPath, name, mime) ?: false
    fun writeBytes(path: String, data: ByteArray, mime: String? = null) = saf?.writeBytes(path, data, mime) ?: false
    suspend fun writeStream(path: String, channel: io.ktor.utils.io.ByteReadChannel, mime: String? = null) = saf?.writeStream(path, channel, mime) ?: false

    // Optional: clear stored root (not used currently but convenient)
    fun clearRoot() {
        if (useFileStorage) {
            fileStorage?.setRoot("")
        } else {
            saf?.rootUri = null
        }
        try {
            SettingsRepository.setRootUri(null)
        } catch (e: Exception) {
            // ignore
        }
        rootSetFlow.value = false
    }

    /**
     * Return a friendly display string for the currently-selected root, or null if none.
     */
    fun getRootDisplayName(): String? {
        return try {
            saf?.rootDisplayName()
        } catch (e: Exception) {
            android.util.Log.w("ServiceLocator", "getRootDisplayName failed: ${e.message}")
            null
        }
    }
}
