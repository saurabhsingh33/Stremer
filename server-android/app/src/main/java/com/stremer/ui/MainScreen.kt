package com.stremer.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
import com.stremer.settings.SettingsRepository

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

    // Track root folder names for multi-folder display
    var rootFolders by remember { mutableStateOf(ServiceLocator.getRootNames()) }

    // Observe recent client logins (username + IP)
    val clients by Server.clients.collectAsState(initial = emptyList())

    // Update root folders list when storage changes
    LaunchedEffect(storageSelected) {
        rootFolders = ServiceLocator.getRootNames()
    }

    val storagePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            try {
                ServiceLocator.setRoot(uri)
                rootFolders = ServiceLocator.getRootNames()
                android.widget.Toast.makeText(context, "Folder added", android.widget.Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                android.widget.Toast.makeText(context, "Failed to add folder: ${e.message}", android.widget.Toast.LENGTH_SHORT).show()
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

    val scrollState = rememberScrollState()

    // Main content column
    Column(modifier = Modifier
        .fillMaxSize()
        .verticalScroll(scrollState)
        .padding(16.dp)) {
        var showNoAuthWarning by remember { mutableStateOf(false) }
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
        // Main buttons - Start/Stop and Add Folder side by side
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
                                "Please add at least one folder",
                                android.widget.Toast.LENGTH_SHORT
                            ).show()
                        } else {
                            // Warn if authentication is disabled
                            if (!SettingsRepository.isAuthEnabled()) {
                                showNoAuthWarning = true
                            } else {
                                StremerServerService.start(context)
                                serverRunning = true
                            }
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
                Text("Add Folder")
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

        // Security warning dialog when starting server without authentication
        if (showNoAuthWarning) {
            AlertDialog(
                onDismissRequest = { showNoAuthWarning = false },
                title = { Text("Security Warning") },
                text = {
                    Text("Authentication is disabled. Anyone on your network may access your shared files.\n\nRecommended: Open Settings and enable 'Require authentication', then set a username and password.")
                },
                confirmButton = {
                    TextButton(onClick = {
                        showNoAuthWarning = false
                        StremerServerService.start(context)
                        serverRunning = true
                    }) { Text("Start anyway") }
                },
                dismissButton = {
                    TextButton(onClick = { showNoAuthWarning = false }) { Text("Cancel") }
                }
            )
        }
        Spacer(modifier = Modifier.height(8.dp))
        Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f))) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text(text = "Recent logins", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onBackground)
                Spacer(modifier = Modifier.height(6.dp))
                if (clients.isEmpty()) {
                    Text(
                        text = "No clients have logged in yet",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.75f)
                    )
                } else {
                    clients.take(5).forEach { client ->
                        val timeStr = remember(client.lastSeen) {
                            android.text.format.DateFormat.format("HH:mm:ss", java.util.Date(client.lastSeen)).toString()
                        }
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(text = "👤 ${client.username}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onBackground)
                                Text(text = "IP: ${client.ip}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.8f))
                            }
                            Text(text = timeStr, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.8f))
                        }
                    }
                    if (clients.size > 5) {
                        Text(
                            text = "+${clients.size - 5} more",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.7f)
                        )
                    }
                }
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        Column {
            Text(
                text = if (storageSelected) {
                    if (rootFolders.size > 1) "✓ ${rootFolders.size} folders shared"
                    else "✓ Storage selected"
                } else "⚠ No folders shared",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onBackground
            )

            // Show list of shared folders with remove buttons
            if (rootFolders.isNotEmpty()) {
                Spacer(modifier = Modifier.height(8.dp))
                Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))) {
                    Column(modifier = Modifier.padding(10.dp)) {
                        Text(text = "Shared Folders:", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onBackground)
                        Spacer(modifier = Modifier.height(6.dp))
                        rootFolders.forEach { folderName ->
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
                            ) {
                                Text(
                                    text = "📁 $folderName",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onBackground,
                                    modifier = Modifier.weight(1f)
                                )
                                TextButton(
                                    onClick = {
                                        if (!serverRunning) {
                                            ServiceLocator.removeRoot(folderName)
                                            rootFolders = ServiceLocator.getRootNames()
                                            android.widget.Toast.makeText(context, "Removed $folderName", android.widget.Toast.LENGTH_SHORT).show()
                                        } else {
                                            android.widget.Toast.makeText(context, "Stop server first", android.widget.Toast.LENGTH_SHORT).show()
                                        }
                                    },
                                    enabled = !serverRunning
                                ) {
                                    Text("Remove", style = MaterialTheme.typography.labelSmall)
                                }
                            }
                        }
                    }
                }
            }

            // Show helper text when no storage selected
            if (!storageSelected) {
                Spacer(modifier = Modifier.height(12.dp))
                Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                    Column(modifier = Modifier.padding(10.dp)) {
                        Text(text = "📁 How to add folders:", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onBackground)
                        Spacer(modifier = Modifier.height(6.dp))
                        val buildVersion = android.os.Build.VERSION.SDK_INT
                        val fullAccessText = if (buildVersion >= android.os.Build.VERSION_CODES.R) {
                            "• Tap 'Full Access' button to grant permission for complete device access\n• Then add any folder or use the file system directly\n"
                        } else {
                            ""
                        }
                        val folderText = "• Alternatively, tap 'Add Folder' and choose Documents, DCIM, or other folders\n• You can add multiple folders to share different locations\n• Each folder appears as a separate directory in the client"
                        Text(text = fullAccessText + folderText, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.8f))
                    }
                }
            }
        }

    }
}
