package com.stremer.settings

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

object SettingsRepository {
    private const val PREFS_NAME = "stremer_settings"
    private const val KEY_AUTH_ENABLED = "auth_enabled"
    private const val KEY_USERNAME = "auth_username"
    private const val KEY_PASSWORD = "auth_password"
    private const val KEY_ROOT_URI = "root_uri"
    private const val KEY_ROOT_URIS = "root_uris"
    private const val KEY_CAMERA_ENABLED = "camera_enabled"

    @Volatile
    private var prefs: android.content.SharedPreferences? = null

    fun init(context: Context) {
        if (prefs != null) return
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        prefs = EncryptedSharedPreferences.create(
            context,
            PREFS_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    private fun requirePrefs(): android.content.SharedPreferences {
        return prefs ?: throw IllegalStateException("SettingsRepository not initialized")
    }

    fun isAuthEnabled(): Boolean = requirePrefs().getBoolean(KEY_AUTH_ENABLED, true)

    fun setAuthEnabled(enabled: Boolean) {
        requirePrefs().edit().putBoolean(KEY_AUTH_ENABLED, enabled).apply()
    }

    fun getUsername(): String? = requirePrefs().getString(KEY_USERNAME, null)

    fun getPassword(): String? = requirePrefs().getString(KEY_PASSWORD, null)

    fun setCredentials(username: String?, password: String?) {
        requirePrefs().edit()
            .putString(KEY_USERNAME, username?.trim()?.ifEmpty { null })
            .putString(KEY_PASSWORD, password)
            .apply()
    }

    fun getRootUri(): String? = requirePrefs().getString(KEY_ROOT_URI, null)

    fun setRootUri(uri: String?) {
        if (uri == null) {
            requirePrefs().edit().remove(KEY_ROOT_URI).apply()
        } else {
            requirePrefs().edit().putString(KEY_ROOT_URI, uri).apply()
        }
    }

    fun getRootUris(): List<String> {
        val json = requirePrefs().getString(KEY_ROOT_URIS, null)
        if (json.isNullOrEmpty()) {
            // Migrate from single root if available
            val single = getRootUri()
            return if (single != null) listOf(single) else emptyList()
        }
        return try {
            org.json.JSONArray(json).let { array ->
                (0 until array.length()).mapNotNull { array.optString(it) }
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    fun setRootUris(uris: List<String>) {
        val json = org.json.JSONArray(uris).toString()
        requirePrefs().edit().putString(KEY_ROOT_URIS, json).apply()
        // Also update single root for backward compatibility
        if (uris.isNotEmpty()) {
            setRootUri(uris.first())
        } else {
            setRootUri(null)
        }
    }

    fun isCameraEnabled(): Boolean = requirePrefs().getBoolean(KEY_CAMERA_ENABLED, false)

    fun setCameraEnabled(enabled: Boolean) {
        requirePrefs().edit().putBoolean(KEY_CAMERA_ENABLED, enabled).apply()
    }
}
