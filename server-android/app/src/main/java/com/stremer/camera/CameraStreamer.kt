package com.stremer.camera

import android.app.Activity
import android.graphics.ImageFormat
import android.hardware.camera2.*
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.view.Surface
import java.nio.ByteBuffer
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Minimal camera helper to capture a single JPEG frame on demand.
 * This opens the back camera, captures one frame, and closes immediately.
 */
class CameraStreamer(private val activity: Activity) {
    private val cameraManager: CameraManager = activity.getSystemService(CameraManager::class.java)

    @Volatile private var cameraDevice: CameraDevice? = null
    @Volatile private var session: CameraCaptureSession? = null
    @Volatile private var reader: ImageReader? = null
    @Volatile private var handlerThread: HandlerThread? = null
    @Volatile private var handler: Handler? = null
    private val frameQueue: java.util.concurrent.LinkedBlockingQueue<ByteArray> = java.util.concurrent.LinkedBlockingQueue(2)

    private var currentCameraId: String? = null
    private var currentLens: String? = null
    private var currentBrightness: Int? = null
    private var currentSharpness: Int? = null

    fun start(lens: String? = null, brightness: Int? = null, sharpness: Int? = null): Boolean {
        val targetLens = lens?.lowercase()
        val needsReopen = cameraDevice == null || currentLens != targetLens || currentBrightness != brightness || currentSharpness != sharpness
        if (!needsReopen) return true

        stop()

        val cameraId = pickCameraId(targetLens) ?: return false
        currentCameraId = cameraId
        currentLens = targetLens
        currentBrightness = brightness
        currentSharpness = sharpness

        try {
            handlerThread = HandlerThread("stremer-camera").also { it.start() }
            handler = Handler(handlerThread!!.looper)

            val characteristics = cameraManager.getCameraCharacteristics(cameraId)
            val streamConfig = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            val size = streamConfig?.getOutputSizes(ImageFormat.JPEG)?.firstOrNull() ?: android.util.Size(640, 480)
            reader = ImageReader.newInstance(size.width, size.height, ImageFormat.JPEG, 2)

            reader!!.setOnImageAvailableListener({ ir ->
                val image = ir.acquireLatestImage() ?: return@setOnImageAvailableListener
                try {
                    val buffer: ByteBuffer = image.planes[0].buffer
                    val bytes = ByteArray(buffer.remaining())
                    buffer.get(bytes)
                    if (!frameQueue.offer(bytes)) {
                        frameQueue.poll()
                        frameQueue.offer(bytes)
                    }
                } catch (_: Exception) {
                } finally {
                    image.close()
                    try {
                        cameraDevice?.let { dev ->
                            session?.capture(dev.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                                addTarget(reader!!.surface)
                                set(CaptureRequest.CONTROL_MODE, CameraMetadata.CONTROL_MODE_AUTO)
                                set(CaptureRequest.CONTROL_AE_MODE, CameraMetadata.CONTROL_AE_MODE_ON)
                                set(CaptureRequest.FLASH_MODE, CameraMetadata.FLASH_MODE_OFF)
                                applyExposureCompensation(this, characteristics)
                                applySharpness(this, characteristics)
                                set(CaptureRequest.JPEG_ORIENTATION, getJpegOrientation(characteristics))
                            }.build(), object : CameraCaptureSession.CaptureCallback() {}, handler)
                        }
                    } catch (_: Exception) { }
                }
            }, handler)

            val openLatch = CountDownLatch(1)
            val stateCallback = object : CameraDevice.StateCallback() {
                override fun onOpened(device: CameraDevice) {
                    cameraDevice = device
                    try {
                        device.createCaptureSession(listOf(reader!!.surface), object : CameraCaptureSession.StateCallback() {
                            override fun onConfigured(sess: CameraCaptureSession) {
                                session = sess
                                try {
                                    val req = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                                        addTarget(reader!!.surface)
                                        set(CaptureRequest.CONTROL_MODE, CameraMetadata.CONTROL_MODE_AUTO)
                                        set(CaptureRequest.CONTROL_AE_MODE, CameraMetadata.CONTROL_AE_MODE_ON)
                                        set(CaptureRequest.FLASH_MODE, CameraMetadata.FLASH_MODE_OFF)
                                        applyExposureCompensation(this, characteristics)
                                        applySharpness(this, characteristics)
                                        set(CaptureRequest.JPEG_ORIENTATION, getJpegOrientation(characteristics))
                                    }
                                    sess.capture(req.build(), object : CameraCaptureSession.CaptureCallback() {}, handler)
                                } catch (_: Exception) { }
                                openLatch.countDown()
                            }
                            override fun onConfigureFailed(p0: CameraCaptureSession) { openLatch.countDown() }
                        }, handler)
                    } catch (_: Exception) {
                        openLatch.countDown()
                    }
                }
                override fun onDisconnected(device: CameraDevice) { device.close(); openLatch.countDown() }
                override fun onError(device: CameraDevice, error: Int) { device.close(); openLatch.countDown() }
            }

            cameraManager.openCamera(cameraId, stateCallback, handler)
            return openLatch.await(1500, TimeUnit.MILLISECONDS)
        } catch (_: SecurityException) {
            return false
        } catch (_: Exception) {
            return false
        }
    }

    fun nextFrame(timeoutMs: Long = 1000): ByteArray? {
        return try { frameQueue.poll(timeoutMs, TimeUnit.MILLISECONDS) } catch (_: Exception) { null }
    }

    fun stop() {
        try { frameQueue.clear() } catch (_: Exception) {}
        try { session?.close() } catch (_: Exception) {}
        try { cameraDevice?.close() } catch (_: Exception) {}
        try { reader?.close() } catch (_: Exception) {}
        try { handlerThread?.quitSafely() } catch (_: Exception) {}
        session = null; cameraDevice = null; reader = null; handlerThread = null; handler = null
    }

    private fun getJpegOrientation(characteristics: CameraCharacteristics): Int {
        val sensorOrientation = characteristics.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0
        val lensFacing = characteristics.get(CameraCharacteristics.LENS_FACING)
        val deviceRotation = activity.windowManager.defaultDisplay.rotation
        val deviceDegrees = when (deviceRotation) {
            Surface.ROTATION_90 -> 90
            Surface.ROTATION_180 -> 180
            Surface.ROTATION_270 -> 270
            else -> 0
        }
        // Adjust to match most device back-camera outputs: back = sensor + device; front = sensor - device.
        return if (lensFacing == CameraCharacteristics.LENS_FACING_FRONT) {
            (sensorOrientation - deviceDegrees + 360) % 360
        } else {
            (sensorOrientation + deviceDegrees) % 360
        }
    }

    private fun pickCameraId(lens: String?): String? {
        val list = cameraManager.cameraIdList
        val back = list.firstOrNull { id ->
            val chars = cameraManager.getCameraCharacteristics(id)
            chars.get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
        }
        val front = list.firstOrNull { id ->
            val chars = cameraManager.getCameraCharacteristics(id)
            chars.get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_FRONT
        }
        return when (lens) {
            "front" -> front ?: back ?: list.firstOrNull()
            "back" -> back ?: front ?: list.firstOrNull()
            else -> back ?: list.firstOrNull()
        }
    }

    private fun applyExposureCompensation(builder: CaptureRequest.Builder, characteristics: CameraCharacteristics) {
        val target = currentBrightness ?: return
        val range = characteristics.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_RANGE) ?: return
        val maxAbs = maxOf(abs(range.lower), abs(range.upper))
        if (maxAbs == 0) return
        val percent = target.coerceIn(-100, 100)
        val comp = ((percent / 100.0) * maxAbs).roundToInt().coerceIn(range.lower, range.upper)
        builder.set(CaptureRequest.CONTROL_AE_EXPOSURE_COMPENSATION, comp)
    }

    private fun applySharpness(builder: CaptureRequest.Builder, characteristics: CameraCharacteristics) {
        val target = currentSharpness ?: return
        val modes = characteristics.get(CameraCharacteristics.EDGE_AVAILABLE_EDGE_MODES) ?: return
        val pct = target.coerceIn(0, 100)
        val desired = when {
            pct <= 10 && modes.contains(CaptureRequest.EDGE_MODE_OFF) -> CaptureRequest.EDGE_MODE_OFF
            pct <= 60 && modes.contains(CaptureRequest.EDGE_MODE_FAST) -> CaptureRequest.EDGE_MODE_FAST
            modes.contains(CaptureRequest.EDGE_MODE_HIGH_QUALITY) -> CaptureRequest.EDGE_MODE_HIGH_QUALITY
            modes.contains(CaptureRequest.EDGE_MODE_FAST) -> CaptureRequest.EDGE_MODE_FAST
            else -> null
        }
        desired?.let { builder.set(CaptureRequest.EDGE_MODE, it) }
    }
}
