package com.stremer.di

import android.app.Activity
import com.stremer.auth.AuthManager
import com.stremer.saf.SafHelper
import com.stremer.settings.SettingsRepository
import android.net.Uri
import com.stremer.files.FileItem
import kotlinx.coroutines.flow.MutableStateFlow

object ServiceLocator {
    private var saf: SafHelper? = null
    var token: String? = null

    // Expose a Flow so UI can observe storage selection changes
    val rootSetFlow = MutableStateFlow(false)

    fun init(activity: Activity) {
        saf = SafHelper(activity)
        SettingsRepository.init(activity)
        // Initialize flow with current state
        // Try to restore previously saved root URI from settings
        try {
            val stored = SettingsRepository.getRootUri()
            if (stored != null) {
                try {
                    val uri = Uri.parse(stored)
                    saf?.setRoot(uri)
                    android.util.Log.d("ServiceLocator", "Restored storage root from settings: $stored")
                } catch (e: Exception) {
                    android.util.Log.e("ServiceLocator", "Failed to restore root URI: $stored", e)
                }
            }
        } catch (e: Exception) {
            // ignore
        }
        rootSetFlow.value = saf?.rootUri != null
    }

    fun setRoot(uri: Uri) {
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
        return saf?.rootUri != null
    }

    fun validate(username: String?, password: String?): Boolean {
        if (username == null || password == null) return false
        return AuthManager.validate(username, password)
    }

    fun issueTokenFor(user: String) { token = "token-$user" }

    fun safList(path: String): List<FileItem> {
        val result = saf?.listFiles(path) ?: emptyList()
        android.util.Log.d("ServiceLocator", "safList($path) returned ${result.size} items")
        return result
    }

    fun getFileInfo(path: String): FileItem? {
        return saf?.getFileInfo(path)
    }

    fun openInputStream(path: String) = saf?.openInputStream(path)

    fun getUri(path: String) = saf?.getUri(path)

    fun context(): android.content.Context? = saf?.getContext()

    fun getDocumentFile(path: String): androidx.documentfile.provider.DocumentFile? = saf?.getFile(path)

    fun delete(path: String) = saf?.deleteFile(path) ?: false
    fun copy(src: String, dst: String) = saf?.copyFile(src, dst) ?: false
    fun rename(path: String, newName: String) = saf?.renameFile(path, newName) ?: false
    fun mkdir(parentPath: String, name: String) = saf?.createDirectory(parentPath, name) ?: false
    fun createFile(parentPath: String, name: String, mime: String? = null) = saf?.createFile(parentPath, name, mime) ?: false
    fun writeBytes(path: String, data: ByteArray, mime: String? = null) = saf?.writeBytes(path, data, mime) ?: false
    suspend fun writeStream(path: String, channel: io.ktor.utils.io.ByteReadChannel, mime: String? = null) = saf?.writeStream(path, channel, mime) ?: false

    // Optional: clear stored root (not used currently but convenient)
    fun clearRoot() {
        saf?.rootUri = null
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
