import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:alnajah_scan/alnajah_scan.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _kPrefBaseUrl = 'alnajah_scan_base_url';
const _kPrefUsername = 'alnajah_scan_username';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AlnajahScanExampleApp());
}

class AlnajahScanExampleApp extends StatelessWidget {
  const AlnajahScanExampleApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Al Najah Scan',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal),
        useMaterial3: true,
      ),
      home: const LoginPage(),
    );
  }
}

// ─────────────────────────────────────────── Login ───────────────────────────

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _base = TextEditingController();
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _busy = false;
  bool _prefsLoaded = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadPrefs();
  }

  Future<void> _loadPrefs() async {
    final p = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() {
      _base.text = p.getString(_kPrefBaseUrl) ?? '';
      _user.text = p.getString(_kPrefUsername) ?? '';
      _prefsLoaded = true;
    });
  }

  Future<void> _savePrefs() async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kPrefBaseUrl, _base.text.trim());
    await p.setString(_kPrefUsername, _user.text.trim());
  }

  Future<void> _login() async {
    final origin = _base.text.trim();
    if (origin.isEmpty) {
      setState(() => _error = 'Enter your ERP server URL.');
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      final client = AlnajahScanClient(baseUrl: origin);
      await client.login(username: _user.text.trim(), password: _pass.text);
      await _savePrefs();
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(builder: (_) => SessionListPage(client: client)),
      );
    } on AlnajahScanException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _base.dispose();
    _user.dispose();
    _pass.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_prefsLoaded) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Al Najah — scan')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text(
            'Sign in with your ERP username and password.',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 20),
          TextField(
            controller: _base,
            decoration: const InputDecoration(
              labelText: 'ERP server URL',
              hintText: 'http://37.27.16.210',
            ),
            keyboardType: TextInputType.url,
            autocorrect: false,
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _user,
            decoration: const InputDecoration(labelText: 'Username'),
            autocorrect: false,
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _pass,
            decoration: const InputDecoration(labelText: 'Password'),
            obscureText: true,
            onSubmitted: (_) => _login(),
          ),
          if (_error != null) ...[
            const SizedBox(height: 16),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _busy ? null : _login,
            child: _busy
                ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Sign in'),
          ),
        ],
      ),
    );
  }
}

// ────────────────────────────────────── Session list ─────────────────────────

class SessionListPage extends StatefulWidget {
  const SessionListPage({super.key, required this.client});
  final AlnajahScanClient client;

  @override
  State<SessionListPage> createState() => _SessionListPageState();
}

class _SessionListPageState extends State<SessionListPage> {
  List<StockTakeSessionSummary>? _sessions;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() { _loading = true; _error = null; });
    try {
      final list = await widget.client.listStockTakeSessions();
      if (mounted) setState(() => _sessions = list);
    } on AlnajahScanException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _logout() async {
    try { await widget.client.logout(); } catch (_) {}
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute<void>(builder: (_) => const LoginPage()),
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Stock take sessions'),
        actions: [
          IconButton(onPressed: _load, icon: const Icon(Icons.refresh)),
          IconButton(onPressed: _logout, icon: const Icon(Icons.logout)),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(_error!)))
              : (_sessions == null || _sessions!.isEmpty)
                  ? const Center(child: Text('No in-progress stock take sessions.'))
                  : ListView.builder(
                      itemCount: _sessions!.length,
                      itemBuilder: (context, i) {
                        final s = _sessions![i];
                        return ListTile(
                          title: Text(s.clientName),
                          subtitle: Text('${s.location} · ${s.sessionDate} · ${_lines(s.lineCount)}'),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () => Navigator.of(context).push(
                            MaterialPageRoute<void>(
                              builder: (_) => ScanPage(
                                client: widget.client,
                                sessionId: s.id,
                                title: s.clientName,
                              ),
                            ),
                          ),
                        );
                      },
                    ),
    );
  }

  static String _lines(int n) => n == 1 ? '1 line' : '$n lines';
}

// ─────────────────────────────────────────── Scan ────────────────────────────

class ScanPage extends StatefulWidget {
  const ScanPage({
    super.key,
    required this.client,
    required this.sessionId,
    required this.title,
  });

  final AlnajahScanClient client;
  final int sessionId;
  final String title;

  @override
  State<ScanPage> createState() => _ScanPageState();
}

/// Immutable last-scan display — updated via ValueNotifier only, never triggers camera rebuild.
class _ScanResult {
  const _ScanResult({this.message = 'Point at a barcode to scan', this.ok});
  final String message;
  final bool? ok; // true = matched, false = unknown/error, null = idle
}

/// Camera (ML Kit / mobile_scanner) vs physical HID scanner (USB / BT keyboard wedge).
enum _ScanInputMode { camera, scanner }

class _ScanPageState extends State<ScanPage> {
  /// Android APK uses native ML Kit + CameraX ([AndroidView]); iOS/other use [mobile_scanner].
  static bool get _useNativeAndroidScanner => !kIsWeb && Platform.isAndroid;

  // Controller is nullable — created AFTER first frame (mobile_scanner path only).
  MobileScannerController? _cam;
  StreamSubscription<BarcodeCapture>? _sub;
  MethodChannel? _nativeBarcodeChannel;
  /// Android Activity-level HID wedge (USB/BT scanner); see [MainActivity.dispatchKeyEvent].
  MethodChannel? _hidControl;
  MethodChannel? _hidWedgeRx;
  /// Torch state for Android native path (Flutter toggles via [MethodChannel] `setTorch`).
  bool _torchOn = false;

  _ScanInputMode _inputMode = _ScanInputMode.camera;

  final TextEditingController _wedge = TextEditingController();
  final FocusNode _wedgeFocus = FocusNode();
  final ValueNotifier<_ScanResult> _result = ValueNotifier(const _ScanResult());
  final ValueNotifier<Color?> _flash = ValueNotifier<Color?>(null);

  Timer? _idleTimer;
  Timer? _flashTimer;

  // Guard against overlapping HTTP calls — checked in _onBarcode, NOT via stream pause/resume.
  // pause()/resume() on a platform-channel broadcast stream can deadlock on some Android versions.
  bool _busy = false;
  bool _alive = true;

  // Debounce same-barcode: prevents continuous counting when a label is held in front of the camera.
  // User can intentionally scan the same item again after _kSameBarcodeCooldown.
  String _lastRaw = '';
  DateTime _lastScanAt = DateTime.fromMillisecondsSinceEpoch(0);
  static const _kSameBarcodeCooldown = Duration(milliseconds: 2500);

  // ─────────── lifecycle ───────────

  @override
  void initState() {
    super.initState();
    _wedge.addListener(_onWedgeInput);
    // Android: capture USB/BT HID scanner at Activity level (camera PlatformView often steals focus).
    if (!kIsWeb && Platform.isAndroid) {
      _hidControl = const MethodChannel('alnajah_hid_control');
      _hidWedgeRx = const MethodChannel('alnajah_hid_wedge');
      _hidWedgeRx!.setMethodCallHandler((call) async {
        if (!_alive || !mounted) return;
        if (call.method == 'barcode') {
          final a = call.arguments;
          if (a is String && a.trim().isNotEmpty && !_busy) {
            unawaited(_submit(a.trim()));
          }
        }
      });
      // Wedge only in Scanner mode — camera mode uses ML Kit only (no double counts).
      unawaited(_hidControl!.invokeMethod<void>('setWedgeCapture', false));
    }
    if (!_useNativeAndroidScanner) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _startCamera());
    }
  }

  void _onScannerViewCreated(int id) {
    _nativeBarcodeChannel = MethodChannel('alnajah_barcode_scanner/$id');
    _nativeBarcodeChannel!.setMethodCallHandler((call) async {
      if (!_alive) return;
      if (call.method == 'onBarcode') {
        final raw = call.arguments;
        if (raw is String && raw.isNotEmpty) {
          // Native layer: 1s cooldown per barcode + ML Kit off UI thread; submit when not busy.
          if (!_busy) unawaited(_submit(raw));
        }
      }
    });
    unawaited(_invokeNativeSetCameraMode());
  }

  /// Syncs Camera / Scanner mode to native after [AndroidView] is ready (retry once — avoids no-op bind).
  Future<void> _invokeNativeSetCameraMode() async {
    if (!_useNativeAndroidScanner) return;
    final ch = _nativeBarcodeChannel;
    if (ch == null) return;
    final camera = _inputMode == _ScanInputMode.camera;
    try {
      await ch.invokeMethod<void>('setCameraMode', camera);
    } catch (_) {
      await Future<void>.delayed(const Duration(milliseconds: 300));
      if (!_alive || !mounted) return;
      try {
        await _nativeBarcodeChannel?.invokeMethod<void>('setCameraMode', camera);
      } catch (_) {}
    }
  }

  void _setInputMode(_ScanInputMode mode) {
    if (_inputMode == mode) return;
    if (!_useNativeAndroidScanner && mode == _ScanInputMode.scanner) {
      _sub?.cancel();
      _sub = null;
      _cam?.dispose();
      _cam = null;
    }
    setState(() {
      _inputMode = mode;
      if (mode == _ScanInputMode.scanner) _torchOn = false;
    });
    if (!kIsWeb && Platform.isAndroid) {
      unawaited(
        _hidControl?.invokeMethod<void>(
          'setWedgeCapture',
          mode == _ScanInputMode.scanner,
        ),
      );
      unawaited(_invokeNativeSetCameraMode());
    }
    if (!_useNativeAndroidScanner && mode == _ScanInputMode.camera) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || !_alive) return;
        if (_inputMode != _ScanInputMode.camera) return;
        if (_cam == null) _startCamera();
      });
    }
  }

  Future<void> _toggleTorch() async {
    if (!_alive || !mounted) return;
    try {
      if (_useNativeAndroidScanner) {
        final next = !_torchOn;
        await _nativeBarcodeChannel?.invokeMethod<void>('setTorch', next);
        if (_alive && mounted) setState(() => _torchOn = next);
      } else {
        final c = _cam;
        if (c != null) {
          await c.toggleTorch();
          if (_alive && mounted) setState(() {});
        }
      }
    } catch (_) {
      if (_useNativeAndroidScanner && _alive && mounted) {
        setState(() {});
      }
    }
  }

  void _showManualBarcodeDialog() {
    if (!_alive || !mounted) return;
    final manual = TextEditingController();
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Enter barcode'),
        content: TextField(
          controller: manual,
          autofocus: true,
          keyboardType: TextInputType.visiblePassword,
          autocorrect: false,
          decoration: const InputDecoration(
            hintText: 'Type or paste SKU / barcode',
          ),
          onSubmitted: (s) {
            Navigator.of(ctx).pop();
            final t = s.trim();
            if (t.isNotEmpty) unawaited(_submit(t));
          },
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.of(ctx).pop();
              final t = manual.text.trim();
              if (t.isNotEmpty) unawaited(_submit(t));
            },
            child: const Text('Submit'),
          ),
        ],
      ),
    ).whenComplete(manual.dispose);
  }

  void _startCamera() {
    if (!_alive || !mounted) return;
    final cam = MobileScannerController(
      // normal + detectionTimeoutMs: ML Kit runs at most every 1500 ms.
      // noDuplicates was removed — it silently blocks re-scanning the same item,
      // which is wrong for stock-take where you scan multiple identical items.
      detectionSpeed: DetectionSpeed.normal,
      detectionTimeoutMs: 1500,
      facing: CameraFacing.back,
      // No cameraResolution — requesting unsupported sizes crashes some devices.
    );
    // Listen to the stream. We do NOT pause/resume — we gate via _busy instead.
    _sub = cam.barcodes.listen(_onBarcode, cancelOnError: false);
    setState(() => _cam = cam);
  }

  @override
  void dispose() {
    _alive = false;
    if (!kIsWeb && Platform.isAndroid) {
      _hidWedgeRx?.setMethodCallHandler(null);
      _hidWedgeRx = null;
      try {
        _hidControl?.invokeMethod<void>('setWedgeCapture', false);
      } catch (_) {}
      _hidControl = null;
    }
    _nativeBarcodeChannel?.setMethodCallHandler(null);
    _nativeBarcodeChannel = null;
    _flashTimer?.cancel();
    _idleTimer?.cancel();
    _sub?.cancel();
    _sub = null;
    _cam?.dispose();
    _cam = null;
    _wedge.removeListener(_onWedgeInput);
    _wedge.dispose();
    _wedgeFocus.dispose();
    _result.dispose();
    _flash.dispose();
    super.dispose();
  }

  // ─────────── camera stream ───────────

  static String _raw(Barcode b) {
    final v = (b.rawValue ?? '').trim();
    return v.isNotEmpty ? v : (b.displayValue ?? '').trim();
  }

  void _onBarcode(BarcodeCapture cap) {
    if (_busy || !_alive) return;
    final raw = cap.barcodes.map(_raw).firstWhere((s) => s.isNotEmpty, orElse: () => '');
    if (raw.isEmpty) return;

    // Debounce: same barcode within cooldown window → skip (prevents continuous multi-count
    // when a label is held steady in front of the camera lens).
    final now = DateTime.now();
    if (raw == _lastRaw && now.difference(_lastScanAt) < _kSameBarcodeCooldown) return;
    _lastRaw = raw;
    _lastScanAt = now;

    unawaited(_submit(raw));
  }

  // ─────────── wedge (USB / BT keyboard) ───────────

  void _onWedgeInput() {
    _idleTimer?.cancel();
    _idleTimer = Timer(const Duration(milliseconds: 300), _flushWedge);
  }

  void _flushWedge() {
    _idleTimer?.cancel();
    final raw = _wedge.text.trim();
    _wedge.clear();
    if (raw.isNotEmpty) unawaited(_submit(raw));
  }

  // ─────────── submit to ERP ───────────

  Future<void> _submit(String raw) async {
    if (_busy || !_alive) return;
    _busy = true;
    // No stream pause here — pausing a platform-channel stream buffers native events,
    // causing a burst-delivery and potential deadlock on resume.
    try {
      final r = await widget.client.submitScan(widget.sessionId, barcode: raw);
      if (!_alive || !mounted) return;
      if (r.ok && r.matched == true) {
        _result.value = _ScanResult(
          ok: true,
          message: '✓  ${r.itemName ?? r.sku} — actual: ${r.actualQty}  (expected: ${r.expectedQty})',
        );
        _doFlash(Colors.green.withValues(alpha: 0.35), durationMs: 380);
      } else if (r.ok && r.unknown == true) {
        _result.value = _ScanResult(ok: false, message: 'Unknown barcode: $raw');
        _doFlash(Colors.red.withValues(alpha: 0.45), durationMs: 500, beep: true);
      } else {
        _result.value = _ScanResult(ok: false, message: r.error ?? 'Scan failed');
        _doFlash(Colors.red.withValues(alpha: 0.45), durationMs: 500, beep: true);
      }
    } catch (e) {
      if (!_alive || !mounted) return;
      _result.value = _ScanResult(ok: false, message: 'Error: $e');
      _doFlash(Colors.red.withValues(alpha: 0.45), durationMs: 500, beep: true);
    } finally {
      // Always clear busy so new scans can come in.
      if (_alive) _busy = false;
    }
  }

  // ─────────── flash feedback ───────────

  void _doFlash(Color color, {required int durationMs, bool beep = false}) {
    if (!_alive || !mounted) return;
    _flashTimer?.cancel();
    _flash.value = color;
    if (beep) {
      try { HapticFeedback.heavyImpact(); } catch (_) {}
      try { SystemSound.play(SystemSoundType.alert); } catch (_) {}
    }
    _flashTimer = Timer(Duration(milliseconds: durationMs), () {
      if (_alive && mounted) _flash.value = null;
    });
  }

  // ─────────── build ───────────

  @override
  Widget build(BuildContext context) {
    final cam = _cam;
    final cs = Theme.of(context).colorScheme;

    return Scaffold(
      // Reduces relayout / PlatformView churn when the soft keyboard or IME toggles (ANRs on some devices).
      resizeToAvoidBottomInset: false,
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        surfaceTintColor: Colors.transparent,
        title: Text(widget.title),
        // Camera / Scanner toggle lives in the app bar so it stays *above* the Android
        // PlatformView. A native view in the body is often composited on top of Flutter
        // siblings after the first frame, which made the old in-body control vanish.
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(56),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            child: Align(
              alignment: Alignment.topCenter,
              child: SegmentedButton<_ScanInputMode>(
                showSelectedIcon: false,
                emptySelectionAllowed: false,
                style: ButtonStyle(
                  visualDensity: VisualDensity.compact,
                  side: WidgetStateProperty.all(BorderSide(color: Colors.white.withValues(alpha: 0.35))),
                  backgroundColor: WidgetStateProperty.resolveWith((states) {
                    if (states.contains(WidgetState.selected)) {
                      return cs.primary;
                    }
                    return Colors.white.withValues(alpha: 0.08);
                  }),
                  foregroundColor: WidgetStateProperty.resolveWith((states) {
                    if (states.contains(WidgetState.selected)) {
                      return cs.onPrimary;
                    }
                    return Colors.white.withValues(alpha: 0.88);
                  }),
                ),
                segments: const [
                  ButtonSegment<_ScanInputMode>(
                    value: _ScanInputMode.camera,
                    label: Text('Camera'),
                    icon: Icon(Icons.photo_camera_outlined),
                  ),
                  ButtonSegment<_ScanInputMode>(
                    value: _ScanInputMode.scanner,
                    label: Text('Scanner'),
                    icon: Icon(Icons.keyboard_alt_outlined),
                  ),
                ],
                selected: {_inputMode},
                onSelectionChanged: (Set<_ScanInputMode> next) {
                  if (next.isEmpty) return;
                  _setInputMode(next.first);
                },
              ),
            ),
          ),
        ),
        actions: [
          IconButton(
            tooltip: 'Enter barcode manually',
            onPressed: _showManualBarcodeDialog,
            icon: const Icon(Icons.keyboard),
          ),
          if (!_useNativeAndroidScanner || _inputMode == _ScanInputMode.camera)
            IconButton(
              tooltip: _useNativeAndroidScanner
                  ? (_torchOn ? 'Turn off flashlight' : 'Turn on flashlight')
                  : 'Toggle flashlight',
              onPressed: _toggleTorch,
              icon: Icon(
                _useNativeAndroidScanner
                    ? (_torchOn ? Icons.flashlight_on : Icons.flashlight_off_outlined)
                    : Icons.flashlight_on,
              ),
            ),
          if (!_useNativeAndroidScanner)
            IconButton(
              tooltip: 'Focus USB / BT scanner',
              onPressed: () => _wedgeFocus.requestFocus(),
              icon: const Icon(Icons.keyboard_alt_outlined),
            ),
        ],
      ),
      body: Column(
        children: [
          // ── Camera preview (takes most of the screen) ──
          Expanded(
            child: _useNativeAndroidScanner
                ? Stack(
                    fit: StackFit.expand,
                    children: [
                      AndroidView(
                        key: const ValueKey<Object>('alnajah_barcode_scanner'),
                        viewType: 'alnajah_barcode_scanner',
                        onPlatformViewCreated: _onScannerViewCreated,
                      ),
                      ValueListenableBuilder<Color?>(
                        valueListenable: _flash,
                        builder: (_, tint, __) => tint == null
                            ? const SizedBox.shrink()
                            : IgnorePointer(
                                child: ColoredBox(
                                  color: tint,
                                  child: const SizedBox.expand(),
                                ),
                              ),
                      ),
                    ],
                  )
                : _inputMode == _ScanInputMode.scanner
                    ? Center(
                        child: Text(
                          'Scanner ready — scan now',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.92),
                            fontSize: 18,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      )
                    : cam == null
                        ? const Center(child: CircularProgressIndicator(color: Colors.white54))
                        : Stack(
                        fit: StackFit.expand,
                        children: [
                          MobileScanner(controller: cam),
                          ValueListenableBuilder<Color?>(
                            valueListenable: _flash,
                            builder: (_, tint, __) => tint == null
                                ? const SizedBox.shrink()
                                : IgnorePointer(
                                    child: ColoredBox(
                                      color: tint,
                                      child: const SizedBox.expand(),
                                    ),
                                  ),
                          ),
                        ],
                      ),
          ),

          // ── Status card ──
          ColoredBox(
            color: Colors.black,
            child: ValueListenableBuilder<_ScanResult>(
              valueListenable: _result,
              builder: (_, res, __) {
                final Color textColor = res.ok == true
                    ? Colors.green.shade300
                    : res.ok == false
                        ? cs.error
                        : Colors.white70;
                return Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
                  child: Text(
                    res.message,
                    style: TextStyle(
                      color: textColor,
                      fontSize: 15,
                      fontWeight: res.ok != null ? FontWeight.w600 : FontWeight.normal,
                    ),
                  ),
                );
              },
            ),
          ),

          // ── Wedge hidden input — Offstage = no compositing layer, no render overhead ──
          Focus(
            focusNode: _wedgeFocus,
            onKeyEvent: (_, event) {
              if (event is KeyDownEvent &&
                  (event.logicalKey == LogicalKeyboardKey.enter ||
                   event.logicalKey == LogicalKeyboardKey.tab ||
                   event.logicalKey == LogicalKeyboardKey.numpadEnter)) {
                _flushWedge();
                return KeyEventResult.handled;
              }
              return KeyEventResult.ignored;
            },
            child: Offstage(
              offstage: true,
              child: TextField(
                controller: _wedge,
                focusNode: _wedgeFocus,
                enableSuggestions: false,
                autocorrect: false,
                onSubmitted: (_) => _flushWedge(),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
