package com.stremer.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.stremer.settings.SettingsRepository

@Composable
fun SettingsScreen() {
    val ctx = LocalContext.current
    LaunchedEffect(Unit) {
        try { SettingsRepository.init(ctx) } catch (_: Exception) {}
    }

    var authEnabled by remember { mutableStateOf(SettingsRepository.isAuthEnabled()) }
    var username by remember { mutableStateOf(SettingsRepository.getUsername() ?: "") }
    var password by remember { mutableStateOf(SettingsRepository.getPassword() ?: "") }
    var saved by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.Top
    ) {
        Text(
            text = "Security",
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.onBackground
        )
        Spacer(Modifier.height(12.dp))

        Row {
            Text(
                text = "Require authentication",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onBackground,
                modifier = Modifier.weight(1f)
            )
            Switch(
                checked = authEnabled,
                onCheckedChange = { checked -> authEnabled = checked; saved = false },
                colors = SwitchDefaults.colors()
            )
        }

        if (authEnabled) {
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = username,
                onValueChange = { username = it; saved = false },
                label = { Text("Username") },
                singleLine = true
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = password,
                onValueChange = { password = it; saved = false },
                label = { Text("Password") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation()
            )
        }

        Spacer(Modifier.height(16.dp))
        Button(onClick = {
            SettingsRepository.setAuthEnabled(authEnabled)
            if (authEnabled) {
                SettingsRepository.setCredentials(username.trim(), password)
            } else {
                // Clear credentials when disabling auth (optional, but safer)
                SettingsRepository.setCredentials(null, null)
            }
            saved = true
        }) {
            Text(if (saved) "Saved" else "Save")
        }

        Spacer(Modifier.height(8.dp))
        Text(
            text = if (authEnabled) "Windows client must login with these credentials." else "Authentication disabled: Windows client can connect without login.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onBackground
        )
    }
}
