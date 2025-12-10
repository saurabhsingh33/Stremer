package com.stremer.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
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

    // Observe actual storage state (survives navigation) via ServiceLocator flow
    val storageSelected by ServiceLocator.rootSetFlow.collectAsState(initial = ServiceLocator.isRootSet())

    val storagePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            ServiceLocator.setRoot(uri)
        }
    }

    Column(modifier = Modifier
        .fillMaxSize()
        .padding(16.dp)) {
        Text(
            text = "Stremer Android Server",
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.onBackground
        )
        Spacer(modifier = Modifier.height(16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(
                enabled = serverRunning || storageSelected,
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
            Button(onClick = { storagePicker.launch(null) }) {
                Text("Select Storage")
            }
        }
        Spacer(modifier = Modifier.height(16.dp))
        if (serverRunning || Server.isRunning()) {
            Text(
                text = "Server is running on LAN",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.primary
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "Connect to: ${Server.getServerUrl()}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onBackground
            )
        } else {
            Text(
                text = "Server is stopped",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onBackground
            )
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = if (storageSelected) "✓ Storage selected" else "⚠ No storage selected",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onBackground
        )
    }
}
