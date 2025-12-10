package com.stremer.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.stremer.MainActivity
import com.stremer.api.Server

class StremerServerService : android.app.Service() {
    private val serviceJob = Job()
    private val serviceScope = CoroutineScope(Dispatchers.Default + serviceJob)
    override fun onBind(intent: Intent?) = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        return when (action) {
            ACTION_STOP -> {
                stopServer()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                // stop any background coroutines
                serviceScope.cancel()
                START_NOT_STICKY
            }
            else -> {
                // Default: start server if not running
                if (!Server.isRunning()) {
                    Server.start(8080)
                }
                startForeground(NOTIF_ID, buildNotification(0))

                // Collect client count updates and refresh notification
                serviceScope.launch {
                    try {
                        Server.clientCount.collect { count ->
                            try {
                                val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
                                nm.notify(NOTIF_ID, buildNotification(count))
                            } catch (e: Exception) {
                                android.util.Log.w("StremerServerService", "Failed to update notification: ${e.message}")
                            }
                        }
                    } catch (e: Exception) {
                        android.util.Log.w("StremerServerService", "Client count collector failed: ${e.message}")
                    }
                }
                START_STICKY
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        stopServer()
        serviceScope.cancel()
    }

    private fun stopServer() {
        if (Server.isRunning()) Server.stop()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Stremer Server",
                NotificationManager.IMPORTANCE_LOW
            )
            channel.description = "LAN server status"
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(clientCount: Int): Notification {
        val openIntent = Intent(this, MainActivity::class.java)
        val openPending = PendingIntent.getActivity(
            this, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 23) PendingIntent.FLAG_IMMUTABLE else 0)
        )
        val stopIntent = Intent(this, StremerServerService::class.java).setAction(ACTION_STOP)
        val stopPending = PendingIntent.getService(
            this, 1, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 23) PendingIntent.FLAG_IMMUTABLE else 0)
        )
        val baseText = if (Server.isRunning()) "Server running on port ${Server.getPort()}" else "Server starting…"
        val text = if (Server.isRunning()) {
            if (clientCount > 0) "$baseText — $clientCount client${if (clientCount == 1) "" else "s"} connected" else baseText
        } else baseText
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("Stremer")
            .setContentText(text)
            .setContentIntent(openPending)
            .setOngoing(true)
            .addAction(0, "Stop", stopPending)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "stremer_server"
        private const val NOTIF_ID = 1001
        const val ACTION_STOP = "com.stremer.action.STOP"

        fun start(context: Context) {
            val i = Intent(context, StremerServerService::class.java)
            ContextCompat.startForegroundService(context, i)
        }

        fun stop(context: Context) {
            val i = Intent(context, StremerServerService::class.java).setAction(ACTION_STOP)
            ContextCompat.startForegroundService(context, i)
        }
    }
}
