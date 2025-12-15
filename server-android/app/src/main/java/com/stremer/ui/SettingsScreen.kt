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
import com.stremer.di.ServiceLocator

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

        Spacer(Modifier.height(24.dp))
        Text(
            text = "Camera",
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.onBackground
        )
        Spacer(Modifier.height(12.dp))

        var camEnabled by remember { mutableStateOf(ServiceLocator.isCameraEnabled()) }
        Row {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Enable camera streaming",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onBackground
                )
                Text(
                    text = "Allow clients to view live camera stream (secure, requires auth)",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.75f)
                )
            }
            Switch(
                checked = camEnabled,
                onCheckedChange = {
                    camEnabled = it
                    ServiceLocator.setCameraEnabled(it)
                    if (it) {
                        // Request camera permission when enabling
                        try {
                            val hasCam = ctx.checkSelfPermission(android.Manifest.permission.CAMERA) == android.content.pm.PackageManager.PERMISSION_GRANTED
                            if (!hasCam && ctx is android.app.Activity) {
                                ctx.requestPermissions(arrayOf(android.Manifest.permission.CAMERA), 1001)
                            }
                        } catch (_: Exception) { }
                    }
                },
                colors = SwitchDefaults.colors()
            )
        }

        Spacer(Modifier.height(24.dp))
        Button(onClick = {
            try {
                ServiceLocator.clearRoot()
                android.widget.Toast.makeText(ctx, "Storage cleared", android.widget.Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                android.util.Log.w("SettingsScreen", "Failed to clear storage: ${e.message}")
                android.widget.Toast.makeText(ctx, "Failed to clear storage", android.widget.Toast.LENGTH_SHORT).show()
            }
        }) {
            Text("Clear Storage")
        }
    }
}
