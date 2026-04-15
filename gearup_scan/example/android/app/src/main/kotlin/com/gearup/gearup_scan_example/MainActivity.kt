package com.gearup.gearup_scan_example

import android.content.res.Configuration
import android.view.KeyEvent
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * Intercepts HID keyboard-wedge scanners (USB / Bluetooth in HID mode) at the Activity level.
 * When the camera [AndroidView] has focus, keystrokes may not reach Flutter's hidden [TextField];
 * [dispatchKeyEvent] buffers characters until Enter/Tab, then sends the barcode to Flutter.
 *
 * Flutter enables capture only on the stock-take scan screen via [gearup_hid_control] `setWedgeCapture`.
 */
class MainActivity : FlutterActivity() {

    private val wedgeBuffer = StringBuilder(64)

    @Volatile
    private var hidWedgeCapture = false

    private var hidWedgeOut: MethodChannel? = null

    /** Activity is not recreated on rotation (see manifest configChanges). */
    override fun onConfigurationChanged(newConfig: Configuration) {
        try {
            super.onConfigurationChanged(newConfig)
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "onConfigurationChanged", e)
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        hidWedgeOut = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "gearup_hid_wedge")
        try {
            MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "gearup_hid_control")
                .setMethodCallHandler { call, result ->
                    when (call.method) {
                        "setWedgeCapture" -> {
                            try {
                                hidWedgeCapture = call.arguments == true
                                wedgeBuffer.setLength(0)
                                result.success(null)
                            } catch (e: Exception) {
                                result.error("WEDGE", e.message, null)
                            }
                        }
                        else -> result.notImplemented()
                    }
                }
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "gearup_hid_control", e)
        }
        try {
            flutterEngine.platformViewsController.registry.registerViewFactory(
                "gearup_barcode_scanner",
                BarcodeScannerViewFactory(
                    flutterEngine.dartExecutor.binaryMessenger,
                    this,
                ),
            )
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "registerViewFactory", e)
        }
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (!hidWedgeCapture || event.action != KeyEvent.ACTION_DOWN) {
            return super.dispatchKeyEvent(event)
        }
        return try {
            when (event.keyCode) {
                KeyEvent.KEYCODE_ENTER,
                KeyEvent.KEYCODE_NUMPAD_ENTER,
                KeyEvent.KEYCODE_TAB,
                -> {
                    flushWedgeBufferToFlutter()
                    true
                }
                KeyEvent.KEYCODE_BACK -> super.dispatchKeyEvent(event)
                else -> {
                    val u = event.unicodeChar
                    if (u != 0) {
                        wedgeBuffer.append(u.toChar())
                        true
                    } else {
                        super.dispatchKeyEvent(event)
                    }
                }
            }
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "dispatchKeyEvent wedge", e)
            super.dispatchKeyEvent(event)
        }
    }

    private fun flushWedgeBufferToFlutter() {
        val s = wedgeBuffer.toString().trim()
        wedgeBuffer.setLength(0)
        if (s.isEmpty()) return
        try {
            hidWedgeOut?.invokeMethod("barcode", s)
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "invoke barcode", e)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        try {
            super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "super.onRequestPermissionsResult", e)
        }
        try {
            CameraPermissionHelper.dispatchRequestPermissionsResult(requestCode, grantResults)
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "dispatchRequestPermissionsResult", e)
        }
    }
}
