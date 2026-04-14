package com.gearup.gearup_scan_example

import android.content.Context
import io.flutter.embedding.android.FlutterActivity
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.StandardMessageCodec
import io.flutter.plugin.platform.PlatformView
import io.flutter.plugin.platform.PlatformViewFactory

/**
 * Embeds ML Kit + CameraX preview into Flutter via [PlatformView].
 */
internal class BarcodeScannerViewFactory(
    private val messenger: BinaryMessenger,
    private val activity: FlutterActivity,
) : PlatformViewFactory(StandardMessageCodec.INSTANCE) {

    override fun create(context: Context, viewId: Int, args: Any?): PlatformView {
        return BarcodeScannerPlatformView(
            context = context,
            viewId = viewId,
            messenger = messenger,
            activity = activity,
        )
    }
}
