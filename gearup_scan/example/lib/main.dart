import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:gearup_scan/gearup_scan.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _kPrefBaseUrl = 'gearup_scan_base_url';
const _kPrefUsername = 'gearup_scan_username';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
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
      final client = GearupScanClient(baseUrl: origin);
      await client.login(username: _user.text.trim(), password: _pass.text);
      await _savePrefs();
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(builder: (_) => SessionListPage(client: client)),
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
              hintText: 'https://gear.telldb.com',
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
    if (!mounted) return;
    setState(() { _loading = true; _error = null; });
    try {
      final list = await widget.client.listStockTakeSessions();
      if (mounted) setState(() => _sessions = list);
    } on GearupScanException catch (e) {
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

  final GearupScanClient client;
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

class _ScanPageState extends State<ScanPage> {
  // ── Controller is nullable; assigned AFTER first frame to avoid ANR at widget construction ──
  MobileScannerController? _cam;
  StreamSubscription<BarcodeCapture>? _sub;

  final TextEditingController _wedge = TextEditingController();
  final FocusNode _wedgeFocus = FocusNode();
  final ValueNotifier<_ScanResult> _result = ValueNotifier(const _ScanResult());
  final ValueNotifier<Color?> _flash = ValueNotifier<Color?>(null);

  Timer? _idleTimer;
  Timer? _flashTimer;
  bool _busy = false;
  bool _alive = true;

  // ─────────── lifecycle ───────────

  @override
  void initState() {
    super.initState();
    _wedge.addListener(_onWedgeInput);
    // Defer camera creation so widget tree renders first — avoids UI-thread block (ANR).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_alive || !mounted) return;
      final cam = MobileScannerController(
        // noDuplicates: native fires only when a NEW barcode is seen.
        // This eliminates the need for timestamp throttling and keeps the stream quiet.
        detectionSpeed: DetectionSpeed.noDuplicates,
        facing: CameraFacing.back,
        // No cameraResolution: requesting unsupported sizes crashes some devices.
      );
      // Subscribe to the controller stream directly so we can pause/resume around HTTP.
      _sub = cam.barcodes.listen(_onBarcode, cancelOnError: false);
      setState(() => _cam = cam);
    });
  }

  @override
  void dispose() {
    _alive = false;
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

  // ─────────── barcode camera stream ───────────

  static String _raw(Barcode b) {
    final v = (b.rawValue ?? '').trim();
    return v.isNotEmpty ? v : (b.displayValue ?? '').trim();
  }

  void _onBarcode(BarcodeCapture cap) {
    if (_busy || !_alive) return;
    final raw = cap.barcodes.map(_raw).firstWhere((s) => s.isNotEmpty, orElse: () => '');
    if (raw.isEmpty) return;
    unawaited(_submit(raw));
  }

  // ─────────── wedge (USB / BT keyboard) ───────────

  void _onWedgeInput() {
    _idleTimer?.cancel();
    // Flush 300 ms after last character (no-suffix scanners).
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
    _sub?.pause(); // stop ML Kit events while HTTP round-trip is running
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
      if (_alive) {
        _busy = false;
        _sub?.resume();
      }
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
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        title: Text(widget.title),
        actions: [
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
            child: cam == null
                ? const Center(child: CircularProgressIndicator(color: Colors.white54))
                : Stack(
                    fit: StackFit.expand,
                    children: [
                      MobileScanner(controller: cam),
                      // Flash overlay — tiny widget, only its layer repaints
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
