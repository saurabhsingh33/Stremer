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

    fun start(): Boolean {
        if (cameraDevice != null) return true
        val cameraId = cameraManager.cameraIdList.firstOrNull { id ->
            val chars = cameraManager.getCameraCharacteristics(id)
            val lensFacing = chars.get(CameraCharacteristics.LENS_FACING)
            lensFacing == CameraCharacteristics.LENS_FACING_BACK
        } ?: cameraManager.cameraIdList.firstOrNull() ?: return false

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
}
