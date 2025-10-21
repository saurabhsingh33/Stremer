package com.stremer.settings

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

object SettingsRepository {
    private const val PREFS_NAME = "stremer_settings"
    private const val KEY_AUTH_ENABLED = "auth_enabled"
    private const val KEY_USERNAME = "auth_username"
    private const val KEY_PASSWORD = "auth_password"

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
}
