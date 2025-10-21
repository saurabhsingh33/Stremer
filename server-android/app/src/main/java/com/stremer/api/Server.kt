package com.stremer.api

import com.stremer.di.ServiceLocator
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

object Server {
    private var engine: ApplicationEngine? = null

    fun start(port: Int = 8080) {
        engine = embeddedServer(CIO, port = port) {
            install(ContentNegotiation) {
                json()
            }
            install(Authentication) {
                bearer("auth-bearer") {
                    authenticate { tokenCredential ->
                        // If auth disabled, allow any request
                        if (!com.stremer.auth.AuthManager.isEnabled()) {
                            UserIdPrincipal("anon")
                        } else if (tokenCredential.token == ServiceLocator.token) {
                            UserIdPrincipal("user")
                        } else null
                    }
                }
            }
            routing {
                // login issues token (stored in ServiceLocator)
                post("/auth/login") {
                    val params = call.receiveParameters()
                    val user = params["username"]
                    val pass = params["password"]
                    // If auth disabled, issue token regardless (or a fixed token)
                    if (!com.stremer.auth.AuthManager.isEnabled() || ServiceLocator.validate(user, pass)) {
                        ServiceLocator.issueTokenFor(user ?: "user")
                        call.respond(mapOf("token" to ServiceLocator.token))
                    } else {
                        call.respondText("Invalid credentials", status = HttpStatusCode.Unauthorized)
                    }
                }

                authenticate("auth-bearer") {
                    get("/files") {
                        try {
                            val path = call.request.queryParameters["path"] ?: "/"
                            val items = ServiceLocator.safList(path.trim('/'))
                            call.respond(mapOf("items" to items))
                        } catch (e: Exception) {
                            call.respondText(
                                "Error listing files: ${e.message}. Make sure storage is selected.",
                                status = HttpStatusCode.InternalServerError
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
                            val bitmap: android.graphics.Bitmap? = try {
                                if (isVideo) {
                                    val retriever = android.media.MediaMetadataRetriever()
                                    val ctx = ServiceLocator.context()
                                    if (ctx != null) {
                                        retriever.setDataSource(ctx, uri)
                                    } else {
                                        // Fallback: attempt without context (may fail for content URIs)
                                        retriever.setDataSource(uri.toString(), java.util.HashMap())
                                    }
                                    val frame = retriever.getFrameAtTime(0)
                                    retriever.release()
                                    frame
                                } else if (isImage) {
                                    val input = ServiceLocator.openInputStream(path.trim('/'))
                                    if (input != null) {
                                        input.use { android.graphics.BitmapFactory.decodeStream(it) }
                                    } else null
                                } else null
                            } catch (e: Exception) {
                                android.util.Log.e("Server", "Thumbnail error: ${e.message}")
                                null
                            }

                            if (bitmap == null) {
                                return@get call.respondText("Unsupported or failed to create thumbnail", status = HttpStatusCode.UnsupportedMediaType)
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
}
