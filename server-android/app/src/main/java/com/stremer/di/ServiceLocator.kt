package com.stremer.di

import android.app.Activity
import com.stremer.auth.AuthManager
import com.stremer.saf.SafHelper
import com.stremer.settings.SettingsRepository
import android.net.Uri
import com.stremer.files.FileItem

object ServiceLocator {
    private var saf: SafHelper? = null
    var token: String? = null

    fun init(activity: Activity) {
        saf = SafHelper(activity)
        SettingsRepository.init(activity)
    }

    fun setRoot(uri: Uri) {
        saf?.setRoot(uri)
        android.util.Log.d("ServiceLocator", "Storage root set to: $uri")
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
}
