package com.stremer.ui

import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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

    val fallbackOwner = "saurabhsingh33"
    val fallbackRepo = "Stremer"

    var authEnabled by remember { mutableStateOf(SettingsRepository.isAuthEnabled()) }
    var username by remember { mutableStateOf(SettingsRepository.getUsername() ?: "") }
    var password by remember { mutableStateOf(SettingsRepository.getPassword() ?: "") }
    var saved by remember { mutableStateOf(false) }

    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
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

        Spacer(Modifier.height(24.dp))
        Text(
            text = "About",
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.onBackground
        )
        Spacer(Modifier.height(8.dp))
        val appVersion = remember {
            try {
                ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName
            } catch (_: Exception) {
                "1.1.0"
            }
        }
        Text(
            text = "Version: $appVersion",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onBackground
        )
        Spacer(Modifier.height(8.dp))
        val scope = rememberCoroutineScope()
        var checking by remember { mutableStateOf(false) }
        var lastCheckMsg by remember { mutableStateOf("") }
        Button(enabled = !checking, onClick = {
            checking = true
            lastCheckMsg = ""
            scope.launch(Dispatchers.IO) {
                try {
                    val owner = System.getenv("STREMER_REPO_OWNER") ?: fallbackOwner
                    val repo = System.getenv("STREMER_REPO_NAME") ?: fallbackRepo
                    if (owner == "OWNER" || repo == "REPO") {
                        checking = false
                        lastCheckMsg = "Set STREMER_REPO_OWNER/STREMER_REPO_NAME for updates"
                        return@launch
                    }
                    val url = java.net.URL("https://api.github.com/repos/$owner/$repo/releases/latest")
                    val conn = url.openConnection() as java.net.HttpURLConnection
                    val token = System.getenv("GITHUB_TOKEN")
                    if (!token.isNullOrEmpty()) {
                        conn.setRequestProperty("Authorization", "Bearer $token")
                    }
                    conn.connectTimeout = 10000
                    conn.readTimeout = 10000
                    val text = conn.inputStream.bufferedReader().use { it.readText() }
                    val json = org.json.JSONObject(text)
                    val tag = json.optString("tag_name", "")
                    val assets = json.optJSONArray("assets")
                    var apkUrl: String? = null
                    if (assets != null) {
                        for (i in 0 until assets.length()) {
                            val a = assets.getJSONObject(i)
                            if (a.optString("name", "").equals("Stremer-server.apk", ignoreCase = true)) {
                                apkUrl = a.optString("browser_download_url", null)
                                break
                            }
                        }
                    }
                    val current = try {
                        ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName
                    } catch (e: Exception) {
                        "0.0.0"
                    }
                    val newer = tag.removePrefix("v") != current
                    if (apkUrl != null && newer) {
                        with(android.os.Handler(android.os.Looper.getMainLooper())) {
                            post {
                                startApkDownload(ctx, apkUrl!!)
                            }
                        }
                        checking = false
                        lastCheckMsg = "Downloading update..."
                    } else {
                        checking = false
                        lastCheckMsg = "You're up to date."
                    }
                } catch (e: Exception) {
                    checking = false
                    lastCheckMsg = "Update check failed: ${e.message}"
                }
            }
        }) { Text(if (checking) "Checking..." else "Check for updates") }
        if (lastCheckMsg.isNotEmpty()) {
            Spacer(Modifier.height(6.dp))
            Text(text = lastCheckMsg, style = MaterialTheme.typography.bodySmall)
        }
    }
}

private fun startApkDownload(ctx: android.content.Context, url: String) {
    try {
        // Check permission to install unknown apps
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            val can = ctx.packageManager.canRequestPackageInstalls()
            if (!can) {
                try {
                    val i = android.content.Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, android.net.Uri.parse("package:" + ctx.packageName))
                    i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                    ctx.startActivity(i)
                } catch (_: Exception) {}
                android.widget.Toast.makeText(ctx, "Allow installing unknown apps, then try again.", android.widget.Toast.LENGTH_LONG).show()
                return
            }
        }
        val dm = ctx.getSystemService(android.content.Context.DOWNLOAD_SERVICE) as android.app.DownloadManager
        val req = android.app.DownloadManager.Request(android.net.Uri.parse(url))
            .setTitle("Stremer update")
            .setDescription("Downloading Stremer-server.apk")
            .setNotificationVisibility(android.app.DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setAllowedOverMetered(true)
            .setAllowedOverRoaming(true)
        req.setDestinationInExternalFilesDir(ctx, android.os.Environment.DIRECTORY_DOWNLOADS, "Stremer-server.apk")
        val id = dm.enqueue(req)
        // Receiver for completion
        val filter = android.content.IntentFilter(android.app.DownloadManager.ACTION_DOWNLOAD_COMPLETE)
        val receiver = object : android.content.BroadcastReceiver() {
            override fun onReceive(context: android.content.Context?, intent: android.content.Intent?) {
                val dId = intent?.getLongExtra(android.app.DownloadManager.EXTRA_DOWNLOAD_ID, -1L) ?: -1L
                if (dId == id) {
                    try { ctx.unregisterReceiver(this) } catch (_: Exception) {}
                    val file = java.io.File(ctx.getExternalFilesDir(android.os.Environment.DIRECTORY_DOWNLOADS), "Stremer-server.apk")
                    installApk(ctx, file)
                }
            }
        }
        ctx.registerReceiver(receiver, filter)
        android.widget.Toast.makeText(ctx, "Downloading update...", android.widget.Toast.LENGTH_SHORT).show()
    } catch (e: Exception) {
        android.widget.Toast.makeText(ctx, "Failed to download update: ${e.message}", android.widget.Toast.LENGTH_LONG).show()
    }
}

private fun installApk(ctx: android.content.Context, file: java.io.File) {
    try {
        val uri = androidx.core.content.FileProvider.getUriForFile(ctx, ctx.packageName + ".fileprovider", file)
        val intent = android.content.Intent(android.content.Intent.ACTION_VIEW)
        intent.setDataAndType(uri, "application/vnd.android.package-archive")
        intent.addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        intent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
        ctx.startActivity(intent)
    } catch (e: Exception) {
        android.widget.Toast.makeText(ctx, "Failed to start installer: ${e.message}", android.widget.Toast.LENGTH_LONG).show()
    }
}
