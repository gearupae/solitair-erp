package com.alnajah.alnajah_scan_example

import android.app.Activity
import android.content.pm.PackageManager
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

/**
 * Single in-flight camera permission request for the activity.
 * Used by [BarcodeScannerPlatformView] — avoids overlapping permission dialogs.
 */
internal object CameraPermissionHelper {
    private const val REQ_CAMERA = 0x5c01

    private var pending: ((Boolean) -> Unit)? = null

    fun hasPermission(activity: Activity): Boolean =
        ContextCompat.checkSelfPermission(
            activity,
            android.Manifest.permission.CAMERA,
        ) == PackageManager.PERMISSION_GRANTED

    fun request(activity: Activity, onResult: (Boolean) -> Unit) {
        if (hasPermission(activity)) {
            onResult(true)
            return
        }
        pending = onResult
        try {
            ActivityCompat.requestPermissions(
                activity,
                arrayOf(android.Manifest.permission.CAMERA),
                REQ_CAMERA,
            )
        } catch (e: Exception) {
            pending = null
            onResult(false)
        }
    }

    fun dispatchRequestPermissionsResult(
        requestCode: Int,
        grantResults: IntArray,
    ) {
        if (requestCode != REQ_CAMERA) return
        val ok = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
        val cb = pending
        pending = null
        try {
            cb?.invoke(ok)
        } catch (_: Exception) {
            // Never crash the app from a callback
        }
    }
}
