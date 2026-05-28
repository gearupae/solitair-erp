package com.alnajah.alnajah_scan_example

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.hardware.camera2.CameraAccessException
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.SystemClock
import android.util.Log
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import io.flutter.embedding.android.FlutterActivity
import com.google.mlkit.vision.common.InputImage
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.platform.PlatformView
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * ML Kit Barcode + CameraX preview embedded in Flutter.
 *
 * - Analysis runs on a dedicated background [ExecutorService] (never blocks UI thread).
 * - [ProcessCameraProvider.unbindAll] before each bind; full unbind on pause/destroy.
 * - 1s cooldown between accepted reads to avoid duplicate counts.
 * - All camera / ML Kit entry points wrapped in try/catch.
 */
@OptIn(ExperimentalGetImage::class)
@SuppressLint("ViewConstructor")
internal class BarcodeScannerPlatformView(
    context: Context,
    private val viewId: Int,
    messenger: io.flutter.plugin.common.BinaryMessenger,
    private val activity: FlutterActivity,
    initialCameraMode: Boolean = true,
) : PlatformView {

    companion object {
        private const val TAG = "AlnajahBarcodeView"
        private const val COOLDOWN_MS = 1000L
        private const val CHANNEL_PREFIX = "alnajah_barcode_scanner"

        /**
         * Fallback when [BarcodeScanning.getClient] (no args) fails — explicit symbologies only.
         * Prefer the default client first: ML Kit enables **all** formats by default, which often
         * helps marginal reads (glare, angle). Curved/wet labels remain a physics limit for any camera.
         *
         * Note: [BarcodeScannerOptions.Builder.enableAllPotentialBarcodes] returns regions where
         * decode failed ([Barcode.getRawValue] null) — useful for zoom UX, not for our string-only API path.
         */
        private fun buildBarcodeScannerOptions(): BarcodeScannerOptions =
            BarcodeScannerOptions.Builder()
                .setBarcodeFormats(
                    Barcode.FORMAT_QR_CODE,
                    Barcode.FORMAT_DATA_MATRIX,
                    Barcode.FORMAT_PDF417,
                    Barcode.FORMAT_AZTEC,
                    Barcode.FORMAT_UPC_A,
                    Barcode.FORMAT_UPC_E,
                    Barcode.FORMAT_EAN_13,
                    Barcode.FORMAT_EAN_8,
                    Barcode.FORMAT_CODE_128,
                    Barcode.FORMAT_CODE_39,
                    Barcode.FORMAT_CODE_93,
                    Barcode.FORMAT_CODABAR,
                    Barcode.FORMAT_ITF,
                )
                .build()
    }

    private val root: FrameLayout = FrameLayout(context)
    private val previewView: PreviewView = PreviewView(context).apply {
        // COMPATIBLE (TextureView) is more stable inside Flutter PlatformView than PERFORMANCE
        // (SurfaceView): fewer native crashes / ANRs when composited with the Flutter surface.
        implementationMode = PreviewView.ImplementationMode.COMPATIBLE
        scaleType = PreviewView.ScaleType.FILL_CENTER
    }
    /** Physical USB/BT scanner (HID) — camera off, same result path via Activity wedge + Flutter. */
    private val scannerReadyBanner: TextView = TextView(context).apply {
        setBackgroundColor(Color.BLACK)
        setTextColor(Color.WHITE)
        gravity = Gravity.CENTER
        textSize = 17f
        setPadding(48, 48, 48, 48)
        text = "Scanner ready — scan now"
        visibility = View.GONE
    }
    private val overlay: TextView = TextView(context).apply {
        setBackgroundColor(0xCC000000.toInt())
        setTextColor(Color.WHITE)
        gravity = Gravity.CENTER
        textSize = 16f
        setPadding(48, 48, 48, 48)
        visibility = View.GONE
    }

    private val methodChannel = MethodChannel(messenger, "$CHANNEL_PREFIX/$viewId")

    /** Lazy-init on [analysisExecutor] only — avoids races where CameraX delivers frames before async ML Kit init finished (all scans were dropped). */
    @Volatile
    private var scanner: BarcodeScanner? = null
    private val scannerInitLock = Any()

    private val analysisExecutor: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "alnajah-mlkit-analysis").apply { isDaemon = true }
    }

    private var cameraProvider: ProcessCameraProvider? = null
    /** Set after [ProcessCameraProvider.bindToLifecycle]; cleared on unbind / dispose. */
    private var boundCamera: Camera? = null
    private val isReleased = AtomicBoolean(false)
    /** Same value re-read within [COOLDOWN_MS] is ignored (avoids duplicate counts when label stays in view). */
    private val cooldownLock = Any()
    private var lastBarcodeForCooldown = ""
    private var lastBarcodeClockMs = 0L

    /** When false, camera is unbound and [scannerReadyBanner] is shown (HID wedge handles input). */
    private var isCameraMode = initialCameraMode

    private val lifecycleObserver = object : DefaultLifecycleObserver {
        override fun onPause(owner: LifecycleOwner) {
            releaseCameraUseCases("onPause")
        }

        override fun onResume(owner: LifecycleOwner) {
            if (!isCameraMode) {
                overlay.visibility = View.GONE
                applyCameraModeUi()
                return
            }
            if (CameraPermissionHelper.hasPermission(activity)) {
                overlay.visibility = View.GONE
                tryBindCamera("onResume")
            } else {
                showPermissionPlaceholder()
            }
        }

        override fun onDestroy(owner: LifecycleOwner) {
            disposeInternal()
        }
    }

    init {
        root.addView(
            previewView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )
        root.addView(
            scannerReadyBanner,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )
        root.addView(
            overlay,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )

        try {
            activity.lifecycle.addObserver(lifecycleObserver)
        } catch (e: Exception) {
            Log.e(TAG, "lifecycle addObserver", e)
        }

        overlay.setOnClickListener {
            try {
                if (isCameraMode) {
                    requestCameraAndBind()
                }
            } catch (e: Exception) {
                Log.e(TAG, "overlay click", e)
            }
        }

        // Match UI to mode before first frame — avoids a flash of camera preview when Flutter
        // recreates the view while the user is in Scanner mode (default used to be camera=true).
        if (!isCameraMode) {
            applyCameraModeUi()
        }

        // Do not call requestCameraAndBind() here: it raced Flutter's setCameraMode from
        // onPlatformViewCreated and could start the camera before "Scanner" mode was applied.
        // First bind: Flutter invokes setCameraMode(true) after the method channel is ready.
        // ML Kit client is created lazily on the analysis thread (see [ensureScanner]) so the first
        // frames are never processed with scanner == null.

        // Flutter -> native: torch (Dart [invokeMethod]); native -> Flutter: onBarcode ([invokeMethod] from here).
        methodChannel.setMethodCallHandler { call, result ->
            when (call.method) {
                "setTorch" -> {
                    try {
                        val on = call.arguments == true
                        setTorchEnabled(on)
                        result.success(true)
                    } catch (e: Exception) {
                        Log.e(TAG, "setTorch", e)
                        result.error("TORCH", e.message, null)
                    }
                }
                "setCameraMode" -> {
                    try {
                        val cameraOn = call.arguments == true
                        setCameraMode(cameraOn)
                        result.success(null)
                    } catch (e: Exception) {
                        Log.e(TAG, "setCameraMode", e)
                        result.error("MODE", e.message, null)
                    }
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun applyCameraModeUi() {
        if (isCameraMode) {
            previewView.visibility = View.VISIBLE
            scannerReadyBanner.visibility = View.GONE
        } else {
            previewView.visibility = View.GONE
            scannerReadyBanner.visibility = View.VISIBLE
            overlay.visibility = View.GONE
        }
    }

    private fun setCameraMode(cameraOn: Boolean) {
        if (isReleased.get()) return
        isCameraMode = cameraOn
        activity.runOnUiThread {
            if (isReleased.get()) return@runOnUiThread
            if (cameraOn) {
                applyCameraModeUi()
                if (CameraPermissionHelper.hasPermission(activity)) {
                    overlay.visibility = View.GONE
                    tryBindCamera("setCameraMode")
                } else {
                    requestCameraAndBind()
                }
            } else {
                releaseCameraUseCases("setCameraMode-scanner")
                applyCameraModeUi()
            }
        }
    }

    private fun showPermissionPlaceholder() {
        if (!isCameraMode) return
        try {
            overlay.text =
                "Camera permission is required for scanning.\n\nTap here to grant permission."
            overlay.visibility = View.VISIBLE
        } catch (e: Exception) {
            Log.e(TAG, "showPermissionPlaceholder", e)
        }
    }

    private fun requestCameraAndBind() {
        try {
            CameraPermissionHelper.request(activity) { granted ->
                try {
                    if (granted) {
                        overlay.visibility = View.GONE
                        tryBindCamera("permissionGranted")
                    } else {
                        showPermissionPlaceholder()
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "permission callback", e)
                    showPermissionPlaceholder()
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "requestCameraAndBind", e)
            showPermissionPlaceholder()
        }
    }

    private fun tryBindCamera(reason: String, allowDefer: Boolean = true) {
        if (isReleased.get()) return
        if (!canBindCameraNow()) {
            if (allowDefer) {
                previewView.post {
                    if (isReleased.get()) return@post
                    tryBindCamera("$reason-deferred", allowDefer = false)
                }
            } else {
                Log.w(TAG, "skip tryBindCamera ($reason): lifecycle=${activity.lifecycle.currentState}")
            }
            return
        }
        if (!CameraPermissionHelper.hasPermission(activity)) {
            showPermissionPlaceholder()
            return
        }
        val mainExecutor = ContextCompat.getMainExecutor(activity)
        val future = try {
            ProcessCameraProvider.getInstance(activity)
        } catch (e: Exception) {
            Log.e(TAG, "ProcessCameraProvider.getInstance: $reason", e)
            return
        }

        future.addListener(
            {
                if (isReleased.get()) return@addListener
                try {
                    // Listener runs when the future completes — get() must not block here.
                    val provider = future.get()
                    cameraProvider = provider
                    bindUseCases(provider, reason)
                } catch (e: IllegalStateException) {
                    Log.e(TAG, "provider get IllegalState: $reason", e)
                } catch (e: CameraAccessException) {
                    Log.e(TAG, "provider get CameraAccess: $reason", e)
                } catch (e: Exception) {
                    Log.e(TAG, "provider get: $reason", e)
                }
            },
            mainExecutor,
        )
    }

    /** CameraX requires the activity lifecycle to be at least STARTED to bind use cases. */
    private fun canBindCameraNow(): Boolean =
        activity.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)

    private fun bindUseCases(provider: ProcessCameraProvider, reason: String) {
        if (isReleased.get()) return
        if (!canBindCameraNow()) {
            Log.w(TAG, "skip bindUseCases ($reason): bad lifecycle")
            return
        }
        val lifecycleOwner = activity
        try {
            provider.unbindAll()
        } catch (e: IllegalStateException) {
            Log.w(TAG, "unbindAll IllegalState: $reason", e)
        } catch (e: Exception) {
            Log.w(TAG, "unbindAll: $reason", e)
        }

        val preview = Preview.Builder().build().also {
            try {
                it.setSurfaceProvider(previewView.surfaceProvider)
            } catch (e: Exception) {
                Log.e(TAG, "setSurfaceProvider", e)
                return
            }
        }

        val imageAnalysis = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
            .build()

        try {
            imageAnalysis.setAnalyzer(analysisExecutor) { imageProxy ->
                try {
                    analyzeImageSafe(imageProxy)
                } catch (t: Throwable) {
                    Log.e(TAG, "analyzer throwable", t)
                    try {
                        imageProxy.close()
                    } catch (_: Exception) {
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "setAnalyzer", e)
            return
        }

        boundCamera = null
        try {
            boundCamera = provider.bindToLifecycle(
                lifecycleOwner,
                CameraSelector.DEFAULT_BACK_CAMERA,
                preview,
                imageAnalysis,
            )
        } catch (e: IllegalStateException) {
            Log.e(TAG, "bindToLifecycle IllegalState: $reason", e)
            boundCamera = null
        } catch (e: CameraAccessException) {
            Log.e(TAG, "bindToLifecycle CameraAccess: $reason", e)
            boundCamera = null
        } catch (e: Exception) {
            Log.e(TAG, "bindToLifecycle: $reason", e)
            boundCamera = null
        }
    }

    private fun setTorchEnabled(enabled: Boolean) {
        val cam = boundCamera ?: return
        try {
            val future = cam.cameraControl.enableTorch(enabled)
            val mainExecutor = ContextCompat.getMainExecutor(activity)
            future.addListener(
                {
                    try {
                        future.get()
                    } catch (e: Exception) {
                        Log.w(TAG, "enableTorch future", e)
                    }
                },
                mainExecutor,
            )
        } catch (e: CameraAccessException) {
            Log.w(TAG, "enableTorch CameraAccess", e)
        } catch (e: IllegalStateException) {
            Log.w(TAG, "enableTorch IllegalState", e)
        } catch (e: Exception) {
            Log.w(TAG, "enableTorch", e)
        }
    }

    /**
     * Must only be called from [analysisExecutor]. Initializes ML Kit on first use on this thread
     * so we never drop frames while an async init (old lifecycleScope launch) was still running.
     */
    private fun ensureScanner(): BarcodeScanner? {
        scanner?.let { return it }
        synchronized(scannerInitLock) {
            if (isReleased.get()) return null
            scanner?.let { return it }
            return try {
                val created = try {
                    BarcodeScanning.getClient()
                } catch (e: Exception) {
                    Log.w(TAG, "BarcodeScanning.getClient() default", e)
                    BarcodeScanning.getClient(buildBarcodeScannerOptions())
                }
                scanner = created
                created
            } catch (e: Exception) {
                Log.e(TAG, "BarcodeScanning failed (default + explicit fallback)", e)
                null
            }
        }
    }

    private fun analyzeImageSafe(imageProxy: ImageProxy) {
        if (isReleased.get()) {
            try {
                imageProxy.close()
            } catch (_: Exception) {
            }
            return
        }
        val sc = ensureScanner()
        if (sc == null) {
            try {
                imageProxy.close()
            } catch (_: Exception) {
            }
            return
        }

        val mediaImage = try {
            imageProxy.image
        } catch (e: Exception) {
            try {
                imageProxy.close()
            } catch (_: Exception) {
            }
            return
        }

        if (mediaImage == null) {
            try {
                imageProxy.close()
            } catch (_: Exception) {
            }
            return
        }

        val inputImage: InputImage = try {
            InputImage.fromMediaImage(
                mediaImage,
                imageProxy.imageInfo.rotationDegrees,
            )
        } catch (e: Exception) {
            try {
                imageProxy.close()
            } catch (_: Exception) {
            }
            return
        }

        try {
            sc.process(inputImage)
                .addOnSuccessListener(analysisExecutor) { barcodes ->
                    try {
                        handleBarcodeResults(barcodes)
                    } catch (e: Exception) {
                        Log.e(TAG, "handleBarcodeResults", e)
                    }
                }
                .addOnFailureListener(analysisExecutor) { e ->
                    Log.w(TAG, "ML Kit process failure", e)
                }
                .addOnCompleteListener(analysisExecutor) {
                    try {
                        imageProxy.close()
                    } catch (e: Exception) {
                        Log.w(TAG, "imageProxy.close", e)
                    }
                }
        } catch (e: Exception) {
            Log.e(TAG, "scanner.process", e)
            try {
                imageProxy.close()
            } catch (_: Exception) {
            }
        }
    }

    private fun handleBarcodeResults(barcodes: MutableList<Barcode>) {
        if (barcodes.isEmpty()) return

        val code = barcodes.firstOrNull() ?: return
        val raw = code.rawValue?.trim().orEmpty()
        if (raw.isEmpty()) return

        val now = SystemClock.elapsedRealtime()
        synchronized(cooldownLock) {
            if (raw == lastBarcodeForCooldown && now - lastBarcodeClockMs < COOLDOWN_MS) return
            lastBarcodeForCooldown = raw
            lastBarcodeClockMs = now
        }

        // Beep + vibrate on successful decode (camera read), on main thread
        activity.runOnUiThread {
            try {
                playSuccessFeedback()
            } catch (e: Exception) {
                Log.w(TAG, "feedback", e)
            }
            try {
                methodChannel.invokeMethod("onBarcode", raw)
            } catch (e: Exception) {
                Log.e(TAG, "invokeMethod onBarcode", e)
            }
        }
    }

    private fun playSuccessFeedback() {
        try {
            @Suppress("DEPRECATION")
            val tone = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 80)
            tone.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
            tone.release()
        } catch (_: Exception) {
        }
        try {
            val vib = activity.getSystemService(Context.VIBRATOR_SERVICE) as? android.os.Vibrator
                ?: return
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vib.vibrate(
                    android.os.VibrationEffect.createOneShot(
                        40,
                        android.os.VibrationEffect.DEFAULT_AMPLITUDE,
                    ),
                )
            } else {
                @Suppress("DEPRECATION")
                vib.vibrate(40)
            }
        } catch (_: Exception) {
        }
    }

    private fun releaseCameraUseCases(reason: String) {
        try {
            try {
                boundCamera?.cameraControl?.enableTorch(false)
            } catch (e: Exception) {
                Log.w(TAG, "torch off before unbind", e)
            }
            boundCamera = null
            cameraProvider?.unbindAll()
        } catch (e: IllegalStateException) {
            Log.w(TAG, "release unbindAll IllegalState: $reason", e)
        } catch (e: Exception) {
            Log.w(TAG, "release unbindAll: $reason", e)
        }
    }

    private fun disposeInternal() {
        if (!isReleased.compareAndSet(false, true)) return
        try {
            activity.lifecycle.removeObserver(lifecycleObserver)
        } catch (e: Exception) {
            Log.w(TAG, "removeObserver", e)
        }
        try {
            methodChannel.setMethodCallHandler(null)
        } catch (e: Exception) {
            Log.w(TAG, "methodChannel handler clear", e)
        }
        releaseCameraUseCases("dispose")
        cameraProvider = null
        try {
            analysisExecutor.shutdown()
        } catch (e: Exception) {
            Log.w(TAG, "executor shutdown", e)
        }
        try {
            scanner?.close()
            scanner = null
        } catch (e: Exception) {
            Log.w(TAG, "scanner.close", e)
        }
    }

    override fun getView(): View = root

    override fun dispose() {
        disposeInternal()
    }
}
