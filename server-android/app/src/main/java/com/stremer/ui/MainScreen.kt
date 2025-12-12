package com.stremer.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.animation.Crossfade
import androidx.compose.animation.animateColorAsState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.stremer.api.Server
import com.stremer.di.ServiceLocator
import com.stremer.service.StremerServerService

@Composable
fun MainScreen() {
    var serverRunning by remember { mutableStateOf(Server.isRunning()) }
    val context = LocalContext.current

    LaunchedEffect(Unit) {
        ServiceLocator.init(context as android.app.Activity)
    }

    // Poll Server.isRunning() every 500ms to keep UI in sync with actual engine state
    LaunchedEffect(Unit) {
        while (true) {
            kotlinx.coroutines.delay(500)
            serverRunning = Server.isRunning()
        }
    }

    // Observe actual storage state (survives navigation) via ServiceLocator flow
    val storageSelected by ServiceLocator.rootSetFlow.collectAsState(initial = ServiceLocator.isRootSet())

    val storagePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            try {
                ServiceLocator.setRoot(uri)
                android.widget.Toast.makeText(context, "Storage selected", android.widget.Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                android.widget.Toast.makeText(context, "Failed to select storage: ${e.message}", android.widget.Toast.LENGTH_SHORT).show()
            }
        }
    }

    // For requesting MANAGE_ALL_FILES permission
    val permLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            android.widget.Toast.makeText(context, "Permission granted! Now select your storage.", android.widget.Toast.LENGTH_SHORT).show()
        } else {
            android.widget.Toast.makeText(context, "Permission denied. Opening Settings...", android.widget.Toast.LENGTH_SHORT).show()
            // Open app settings so user can manually grant the permission
            try {
                val intent = android.content.Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                intent.data = android.net.Uri.fromParts("package", context.packageName, null)
                context.startActivity(intent)
            } catch (e: Exception) {
                android.widget.Toast.makeText(context, "Please grant MANAGE_ALL_FILES in Settings > Apps", android.widget.Toast.LENGTH_LONG).show()
            }
        }
    }

    // Main content column
    Column(modifier = Modifier
        .fillMaxSize()
        .padding(16.dp)) {
        // Compact header card with subtle entrance animation
        androidx.compose.animation.Crossfade(targetState = true) { _ ->
            Card(modifier = Modifier.fillMaxWidth(), elevation = CardDefaults.cardElevation(defaultElevation = 6.dp)) {
                Row(modifier = Modifier
                    .fillMaxWidth()
                    .padding(12.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    androidx.compose.material3.Icon(
                        imageVector = Icons.Filled.Settings,
                        contentDescription = "Server",
                        tint = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Column {
                        Text(text = "Stremer", style = MaterialTheme.typography.titleLarge)
                        Text(text = "Android Server — manage & share files on LAN", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.8f))
                    }
                }
            }
        }
        Spacer(modifier = Modifier.height(16.dp))
        // Main buttons - Start/Stop and Select Folder side by side
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
            Button(
                enabled = storageSelected,
                modifier = Modifier.weight(1f),
                onClick = {
                    if (serverRunning) {
                        StremerServerService.stop(context)
                        serverRunning = false
                    } else {
                        if (!ServiceLocator.isRootSet()) {
                            android.widget.Toast.makeText(
                                context,
                                "Please select storage first",
                                android.widget.Toast.LENGTH_SHORT
                            ).show()
                        } else {
                            StremerServerService.start(context)
                            serverRunning = true
                        }
                    }
                }
            ) {
                Text(if (serverRunning) "Stop Server" else "Start Server")
            }
            Button(
                modifier = Modifier.weight(1f),
                onClick = { storagePicker.launch(null) }
            ) {
                Text("Select Folder")
            }
        }
        // Full Access button on its own row if API 30+ and permission not yet granted
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
            val hasPermission = try {
                context.checkSelfPermission("android.permission.MANAGE_ALL_FILES") ==
                    android.content.pm.PackageManager.PERMISSION_GRANTED
            } catch (e: Exception) {
                false
            }
            if (!hasPermission) {
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedButton(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = {
                        // MANAGE_ALL_FILES can't be requested at runtime; open Settings directly
                        try {
                            val intent = android.content.Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                            intent.data = android.net.Uri.fromParts("package", context.packageName, null)
                            context.startActivity(intent)
                        } catch (e: Exception) {
                            android.widget.Toast.makeText(context, "Please grant MANAGE_ALL_FILES in Settings > Apps > Stremer > Permissions", android.widget.Toast.LENGTH_LONG).show()
                        }
                    }
                ) {
                    Text("🔓 Grant Full Device Access")
                }
            }
        }
        Spacer(modifier = Modifier.height(16.dp))
        // Status card with animated color when server running
        // Use the serverRunning state variable so UI recomposes when polling updates it
        val bgColor by animateColorAsState(targetValue = if (serverRunning) MaterialTheme.colorScheme.primary.copy(alpha = 0.12f) else MaterialTheme.colorScheme.surface)
        Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = bgColor)) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text(text = if (serverRunning) "Server is running on LAN" else "Server is stopped", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onBackground)
                Spacer(modifier = Modifier.height(6.dp))
                if (serverRunning) {
                    Text(text = "Connect to: ${Server.getServerUrl()}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.8f))
                } else {
                    Text(text = "Start the server to obtain the LAN address", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.6f))
                }
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        Column {
            Text(
                text = if (storageSelected) "✓ Storage selected" else "⚠ No storage selected",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onBackground
            )

            // Show a short friendly storage name when available (recomputes when storageSelected changes)
            val storageDisplay = remember(storageSelected) { ServiceLocator.getRootDisplayName() }
            if (!storageDisplay.isNullOrEmpty()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = "Storage: $storageDisplay",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onBackground
                )
            }

            // Show helper text when no storage selected
            if (!storageSelected) {
                Spacer(modifier = Modifier.height(12.dp))
                Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                    Column(modifier = Modifier.padding(10.dp)) {
                        Text(text = "📁 How to select storage:", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onBackground)
                        Spacer(modifier = Modifier.height(6.dp))
                        val buildVersion = android.os.Build.VERSION.SDK_INT
                        val fullAccessText = if (buildVersion >= android.os.Build.VERSION_CODES.R) {
                            "• Tap 'Full Access' button to grant permission for complete device access\n• Then select any folder or use the file system directly\n"
                        } else {
                            ""
                        }
                        val folderText = "• Alternatively, tap 'Select Folder' and choose Documents, DCIM, or other folders\n• You can create a new folder to store files for sharing"
                        Text(text = fullAccessText + folderText, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.8f))
                    }
                }
            }
        }
    }
}
