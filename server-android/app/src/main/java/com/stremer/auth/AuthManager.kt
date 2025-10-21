package com.stremer.auth

import com.stremer.settings.SettingsRepository

object AuthManager {
    fun isEnabled(): Boolean = SettingsRepository.isAuthEnabled()

    fun validate(username: String, password: String): Boolean {
        if (!isEnabled()) return true
        val u = SettingsRepository.getUsername()
        val p = SettingsRepository.getPassword()
        return username == u && password == p
    }
}
