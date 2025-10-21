package com.stremer.ui

import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.foundation.layout.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.stremer.api.Server
import com.stremer.di.ServiceLocator
import androidx.compose.ui.platform.LocalContext
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts

@Composable
fun MainScreen() {
    var serverRunning by remember { mutableStateOf(false) }
    var storageSelected by remember { mutableStateOf(false) }
    val context = LocalContext.current
    LaunchedEffect(Unit) {
        ServiceLocator.init(context as android.app.Activity)
    }
    val storagePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            ServiceLocator.setRoot(uri)
            storageSelected = true
        }
    }
    Column(modifier = Modifier.padding(16.dp)) {
        Text(text = "Stremer Android Server", style = MaterialTheme.typography.headlineMedium)
        Spacer(modifier = Modifier.height(16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = {
                serverRunning = !serverRunning
                if (serverRunning) Server.start(8080) else Server.stop()
            }) {
                Text(if (serverRunning) "Stop Server" else "Start Server")
            }
            Button(onClick = { storagePicker.launch(null) }) {
                Text("Select Storage")
            }
        }
        Spacer(modifier = Modifier.height(16.dp))
        Text(text = if (serverRunning) "Server is running on LAN" else "Server is stopped")
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = if (storageSelected) "✓ Storage selected" else "⚠ No storage selected",
            style = MaterialTheme.typography.bodyMedium
        )
    }
}
