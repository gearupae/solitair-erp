package com.gearup.gearup_scan_example

import android.content.res.Configuration
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

class MainActivity : FlutterActivity() {

    /** Activity is not recreated on rotation (see manifest configChanges); forward to Flutter + CameraX. */
    override fun onConfigurationChanged(newConfig: Configuration) {
        try {
            super.onConfigurationChanged(newConfig)
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "onConfigurationChanged", e)
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
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
