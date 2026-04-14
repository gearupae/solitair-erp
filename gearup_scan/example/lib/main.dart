import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:gearup_scan/gearup_scan.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _kPrefBaseUrl = 'gearup_scan_base_url';
const _kPrefUsername = 'gearup_scan_username';

void main() {
  runApp(const GearupScanExampleApp());
}

class GearupScanExampleApp extends StatelessWidget {
  const GearupScanExampleApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Gearup Scan',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal),
        useMaterial3: true,
      ),
      home: const LoginPage(),
    );
  }
}

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
      setState(() => _error = 'Enter your ERP server URL (same network as this phone).');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final client = GearupScanClient(baseUrl: origin);
      await client.login(username: _user.text.trim(), password: _pass.text);
      await _savePrefs();
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => SessionListPage(client: client),
        ),
      );
    } on GearupScanException catch (e) {
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
      appBar: AppBar(title: const Text('Gearup — scan')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text(
            'Sign in with your ERP username and password. Use your computer\'s LAN address so this phone can reach the server (not localhost).',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 20),
          TextField(
            controller: _base,
            decoration: const InputDecoration(
              labelText: 'ERP server URL',
              hintText: 'http://192.168.1.10:8000',
              helperText: 'Android emulator: http://10.0.2.2:PORT',
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

class SessionListPage extends StatefulWidget {
  const SessionListPage({super.key, required this.client});

  final GearupScanClient client;

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
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final list = await widget.client.listStockTakeSessions();
      setState(() => _sessions = list);
    } on GearupScanException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _logout() async {
    await widget.client.logout();
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
                          subtitle: Text('${s.location} · ${s.sessionDate} · ${_sessionLines(s.lineCount)}'),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () {
                            Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) =>
                                    ScanPage(client: widget.client, sessionId: s.id, title: s.clientName),
                              ),
                            );
                          },
                        );
                      },
                    ),
    );
  }

  static String _sessionLines(int n) => n == 1 ? '1 line' : '$n lines';
}

class ScanPage extends StatefulWidget {
  const ScanPage({super.key, required this.client, required this.sessionId, required this.title});

  final GearupScanClient client;
  final int sessionId;
  final String title;

  @override
  State<ScanPage> createState() => _ScanPageState();
}

/// Last line shown under the camera — kept outside [setState] so the camera widget is not rebuilt every scan.
class _ScanFooter {
  const _ScanFooter({this.message = '—', this.ok});
  final String message;
  /// `'ok'` | `'bad'` | neutral
  final String? ok;
}

class _ScanPageState extends State<ScanPage> {
  /// Lighter preview + longer gap between ML Kit passes (Android is sensitive to camera + JS thread load).
  final MobileScannerController _cam = MobileScannerController(
    detectionSpeed: DetectionSpeed.normal,
    detectionTimeoutMs: 1200,
    facing: CameraFacing.back,
    cameraResolution: const Size(640, 480),
  );

  final TextEditingController _wedge = TextEditingController();
  final FocusNode _wedgeFocus = FocusNode();
  final ValueNotifier<_ScanFooter> _footer = ValueNotifier(const _ScanFooter());
  /// Brief green/red tint over the preview (success = green, no sound; failure = red + sound).
  final ValueNotifier<Color?> _pulseOverlay = ValueNotifier<Color?>(null);
  Timer? _wedgeIdle;
  Timer? _pulseTimer;

  /// Drop camera callbacks while a network round-trip is in progress (avoids piling work on the UI isolate).
  bool _scanBusy = false;

  /// Throttle duplicate camera frame reads of the same barcode.
  DateTime _lastCameraFire = DateTime.fromMillisecondsSinceEpoch(0);

  static const _wedgeIdleFlush = Duration(milliseconds: 320);

  bool _alive = true;

  void _pulseSuccess() {
    if (!_alive || !mounted) return;
    _pulseTimer?.cancel();
    _pulseOverlay.value = Colors.green.withValues(alpha: 0.38);
    _pulseTimer = Timer(const Duration(milliseconds: 400), () {
      if (_alive && mounted) _pulseOverlay.value = null;
    });
  }

  void _pulseNegative() {
    if (!_alive || !mounted) return;
    _pulseTimer?.cancel();
    _pulseOverlay.value = Colors.red.withValues(alpha: 0.48);
    scheduleMicrotask(() {
      if (!_alive || !mounted) return;
      try {
        SystemSound.play(SystemSoundType.alert);
      } catch (_) {}
      try {
        HapticFeedback.heavyImpact();
      } catch (_) {}
    });
    _pulseTimer = Timer(const Duration(milliseconds: 520), () {
      if (_alive && mounted) _pulseOverlay.value = null;
    });
  }

  @override
  void initState() {
    super.initState();
    _wedge.addListener(_scheduleWedgeIdleFlush);
  }

  void _scheduleWedgeIdleFlush() {
    _wedgeIdle?.cancel();
    _wedgeIdle = Timer(_wedgeIdleFlush, _flushWedgeIfNonEmpty);
  }

  void _flushWedgeIfNonEmpty() {
    _wedgeIdle?.cancel();
    _wedgeIdle = null;
    final raw = _wedge.text.trim();
    _wedge.clear();
    if (raw.isEmpty) return;
    unawaited(_pushScan(raw));
  }

  Future<void> _pushScan(String raw) async {
    if (_scanBusy || !_alive) return;
    _scanBusy = true;
    try {
      final r = await widget.client.submitScan(widget.sessionId, barcode: raw);
      if (!_alive || !mounted) return;
      if (r.ok && r.matched == true) {
        _footer.value = _ScanFooter(
          ok: 'ok',
          message: '${r.itemName ?? r.sku} · actual ${r.actualQty} (exp ${r.expectedQty})',
        );
        _pulseSuccess();
      } else if (r.ok && r.unknown == true) {
        _footer.value = _ScanFooter(ok: 'bad', message: 'Unknown: $raw');
        _pulseNegative();
      } else {
        _footer.value = _ScanFooter(ok: 'bad', message: r.error ?? 'Failed');
        _pulseNegative();
      }
    } catch (e) {
      if (!_alive || !mounted) return;
      _footer.value = _ScanFooter(ok: 'bad', message: e.toString());
      _pulseNegative();
    } finally {
      if (_alive) _scanBusy = false;
    }
  }

  @override
  void dispose() {
    _alive = false;
    _pulseTimer?.cancel();
    _wedgeIdle?.cancel();
    _wedge.removeListener(_scheduleWedgeIdleFlush);
    _wedge.dispose();
    _wedgeFocus.dispose();
    _cam.dispose();
    _footer.dispose();
    _pulseOverlay.dispose();
    super.dispose();
  }

  static String _barcodeText(Barcode b) {
    final a = (b.rawValue ?? '').trim();
    if (a.isNotEmpty) return a;
    return (b.displayValue ?? '').trim();
  }

  /// Sync handler for the barcode stream — return immediately; defer work to a microtask.
  void _onDetect(BarcodeCapture cap) {
    if (_scanBusy || !_alive) return;
    final codes = cap.barcodes.where((b) => _barcodeText(b).isNotEmpty).toList();
    if (codes.isEmpty) return;
    final raw = _barcodeText(codes.first);
    if (raw.isEmpty) return;
    final now = DateTime.now();
    if (now.difference(_lastCameraFire) < const Duration(milliseconds: 900)) return;
    _lastCameraFire = now;
    unawaited(Future.microtask(() => _pushScan(raw)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          IconButton(
            tooltip: 'Focus USB / Bluetooth scanner',
            onPressed: () => _wedgeFocus.requestFocus(),
            icon: const Icon(Icons.keyboard_alt_outlined),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text(
              'Camera: common 1D and 2D codes. USB or Bluetooth scanners: tap the keyboard icon, '
              'then scan (works like the ERP web page — each scan adds one to the matched line).',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: RepaintBoundary(
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      MobileScanner(controller: _cam, onDetect: _onDetect),
                      ValueListenableBuilder<Color?>(
                        valueListenable: _pulseOverlay,
                        builder: (context, tint, _) {
                          if (tint == null) return const SizedBox.shrink();
                          return IgnorePointer(
                            child: DecoratedBox(
                              decoration: BoxDecoration(color: tint),
                              child: const SizedBox.expand(),
                            ),
                          );
                        },
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          // Captures HID “keyboard wedge” scanners (same behavior as ERP web hidden field).
          Focus(
            focusNode: _wedgeFocus,
            onKeyEvent: (node, event) {
              if (event is! KeyDownEvent) return KeyEventResult.ignored;
              if (event.logicalKey == LogicalKeyboardKey.tab) {
                _flushWedgeIfNonEmpty();
                return KeyEventResult.handled;
              }
              return KeyEventResult.ignored;
            },
            child: Opacity(
              opacity: 0.01,
              child: SizedBox(
                height: 1,
                child: TextField(
                  controller: _wedge,
                  focusNode: _wedgeFocus,
                  maxLines: 1,
                  keyboardType: TextInputType.visiblePassword,
                  enableSuggestions: false,
                  autocorrect: false,
                  textInputAction: TextInputAction.done,
                  decoration: const InputDecoration.collapsed(hintText: ''),
                  style: const TextStyle(height: 0.01, fontSize: 1),
                  onSubmitted: (_) => _flushWedgeIfNonEmpty(),
                ),
              ),
            ),
          ),
          ValueListenableBuilder<_ScanFooter>(
            valueListenable: _footer,
            builder: (context, fb, _) {
              return Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text('Last scan', style: Theme.of(context).textTheme.labelSmall),
                    const SizedBox(height: 4),
                    Text(
                      fb.message,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            color: fb.ok == 'ok'
                                ? Colors.green.shade800
                                : fb.ok == 'bad'
                                    ? Theme.of(context).colorScheme.error
                                    : null,
                          ),
                    ),
                  ],
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}
