package com.stremer.di

import android.app.Activity
import com.stremer.auth.AuthManager
import com.stremer.saf.SafHelper
import com.stremer.storage.FileStorageHelper
import com.stremer.settings.SettingsRepository
import android.net.Uri
import com.stremer.files.FileItem
import kotlinx.coroutines.flow.MutableStateFlow
import com.stremer.camera.CameraStreamer

object ServiceLocator {
    private var saf: SafHelper? = null
    private var fileStorage: FileStorageHelper? = null
    private var useFileStorage = false
    private var activityRef: Activity? = null
    private var cameraStreamer: CameraStreamer? = null
    private var cameraEnabled: Boolean = false
    var token: String? = null

    // Expose a Flow so UI can observe storage selection changes
    val rootSetFlow = MutableStateFlow(false)

    fun init(activity: Activity) {
        activityRef = activity
        saf = SafHelper(activity)
        fileStorage = FileStorageHelper(activity)
        useFileStorage = fileStorage?.canUseFullAccess() ?: false

        SettingsRepository.init(activity)
        cameraEnabled = SettingsRepository.isCameraEnabled()
        // Initialize flow with current state
        // Try to restore previously saved root URIs from settings
        try {
            val storedUris = SettingsRepository.getRootUris()
            if (storedUris.isNotEmpty()) {
                try {
                    for ((index, uriString) in storedUris.withIndex()) {
                        if (useFileStorage) {
                            // Try to use file storage path
                            if (index == 0) {
                                fileStorage?.setRoot(uriString)
                            }
                            android.util.Log.d("ServiceLocator", "Using FileStorageHelper for full device access")
                        } else {
                            // Fall back to SAF
                            val uri = Uri.parse(uriString)
                            // Generate a friendly name from the URI
                            val name = extractFolderName(uriString, index)
                            saf?.addRoot(name, uri)
                            android.util.Log.d("ServiceLocator", "Added root: $name")
                        }
                    }
                    android.util.Log.d("ServiceLocator", "Restored ${storedUris.size} root(s)")
                } catch (e: Exception) {
                    android.util.Log.e("ServiceLocator", "Failed to restore roots", e)
                }
            }
        } catch (e: Exception) {
            // ignore
        }
        rootSetFlow.value = isRootSet()
    }

    fun cameraSnapshot(lens: String? = null, brightness: Int? = null, sharpness: Int? = null): ByteArray? {
        if (!cameraEnabled) return null
        val ok = startCameraStream(lens, brightness, sharpness)
        if (!ok) return null
        val frame = nextCameraFrame(1500)
        if (frame == null) {
            android.util.Log.e("ServiceLocator", "cameraSnapshot failed: no frame")
        }
        return frame
    }

    private fun extractFolderName(uriString: String, index: Int): String {
        return try {
            val uri = Uri.parse(uriString)
            val lastSeg = uri.lastPathSegment ?: return "Folder${index + 1}"
            val candidate = lastSeg.split('/').lastOrNull() ?: lastSeg
            val baseName = if (candidate.contains(":")) {
                val parts = candidate.split(":", limit = 2)
                val rest = parts.getOrNull(1) ?: return "Folder${index + 1}"
                rest.split('/').lastOrNull()?.takeIf { it.isNotEmpty() } ?: "Folder${index + 1}"
            } else {
                candidate.takeIf { it.isNotEmpty() } ?: "Folder${index + 1}"
            }

            // Check if name already exists, if so make it unique
            val existingRoots = saf?.getRoots()?.keys ?: emptySet()
            if (existingRoots.contains(baseName)) {
                // Name collision - append disambiguator based on path segments
                var uniqueName = baseName
                var counter = 2

                // Try to extract parent path for disambiguation
                val pathParts = lastSeg.split('/')
                if (pathParts.size > 1) {
                    val parentName = pathParts.getOrNull(pathParts.size - 2)
                    if (parentName != null && parentName.isNotEmpty() && !parentName.contains(":")) {
                        uniqueName = "$baseName ($parentName)"
                        if (!existingRoots.contains(uniqueName)) {
                            return uniqueName
                        }
                    }
                }

                // Fallback: append counter
                while (existingRoots.contains(uniqueName)) {
                    uniqueName = "$baseName ($counter)"
                    counter++
                }
                return uniqueName
            }

            baseName
        } catch (e: Exception) {
            "Folder${index + 1}"
        }
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
        // Fall back to SAF - generate friendly name
        val name = extractFolderName(uri.toString(), saf?.getRoots()?.size ?: 0)
        saf?.addRoot(name, uri)
        android.util.Log.d("ServiceLocator", "Storage root added: $name")

        // Save all roots
        val allRoots = saf?.getRoots()?.values?.map { it.toString() } ?: emptyList()
        try {
            SettingsRepository.setRootUris(allRoots)
        } catch (e: Exception) {
            // ignore
        }
        rootSetFlow.value = true
    }

    fun removeRoot(name: String) {
        saf?.removeRoot(name)
        val allRoots = saf?.getRoots()?.values?.map { it.toString() } ?: emptyList()
        try {
            SettingsRepository.setRootUris(allRoots)
        } catch (e: Exception) {
            // ignore
        }
        rootSetFlow.value = isRootSet()
    }

    fun getRootNames(): List<String> {
        return saf?.getRoots()?.keys?.toList() ?: emptyList()
    }

    fun isRootSet(): Boolean {
        return if (useFileStorage) {
            fileStorage?.getRootPath() != null
        } else {
            saf?.rootUri != null || (saf?.getRoots()?.isNotEmpty() == true)
        }
    }

    fun isCameraEnabled(): Boolean = cameraEnabled

    fun setCameraEnabled(enabled: Boolean) {
        cameraEnabled = enabled
        try { SettingsRepository.setCameraEnabled(enabled) } catch (_: Exception) { }
        if (!enabled) stopCameraStream()
    }

    private fun ensureCamera(): CameraStreamer {
        if (cameraStreamer == null) {
            val act = activityRef ?: throw IllegalStateException("No activity")
            cameraStreamer = CameraStreamer(act)
        }
        return cameraStreamer!!
    }

    fun startCameraStream(lens: String? = null, brightness: Int? = null, sharpness: Int? = null): Boolean {
        if (!cameraEnabled) return false
        return ensureCamera().start(lens, brightness, sharpness)
    }

    fun nextCameraFrame(timeoutMs: Long = 1000): ByteArray? {
        return cameraStreamer?.nextFrame(timeoutMs)
    }

    fun stopCameraStream() {
        try { cameraStreamer?.stop() } catch (_: Exception) { }
    }

    fun validate(username: String?, password: String?): Boolean {
        if (username == null || password == null) return false
        return AuthManager.validate(username, password)
    }

    fun issueTokenFor(user: String) { token = "token-$user" }

    fun safList(path: String, offset: Int = 0, limit: Int = Int.MAX_VALUE): List<FileItem> {
        val result = if (useFileStorage) {
            fileStorage?.listFiles(path, offset, limit) ?: emptyList()
        } else {
            saf?.listFiles(path, offset, limit) ?: emptyList()
        }
        android.util.Log.d("ServiceLocator", "safList($path, offset=$offset, limit=$limit) returned ${result.size} items")
        return result
    }

    fun streamFiles(path: String = ""): Sequence<FileItem> {
        return if (useFileStorage) {
            // FileStorageHelper doesn't have streamFiles yet, fallback to list
            (fileStorage?.listFiles(path) ?: emptyList()).asSequence()
        } else {
            saf?.streamFiles(path) ?: emptySequence()
        }
    }

    data class SearchFilters(
        val name: String? = null,
        val type: String? = null,
        val sizeMin: Long? = null,
        val sizeMax: Long? = null,
        val modifiedAfter: Long? = null,
        val modifiedBefore: Long? = null,
        val limit: Int = 200
    )

    fun search(path: String, filters: SearchFilters): List<FileItem> {
        val results = mutableListOf<FileItem>()
        val queue: ArrayDeque<Pair<String, FileItem>> = ArrayDeque()

        fun enqueueChildren(items: List<FileItem>) {
            for (item in items) {
                val fullPath = item.path ?: buildPath(path, item.name)
                val withPath = item.copy(path = fullPath)
                if (matches(withPath, filters)) {
                    results.add(withPath)
                    if (results.size >= filters.limit) return
                }
                if (withPath.type == "dir") {
                    queue.addLast(withPath.path!! to withPath)
                }
            }
        }

        // Seed with starting path
        val startItems = safList(path)
        enqueueChildren(startItems)
        while (queue.isNotEmpty() && results.size < filters.limit) {
            val (p, _) = queue.removeFirst()
            val children = safList(p.trim('/'))
            enqueueChildren(children)
        }
        return results.take(filters.limit)
    }

    private fun matches(item: FileItem, filters: SearchFilters): Boolean {
        filters.name?.let { q ->
            if (!item.name.contains(q, ignoreCase = true)) return false
        }
        filters.type?.let { t ->
            if (t.lowercase() == "file" && item.type != "file") return false
            if (t.lowercase() == "dir" && item.type != "dir") return false
        }
        filters.sizeMin?.let { if ((item.size ?: Long.MIN_VALUE) < it) return false }
        filters.sizeMax?.let { if ((item.size ?: Long.MAX_VALUE) > it) return false }
        filters.modifiedAfter?.let { if ((item.lastModified ?: Long.MIN_VALUE) < it) return false }
        filters.modifiedBefore?.let { if ((item.lastModified ?: Long.MAX_VALUE) > it) return false }
        return true
    }

    private fun buildPath(parent: String, name: String): String {
        val base = parent.trim('/')
        return if (base.isEmpty()) "/$name" else "/$base/$name"
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
            saf?.clearRoots()
        }
        try {
            SettingsRepository.setRootUris(emptyList())
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
