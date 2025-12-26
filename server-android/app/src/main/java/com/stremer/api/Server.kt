package com.stremer.api

import com.stremer.di.ServiceLocator
import com.stremer.api.FilesResponse
import com.stremer.files.FileItem
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.*
import io.ktor.server.auth.*
import io.ktor.server.cio.*
import io.ktor.server.engine.*
import io.ktor.server.response.*
import io.ktor.server.request.*
import io.ktor.server.routing.*
import io.ktor.serialization.kotlinx.json.*
import io.ktor.server.plugins.contentnegotiation.*
import io.ktor.utils.io.*
import io.ktor.utils.io.core.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

object Server {
    private var engine: ApplicationEngine? = null
    private var currentPort: Int = 8080
    // Expose active client count as a StateFlow so UI/services can observe it in real time
    private val _clientCount = MutableStateFlow(0)
    val clientCount: StateFlow<Int> = _clientCount
    data class ClientInfo(val username: String, val ip: String, val lastSeen: Long)
    private val _clients = MutableStateFlow<List<ClientInfo>>(emptyList())
    val clients: StateFlow<List<ClientInfo>> = _clients
    private val clientLock = Any()

    private fun recordClient(username: String?, ip: String) {
        val name = (username ?: "unknown").ifBlank { "unknown" }
        val now = System.currentTimeMillis()
        synchronized(clientLock) {
            val mutable = _clients.value.toMutableList()
            val idx = mutable.indexOfFirst { it.ip == ip || it.username == name }
            val info = ClientInfo(name, ip, now)
            if (idx >= 0) {
                mutable[idx] = info
            } else {
                mutable.add(info)
            }
            _clients.value = mutable
        }
    }

    fun start(port: Int = 8080) {
        currentPort = port
        engine = embeddedServer(CIO, port = port) {
            // Intercept calls to maintain an active client count
            intercept(ApplicationCallPipeline.Monitoring) {
                try {
                    // Increment
                    _clientCount.value = _clientCount.value + 1
                    proceed()
                } finally {
                    // Decrement when call finished
                    try {
                        _clientCount.value = (_clientCount.value - 1).coerceAtLeast(0)
                    } catch (_: Exception) { }
                }
            }
            install(ContentNegotiation) {
                json()
            }

            install(Authentication) {
                bearer("auth-bearer") {
                    authenticate { tokenCredential ->
                        // If auth disabled , allow any request
                        if (!com.stremer.auth.AuthManager.isEnabled()) {
                            UserIdPrincipal("anon")
                        } else if (tokenCredential.token == ServiceLocator.token) {
                            UserIdPrincipal("user")
                        } else null
                    }
                }
            }
            routing {
                // Lightweight unauthenticated ping for LAN discovery
                get("/ping") {
                    call.respond(mapOf("server" to "stremer", "status" to "ok"))
                }
                // login issues token (stored in ServiceLocator)
                post("/auth/login") {
                    try {
                        // Accept both JSON and x-www-form-urlencoded bodies
                        val contentType = call.request.headers[io.ktor.http.HttpHeaders.ContentType]?.lowercase()
                        var user: String? = null
                        var pass: String? = null

                        if (contentType != null && contentType.contains("application/json")) {
                            val json = runCatching { call.receive<Map<String, String>>() }.getOrNull()
                            user = json?.get("username")
                            pass = json?.get("password")
                        }
                        if (user == null || pass == null) {
                            val params = runCatching { call.receiveParameters() }.getOrNull()
                            user = user ?: params?.get("username")
                            pass = pass ?: params?.get("password")
                        }

                        if (user.isNullOrBlank() || pass.isNullOrBlank()) {
                            return@post call.respond(
                                HttpStatusCode.BadRequest,
                                mapOf("error" to "Missing username or password")
                            )
                        }

                        // If auth disabled, issue token regardless (or a fixed token)
                        if (!com.stremer.auth.AuthManager.isEnabled() || ServiceLocator.validate(user, pass)) {
                            ServiceLocator.issueTokenFor(user ?: "user")
                            // Track client login with username and IP
                            val ip = try {
                                call.request.headers[io.ktor.http.HttpHeaders.XForwardedFor]
                                    ?.split(',')?.firstOrNull()?.trim()
                                    ?: call.request.local.remoteHost
                            } catch (_: Exception) { "unknown" }
                            recordClient(user, ip)
                            call.respond(mapOf("token" to ServiceLocator.token))
                        } else {
                            call.respondText("Invalid credentials", status = HttpStatusCode.Unauthorized)
                        }
                    } catch (e: Exception) {
                        android.util.Log.e("Server", "Login error: ${e.message}", e)
                        call.respond(HttpStatusCode.InternalServerError, mapOf("error" to ("Login failed: ${e.message}")))
                    }
                }

                authenticate("auth-bearer") {
                    // Advanced search with filters
                    get("/search") {
                        try {
                            val path = call.request.queryParameters["path"] ?: "/"
                            val q = call.request.queryParameters["q"]
                            val type = call.request.queryParameters["type"]
                            val sizeMin = call.request.queryParameters["sizeMin"]?.toLongOrNull()
                            val sizeMax = call.request.queryParameters["sizeMax"]?.toLongOrNull()
                            val modifiedAfter = call.request.queryParameters["modifiedAfter"]?.toLongOrNull()
                            val modifiedBefore = call.request.queryParameters["modifiedBefore"]?.toLongOrNull()
                            val limit = call.request.queryParameters["limit"]?.toIntOrNull()?.coerceIn(1, 500) ?: 200

                            val filters = com.stremer.di.ServiceLocator.SearchFilters(
                                name = q,
                                type = type,
                                sizeMin = sizeMin,
                                sizeMax = sizeMax,
                                modifiedAfter = modifiedAfter,
                                modifiedBefore = modifiedBefore,
                                limit = limit
                            )
                            val results = com.stremer.di.ServiceLocator.search(path.trim('/'), filters)
                            call.respond(mapOf("items" to results))
                        } catch (e: Exception) {
                            android.util.Log.e("Server", "Search failed: ${e.message}")
                            call.respondText("Search failed: ${e.message}", status = HttpStatusCode.InternalServerError)
                        }
                    }

                    // Camera snapshot (authenticated) - legacy
                    get("/camera/snapshot") {
                        if (!com.stremer.di.ServiceLocator.isCameraEnabled()) {
                            return@get call.respondText("Camera disabled", status = HttpStatusCode.Forbidden)
                        }
                        val lens = call.request.queryParameters["lens"]
                        val brightness = call.request.queryParameters["brightness"]?.toIntOrNull()
                        val sharpness = call.request.queryParameters["sharpness"]?.toIntOrNull()
                        if (!com.stremer.di.ServiceLocator.startCameraStream(lens, brightness, sharpness)) {
                            return@get call.respondText("No frame", status = HttpStatusCode.ServiceUnavailable)
                        }
                        val bytes = com.stremer.di.ServiceLocator.nextCameraFrame(1500)
                        if (bytes == null) {
                            return@get call.respondText("No frame", status = HttpStatusCode.ServiceUnavailable)
                        }
                        call.respondBytes(bytes, contentType = ContentType.Image.JPEG)
                    }

                    // MJPEG streaming endpoint
                    get("/camera/stream") {
                        if (!com.stremer.di.ServiceLocator.isCameraEnabled()) {
                            return@get call.respondText("Camera disabled", status = HttpStatusCode.Forbidden)
                        }
                        val lens = call.request.queryParameters["lens"]
                        val brightness = call.request.queryParameters["brightness"]?.toIntOrNull()
                        val sharpness = call.request.queryParameters["sharpness"]?.toIntOrNull()

                        val ok = com.stremer.di.ServiceLocator.startCameraStream(lens, brightness, sharpness)
                        if (!ok) return@get call.respondText("Camera error", status = HttpStatusCode.ServiceUnavailable)

                        val boundary = "frame"
                        call.respondBytesWriter(ContentType.parse("multipart/x-mixed-replace; boundary=$boundary")) {
                            try {
                                var consecutiveNulls = 0
                                while (true) {
                                    val frame = com.stremer.di.ServiceLocator.nextCameraFrame(1500)
                                    if (frame == null) {
                                        consecutiveNulls++
                                        if (consecutiveNulls > 3) break
                                        continue
                                    }
                                    consecutiveNulls = 0
                                    val header = "--$boundary\r\nContent-Type: image/jpeg\r\nContent-Length: ${frame.size}\r\n\r\n"
                                    writeFully(header.encodeToByteArray())
                                    writeFully(frame)
                                    writeFully("\r\n".encodeToByteArray())
                                    flush()
                                }
                            } catch (e: Throwable) {
                                android.util.Log.d("Server", "Camera stream ended: ${e.message}")
                            } finally {
                                try { com.stremer.di.ServiceLocator.stopCameraStream() } catch (_: Exception) { }
                            }
                        }
                    }
                    // Upload/overwrite file bytes with streaming support
                    put("/file") {
                        try {
                            val path = call.request.queryParameters["path"]
                                ?: return@put call.respondText("Missing path", status = HttpStatusCode.BadRequest)

                            // Read body in chunks for large file support
                            val channel = call.receiveChannel()
                            val contentTypeHeader = call.request.headers[io.ktor.http.HttpHeaders.ContentType]
                            val contentLength = call.request.headers[io.ktor.http.HttpHeaders.ContentLength]

                            android.util.Log.i("Server", "Starting upload for path: $path, Content-Length: $contentLength")

                            val ok = com.stremer.di.ServiceLocator.writeStream(
                                path.trim('/'),
                                channel,
                                contentTypeHeader
                            )

                            if (ok) {
                                android.util.Log.i("Server", "Upload completed successfully for: $path")
                                call.respond(mapOf("status" to "saved"))
                            } else {
                                android.util.Log.e("Server", "Upload failed for: $path")
                                call.respondText("Write failed", status = HttpStatusCode.InternalServerError)
                            }
                        } catch (e: NumberFormatException) {
                            android.util.Log.e("Server", "Number format error in upload: ${e.message}", e)
                            call.respondText("Error writing file: Number format error - ${e.message}", status = HttpStatusCode.InternalServerError)
                        } catch (e: Exception) {
                            android.util.Log.e("Server", "Write /file error: ${e.message}", e)
                            e.printStackTrace()
                            call.respondText("Error writing file: ${e.message}", status = HttpStatusCode.InternalServerError)
                        }
                    }
                    get("/files") {
                        try {
                            val path = call.request.queryParameters["path"] ?: "/"
                            val limit = call.request.queryParameters["limit"]?.toIntOrNull()
                            val offset = call.request.queryParameters["offset"]?.toIntOrNull() ?: 0

                            // If no storage roots configured yet, return a friendly error in JSON
                            if (!ServiceLocator.isRootSet()) {
                                return@get call.respond(
                                    FilesResponse(
                                        items = emptyList(),
                                        total = 0,
                                        offset = 0,
                                        limit = 0,
                                        error = "No shared folders configured. Open Stremer on Android and select storage folders to share."
                                    )
                                )
                            }

                            // Stream files one by one as NDJSON (newline-delimited JSON)
                            // This allows the client to render items as they arrive, not waiting for the full list
                            call.respondBytesWriter(ContentType.parse("application/x-ndjson")) {
                                try {
                                    val fileSequence = ServiceLocator.streamFiles(path.trim('/'))
                                    var skipped = 0
                                    var count = 0

                                    for (item in fileSequence) {
                                        // Skip items if offset is specified
                                        if (skipped < offset) {
                                            skipped++
                                            continue
                                        }

                                        // Stop streaming if we've reached the limit
                                        if (limit != null && count >= limit) {
                                            android.util.Log.d("Server", "Stream limit reached: $limit for path: $path (offset: $offset)")
                                            break
                                        }

                                        // Serialize each item as JSON and send immediately
                                        val json = kotlinx.serialization.json.Json.encodeToString(com.stremer.files.FileItem.serializer(), item)
                                        writeFully((json + "\n").encodeToByteArray())
                                        flush()
                                        count++
                                    }
                                    android.util.Log.d("Server", "Streamed $count files for path: $path (offset: $offset)")
                                } catch (e: Exception) {
                                    android.util.Log.e("Server", "Stream error: ${e.message}", e)
                                    val errorJson = "{\"error\": \"${e.message?.replace("\"", "\\\"")}\"}\n"
                                    writeFully(errorJson.encodeToByteArray())
                                }
                            }
                        } catch (e: Exception) {
                            // Fallback to error response
                            android.util.Log.e("Server", "/files endpoint error: ${e.message}", e)
                            call.respond(
                                FilesResponse(
                                    items = emptyList(),
                                    total = 0,
                                    offset = 0,
                                    limit = 0,
                                    error = ("Error listing files: ${e.message}. Make sure storage is selected.")
                                )
                            )
                        }
                    }
                    delete("/file") {
                        val path = call.request.queryParameters["path"] ?: return@delete call.respondText(
                            "Missing path",
                            status = HttpStatusCode.BadRequest
                        )
                        val ok = ServiceLocator.delete(path.trim('/'))
                        if (ok) call.respond(mapOf("status" to "deleted")) else call.respondText(
                            "Delete failed",
                            status = HttpStatusCode.InternalServerError
                        )
                    }
                    post("/copy") {
                        val json = call.receive<Map<String, String>>()
                        val src = json["src"] ?: return@post call.respondText("Missing src", status = HttpStatusCode.BadRequest)
                        val dst = json["dst"] ?: return@post call.respondText("Missing dst", status = HttpStatusCode.BadRequest)
                        val ok = ServiceLocator.copy(src.trim('/'), dst.trim('/'))
                        if (ok) call.respond(mapOf("status" to "copied")) else call.respondText(
                            "Copy failed",
                            status = HttpStatusCode.InternalServerError
                        )
                    }

                    // Rename endpoint
                    post("/rename") {
                        val json = call.receive<Map<String, String>>()
                        val path = json["path"] ?: return@post call.respondText("Missing path", status = HttpStatusCode.BadRequest)
                        val newName = json["newName"] ?: return@post call.respondText("Missing newName", status = HttpStatusCode.BadRequest)
                        val ok = ServiceLocator.rename(path.trim('/'), newName.trim('/'))
                        if (ok) call.respond(mapOf("status" to "renamed")) else call.respondText(
                            "Rename failed",
                            status = HttpStatusCode.InternalServerError
                        )
                    }

                    // Create directory
                    post("/mkdir") {
                        val json = call.receive<Map<String, String>>()
                        val parent = json["path"] ?: return@post call.respondText("Missing path", status = HttpStatusCode.BadRequest)
                        val name = json["name"] ?: return@post call.respondText("Missing name", status = HttpStatusCode.BadRequest)
                        val ok = ServiceLocator.mkdir(parent.trim('/'), name.trim('/'))
                        if (ok) call.respond(mapOf("status" to "created")) else call.respondText(
                            "Create directory failed",
                            status = HttpStatusCode.InternalServerError
                        )
                    }

                    // Create empty file
                    post("/createFile") {
                        val json = call.receive<Map<String, String>>()
                        val parent = json["path"] ?: return@post call.respondText("Missing path", status = HttpStatusCode.BadRequest)
                        val name = json["name"] ?: return@post call.respondText("Missing name", status = HttpStatusCode.BadRequest)
                        val mime = json["mime"]
                        val ok = ServiceLocator.createFile(parent.trim('/'), name.trim('/'), mime)
                        if (ok) call.respond(mapOf("status" to "created")) else call.respondText(
                            "Create file failed",
                            status = HttpStatusCode.InternalServerError
                        )
                    }

                    // Metadata endpoint
                    get("/meta") {
                        try {
                            val path = call.request.queryParameters["path"] ?: return@get call.respondText(
                                "Missing path",
                                status = HttpStatusCode.BadRequest
                            )
                            val file = ServiceLocator.getDocumentFile(path.trim('/'))
                            if (file == null) {
                                return@get call.respondText("Not found", status = HttpStatusCode.NotFound)
                            }
                            val isDir = file.isDirectory
                            val name = file.name ?: "unknown"
                            var size: Long? = if (file.isFile) file.length() else null
                            val lastMod = try { file.lastModified() } catch (_: Exception) { null }
                            var mime: String? = file.type ?: if (isDir) "inode/directory" else "application/octet-stream"

                            var width: Int? = null
                            var height: Int? = null
                            var durationMs: Long? = null
                            var itemCount: Int? = null

                            val lower = name.lowercase()
                            val ctx = ServiceLocator.context()
                            if (!isDir && ctx != null) {
                                if (lower.endsWith(".mp4") || lower.endsWith(".mkv") || lower.endsWith(".avi") || lower.endsWith(".mov") || lower.endsWith(".webm") || lower.endsWith(".mp3") || lower.endsWith(".m4a") || lower.endsWith(".flac") || lower.endsWith(".3gp") || lower.endsWith(".ts")) {
                                    try {
                                        val retriever = android.media.MediaMetadataRetriever()
                                        retriever.setDataSource(ctx, file.uri)
                                        val dur = retriever.extractMetadata(android.media.MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull()
                                        val w = retriever.extractMetadata(android.media.MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull()
                                        val h = retriever.extractMetadata(android.media.MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull()
                                        durationMs = dur
                                        if (w != null && h != null) {
                                            width = w
                                            height = h
                                        }
                                        retriever.release()
                                    } catch (e: Exception) {
                                        android.util.Log.w("Server", "Media metadata error: ${e.message}")
                                    }
                                } else if (lower.endsWith(".jpg") || lower.endsWith(".jpeg") || lower.endsWith(".png") || lower.endsWith(".gif") || lower.endsWith(".bmp") || lower.endsWith(".webp") || lower.endsWith(".heic") || lower.endsWith(".heif")) {
                                    try {
                                        val opts = android.graphics.BitmapFactory.Options()
                                        opts.inJustDecodeBounds = true
                                        ServiceLocator.openInputStream(path.trim('/'))?.use { ins ->
                                            android.graphics.BitmapFactory.decodeStream(ins, null, opts)
                                        }
                                        width = opts.outWidth
                                        height = opts.outHeight
                                    } catch (e: Exception) {
                                        android.util.Log.w("Server", "Image bounds error: ${e.message}")
                                    }
                                }
                            }

                            if (isDir) {
                                try {
                                    val children = file.listFiles()
                                    itemCount = children?.size
                                } catch (_: Exception) {
                                    itemCount = null
                                }
                            }

                            val meta = MetaResponse(
                                name = name,
                                type = if (isDir) "dir" else "file",
                                mime = mime,
                                size = size,
                                lastModified = lastMod,
                                width = width,
                                height = height,
                                durationMs = durationMs,
                                itemCount = itemCount
                            )
                            call.respond(meta)
                        } catch (e: Exception) {
                            android.util.Log.e("Server", "Meta endpoint error: ${e.message}")
                            call.respondText("Error getting metadata", status = HttpStatusCode.InternalServerError)
                        }
                    }

                    // Thumbnail endpoint (auth via bearer header)
                    get("/thumb") {
                        try {
                            val path = call.request.queryParameters["path"] ?: return@get call.respondText(
                                "Missing path",
                                status = HttpStatusCode.BadRequest
                            )

                            val uri = ServiceLocator.getUri(path.trim('/'))
                            if (uri == null) {
                                return@get call.respondText("Not found", status = HttpStatusCode.NotFound)
                            }

                            // Decide target size based on query or defaults
                            val maxW = call.request.queryParameters["w"]?.toIntOrNull() ?: 256
                            val maxH = call.request.queryParameters["h"]?.toIntOrNull() ?: 256

                            // Use different generation for images vs videos by file extension
                            val lower = path.lowercase()
                            val isVideo = lower.endsWith(".mp4") || lower.endsWith(".mkv") || lower.endsWith(".avi") || lower.endsWith(".mov") || lower.endsWith(".webm")
                            val isImage = lower.endsWith(".jpg") || lower.endsWith(".jpeg") || lower.endsWith(".png") || lower.endsWith(".gif") || lower.endsWith(".bmp") || lower.endsWith(".webp")

                            // Generate Bitmap
                            var bitmap: android.graphics.Bitmap? = try {
                                if (isVideo) {
                                    // Try a single, best-effort frame extraction. If it fails, generate a simple
                                    // generic video icon so thumbnails are visible for unsupported containers.
                                    val retriever = android.media.MediaMetadataRetriever()
                                    var frame: android.graphics.Bitmap? = null
                                    try {
                                        val ctx = ServiceLocator.context()
                                        if (ctx != null) {
                                            retriever.setDataSource(ctx, uri)
                                        } else {
                                            retriever.setDataSource(uri.toString(), java.util.HashMap())
                                        }
                                        frame = try {
                                            retriever.getFrameAtTime(-1, android.media.MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
                                        } catch (e: Exception) {
                                            null
                                        }
                                    } catch (e: Exception) {
                                        android.util.Log.w("Server", "MediaMetadataRetriever setDataSource failed for $path: ${e.message}")
                                    } finally {
                                        try { retriever.release() } catch (_: Exception) {}
                                    }

                                    if (frame != null) {
                                        frame
                                    } else {
                                        // Create a simple video icon (dark background + white play triangle)
                                        val iconBitmap = android.graphics.Bitmap.createBitmap(maxW.coerceAtLeast(1), maxH.coerceAtLeast(1), android.graphics.Bitmap.Config.ARGB_8888)
                                        val canvas = android.graphics.Canvas(iconBitmap)
                                        canvas.drawColor(android.graphics.Color.parseColor("#1a1a1a"))
                                        val paint = android.graphics.Paint().apply {
                                            color = android.graphics.Color.WHITE
                                            style = android.graphics.Paint.Style.FILL
                                            isAntiAlias = true
                                        }
                                        val cx = iconBitmap.width / 2f
                                        val cy = iconBitmap.height / 2f
                                        val s = (minOf(iconBitmap.width, iconBitmap.height) * 0.28f)
                                        val pathP = android.graphics.Path()
                                        pathP.moveTo(cx - s/2f, cy - s)
                                        pathP.lineTo(cx - s/2f, cy + s)
                                        pathP.lineTo(cx + s, cy)
                                        pathP.close()
                                        canvas.drawPath(pathP, paint)
                                        iconBitmap
                                    }
                                } else if (isImage) {
                                    // Downsample large images to near requested size to avoid OOM and binder slowness
                                    val fd = ServiceLocator.openInputStream(path.trim('/'))
                                    if (fd != null) {
                                        fd.use { input1 ->
                                            val opts1 = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
                                            android.graphics.BitmapFactory.decodeStream(input1, null, opts1)
                                        }
                                        val opts2 = android.graphics.BitmapFactory.Options().apply {
                                            inJustDecodeBounds = false
                                            inPreferredConfig = android.graphics.Bitmap.Config.RGB_565
                                            inDither = true
                                            inSampleSize = run {
                                                var sample = 1
                                                var outW = android.graphics.BitmapFactory.Options().outWidth
                                                var outH = android.graphics.BitmapFactory.Options().outHeight
                                                // The above outW/outH won't be set; re-open stream to get bounds properly
                                                // Safely reopen and compute sample size
                                                val bOpts = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
                                                ServiceLocator.openInputStream(path.trim('/'))?.use { ins ->
                                                    android.graphics.BitmapFactory.decodeStream(ins, null, bOpts)
                                                }
                                                outW = bOpts.outWidth
                                                outH = bOpts.outHeight
                                                while (outW / sample > maxW * 2 || outH / sample > maxH * 2) sample *= 2
                                                if (sample < 1) 1 else sample
                                            }
                                        }
                                        ServiceLocator.openInputStream(path.trim('/'))?.use { ins2 ->
                                            android.graphics.BitmapFactory.decodeStream(ins2, null, opts2)
                                        }
                                    } else null
                                } else null
                            } catch (e: Exception) {
                                android.util.Log.e("Server", "Thumbnail error: ${e.message}")
                                null
                            }

                            if (bitmap == null) {
                                // No bitmap could be extracted. Generate a simple file-type icon so
                                // clients always have a visible thumbnail. Use a short uppercase
                                // label (PDF, TXT, MP3, PY, JS, DOC, XLS, etc.) on a colored
                                // background chosen per file type.
                                val ext = lower.substringAfterLast('.', "")
                                val label = when (ext) {
                                    "pdf" -> "PDF"
                                    "txt" -> "TXT"
                                    "md" -> "MD"
                                    "mp3" -> "MP3"
                                    "wav" -> "AUD"
                                    "flac" -> "AUD"
                                    "exe" -> "EXE"
                                    "json" -> "JSON"
                                    "py" -> "PY"
                                    "yaml", "yml" -> "YML"
                                    "js" -> "JS"
                                    "ts" -> "TS"
                                    "doc", "docx" -> "DOC"
                                    "xls", "xlsx" -> "XLS"
                                    "ppt", "pptx" -> "PPT"
                                    "apk" -> "APK"
                                    "zip", "rar", "7z" -> "ZIP"
                                    else -> if (isVideo) "VID" else ext.uppercase().takeIf { it.isNotEmpty() } ?: "FILE"
                                }

                                val colorHex = when (label) {
                                    "PDF" -> "#D32F2F"
                                    "TXT", "MD" -> "#757575"
                                    "MP3", "AUD" -> "#FB8C00"
                                    "EXE", "APK" -> "#303F9F"
                                    "JSON", "PY", "YML", "JS", "TS" -> "#388E3C"
                                    "DOC" -> "#1976D2"
                                    "XLS" -> "#2E7D32"
                                    "PPT" -> "#E64A19"
                                    "ZIP" -> "#6D4C41"
                                    "VID" -> "#424242"
                                    else -> "#455A64"
                                }

                                // Create bitmap sized to requested max dimensions
                                val w = maxW.coerceAtLeast(1)
                                val h = maxH.coerceAtLeast(1)
                                val iconBitmap = android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888)
                                val canvas = android.graphics.Canvas(iconBitmap)
                                val bgColor = try { android.graphics.Color.parseColor(colorHex) } catch (_: Exception) { android.graphics.Color.DKGRAY }
                                canvas.drawColor(bgColor)

                                val paint = android.graphics.Paint().apply {
                                    isAntiAlias = true
                                    style = android.graphics.Paint.Style.FILL
                                    color = android.graphics.Color.WHITE
                                    typeface = android.graphics.Typeface.create(android.graphics.Typeface.DEFAULT, android.graphics.Typeface.BOLD)
                                }

                                // Choose text color based on background luminance
                                val r = android.graphics.Color.red(bgColor) / 255.0
                                val g = android.graphics.Color.green(bgColor) / 255.0
                                val b = android.graphics.Color.blue(bgColor) / 255.0
                                val lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
                                if (lum > 0.7) paint.color = android.graphics.Color.BLACK else paint.color = android.graphics.Color.WHITE

                                // Text size ~35% of smaller dimension
                                val ts = (minOf(w, h) * 0.35f)
                                paint.textSize = ts
                                paint.textAlign = android.graphics.Paint.Align.CENTER

                                val cx = w / 2f
                                val cy = h / 2f
                                val textY = cy - (paint.descent() + paint.ascent()) / 2f
                                canvas.drawText(label, cx, textY, paint)

                                // Use this generated icon as the bitmap
                                bitmap = iconBitmap
                            }

                            // Scale down preserving aspect ratio
                            val srcW = bitmap.width
                            val srcH = bitmap.height
                            val scale = minOf(maxW.toFloat() / srcW.toFloat(), maxH.toFloat() / srcH.toFloat(), 1.0f)
                            val dstW = (srcW * scale).toInt().coerceAtLeast(1)
                            val dstH = (srcH * scale).toInt().coerceAtLeast(1)
                            val thumb = if (dstW != srcW || dstH != srcH) {
                                android.graphics.Bitmap.createScaledBitmap(bitmap, dstW, dstH, true)
                            } else bitmap

                            // Encode as JPEG for size/compat
                            val baos = java.io.ByteArrayOutputStream()
                            thumb.compress(android.graphics.Bitmap.CompressFormat.JPEG, 80, baos)
                            val bytes = baos.toByteArray()

                            // Respond with cache headers
                            call.response.headers.append(io.ktor.http.HttpHeaders.CacheControl, "public, max-age=604800")
                            call.respondBytes(bytes, ContentType.Image.JPEG)
                        } catch (e: Exception) {
                            android.util.Log.e("Server", "Thumb endpoint error: ${e.message}")
                            call.respondText("Error generating thumbnail", status = HttpStatusCode.InternalServerError)
                        }
                    }
                }

                // Stream endpoint outside auth block to support token in query param
                get("/stream") {
                    val path = call.request.queryParameters["path"] ?: return@get call.respondText(
                        "Missing path",
                        status = HttpStatusCode.BadRequest
                    )
                    // Support token in query param for VLC
                    val tokenParam = call.request.queryParameters["token"]
                    val authHeader = call.request.headers["Authorization"]?.removePrefix("Bearer ")

                    if (com.stremer.auth.AuthManager.isEnabled()) {
                        val validToken = tokenParam ?: authHeader
                        if (validToken != ServiceLocator.token) {
                            android.util.Log.e("Server", "Invalid token. Expected: ${ServiceLocator.token}, Got: $validToken")
                            return@get call.respondText("Unauthorized", status = HttpStatusCode.Unauthorized)
                        }
                    }

                    android.util.Log.d("Server", "Streaming file: $path")

                    val fileInfo = ServiceLocator.getFileInfo(path.trim('/'))
                    if (fileInfo == null) {
                        android.util.Log.e("Server", "File not found: $path")
                        return@get call.respondText("Not found", status = HttpStatusCode.NotFound)
                    }

                    val fileSize = fileInfo.size ?: 0L

                    // Parse Range header
                    val rangeHeader = call.request.headers["Range"]
                    var (start, end) = if (rangeHeader != null && rangeHeader.startsWith("bytes=")) {
                        val rangeValue = rangeHeader.substringAfter("bytes=")
                        val parts = rangeValue.split("-")
                        val rangeStart = parts[0].toLongOrNull() ?: 0L
                        val rangeEnd = if (parts.size > 1 && parts[1].isNotEmpty()) {
                            parts[1].toLongOrNull() ?: (fileSize - 1)
                        } else {
                            fileSize - 1
                        }
                        android.util.Log.d("Server", "Range request: $rangeStart-$rangeEnd")
                        Pair(rangeStart, rangeEnd)
                    } else {
                        Pair(0L, fileSize - 1)
                    }

                    // Clamp and validate range
                    if (start < 0) start = 0
                    if (end >= fileSize) end = fileSize - 1
                    if (end < start) end = start

                    val input = ServiceLocator.openInputStream(path.trim('/'))
                    if (input == null) {
                        android.util.Log.e("Server", "Cannot open stream: $path")
                        return@get call.respondText("Cannot open file", status = HttpStatusCode.InternalServerError)
                    }

                    // Detect content type from filename
                    val contentType = when {
                        path.endsWith(".mp4", ignoreCase = true) -> ContentType.parse("video/mp4")
                        path.endsWith(".mkv", ignoreCase = true) -> ContentType.parse("video/x-matroska")
                        path.endsWith(".avi", ignoreCase = true) -> ContentType.parse("video/x-msvideo")
                        path.endsWith(".mov", ignoreCase = true) -> ContentType.parse("video/quicktime")
                        else -> ContentType.Application.OctetStream
                    }

                    val contentLength = end - start + 1
                    android.util.Log.d("Server", "Streaming $start-$end ($contentLength bytes) of $fileSize as $contentType")

                    // Use 206 Partial Content if range requested, 200 OK otherwise
                    val statusCode = if (rangeHeader != null) HttpStatusCode.PartialContent else HttpStatusCode.OK

                    // HEAD support: return headers only
                    if (call.request.httpMethod == io.ktor.http.HttpMethod.Head) {
                        call.response.status(statusCode)
                        call.response.headers.append(io.ktor.http.HttpHeaders.AcceptRanges, "bytes")
                        call.response.headers.append(io.ktor.http.HttpHeaders.Connection, "keep-alive")
                        if (statusCode == HttpStatusCode.PartialContent) {
                            call.response.headers.append(io.ktor.http.HttpHeaders.ContentRange, "bytes $start-$end/$fileSize")
                            call.response.headers.append(io.ktor.http.HttpHeaders.ContentLength, contentLength.toString())
                        } else {
                            call.response.headers.append(io.ktor.http.HttpHeaders.ContentLength, fileSize.toString())
                        }
                        return@get
                    }

                    call.respond(object : io.ktor.http.content.OutgoingContent.WriteChannelContent() {
                        override val contentLength: Long = contentLength
                        override val contentType: ContentType = contentType
                        override val status: HttpStatusCode = statusCode
                        override val headers: io.ktor.http.Headers = io.ktor.http.headersOf(
                            io.ktor.http.HttpHeaders.AcceptRanges to listOf("bytes"),
                            io.ktor.http.HttpHeaders.Connection to listOf("keep-alive"),
                            io.ktor.http.HttpHeaders.ContentRange to listOf("bytes $start-$end/$fileSize")
                        )

                        override suspend fun writeTo(channel: io.ktor.utils.io.ByteWriteChannel) {
                            input.use { stream ->
                                // Ensure we skip exactly 'start' bytes; InputStream.skip may be partial
                                var toSkip = start
                                while (toSkip > 0) {
                                    val skipped = stream.skip(toSkip)
                                    if (skipped <= 0) break
                                    toSkip -= skipped
                                }

                                val buffer = ByteArray(64 * 1024) // 64KB chunks
                                var remaining = contentLength
                                var totalSent = 0L

                                while (remaining > 0) {
                                    val toRead = minOf(buffer.size.toLong(), remaining).toInt()
                                    val bytes = stream.read(buffer, 0, toRead)
                                    if (bytes <= 0) break

                                    channel.writeFully(buffer, 0, bytes)
                                    remaining -= bytes
                                    totalSent += bytes
                                }
                                channel.flush()
                                android.util.Log.d("Server", "Stream completed: $totalSent bytes sent for $path (requested $contentLength)")
                            }
                        }
                    })
                }
            }
        }.start(wait = false)
    }

    fun stop() {
        engine?.stop(1000, 2000)
        engine = null
    }

    fun isRunning(): Boolean = engine != null

    fun getPort(): Int = currentPort

    fun getServerUrl(): String {
        val ip = getLocalIpAddress() ?: "localhost"
        return "http://$ip:$currentPort"
    }

    private fun getLocalIpAddress(): String? {
        return try {
            val interfaces = java.net.NetworkInterface.getNetworkInterfaces()
            for (networkInterface in interfaces) {
                if (!networkInterface.isUp || networkInterface.isLoopback) continue
                val addresses = networkInterface.inetAddresses
                for (address in addresses) {
                    if (!address.isLoopbackAddress && address is java.net.Inet4Address) {
                        return address.hostAddress
                    }
                }
            }
            null
        } catch (e: Exception) {
            android.util.Log.e("Server", "Error getting local IP", e)
            null
        }
    }
}
