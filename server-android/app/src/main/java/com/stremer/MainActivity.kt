@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
package com.stremer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.background
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.clip
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.animation.animateColorAsState
import com.stremer.ui.theme.StremerTheme
import com.stremer.ui.MainScreen
import com.stremer.ui.SettingsScreen
import com.stremer.api.Server

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            StremerTheme {
                var inSettings by remember { mutableStateOf(false) }
                var serverRunning by remember { mutableStateOf(Server.isRunning()) }

                // Poll Server.isRunning() every 500ms to keep dot color in sync
                LaunchedEffect(Unit) {
                    while (true) {
                        kotlinx.coroutines.delay(500)
                        serverRunning = Server.isRunning()
                    }
                }

                Scaffold(
                    topBar = {
                        TopAppBar(
                                    title = {
                                        if (inSettings) {
                                            Text("Settings")
                                        } else {
                                            val dotColor by animateColorAsState(targetValue = if (serverRunning) androidx.compose.ui.graphics.Color(0xFF4CAF50) else androidx.compose.ui.graphics.Color(0xFFFF5252))
                                            Row(verticalAlignment = Alignment.CenterVertically) {
                                                Box(modifier = Modifier
                                                    .size(12.dp)
                                                    .clip(CircleShape)
                                                    .background(dotColor))
                                                Spacer(modifier = Modifier.width(8.dp))
                                                Text("Server", style = MaterialTheme.typography.titleSmall)
                                            }
                                        }
                                    },
                            navigationIcon = {
                                if (inSettings) {
                                    IconButton(onClick = { inSettings = false }) {
                                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                                    }
                                }
                            },
                            actions = {
                                if (!inSettings) {
                                    IconButton(onClick = { inSettings = true }) {
                                        Icon(Icons.Filled.Settings, contentDescription = "Settings")
                                    }
                                }
                            }
                        )
                    }
                ) { inner ->
                    Surface(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(inner),
                        color = MaterialTheme.colorScheme.background
                    ) {
                        if (inSettings) SettingsScreen() else MainScreen()
                    }
                }
            }
        }
    }
}
