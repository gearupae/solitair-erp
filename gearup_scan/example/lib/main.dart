import 'package:flutter/material.dart';
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

class _ScanPageState extends State<ScanPage> {
  final MobileScannerController _cam = MobileScannerController(
    detectionSpeed: DetectionSpeed.normal,
    facing: CameraFacing.back,
  );
  String _last = '—';
  String? _lastOk;
  DateTime _lastFire = DateTime.fromMillisecondsSinceEpoch(0);

  @override
  void dispose() {
    _cam.dispose();
    super.dispose();
  }

  Future<void> _onDetect(BarcodeCapture cap) async {
    final codes = cap.barcodes.where((b) => (b.rawValue ?? '').trim().isNotEmpty).toList();
    if (codes.isEmpty) return;
    final raw = codes.first.rawValue!.trim();
    final now = DateTime.now();
    if (now.difference(_lastFire) < const Duration(milliseconds: 900)) return;
    _lastFire = now;
    try {
      final r = await widget.client.submitScan(widget.sessionId, barcode: raw);
      if (!mounted) return;
      setState(() {
        if (r.ok && r.matched == true) {
          _lastOk = 'ok';
          _last = '${r.itemName ?? r.sku} · actual ${r.actualQty} (exp ${r.expectedQty})';
        } else if (r.ok && r.unknown == true) {
          _lastOk = 'bad';
          _last = 'Unknown: $raw';
        } else {
          _lastOk = 'bad';
          _last = r.error ?? 'Failed';
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _lastOk = 'bad';
        _last = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: Column(
        children: [
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: MobileScanner(controller: _cam, onDetect: _onDetect),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('Last scan', style: Theme.of(context).textTheme.labelSmall),
                const SizedBox(height: 4),
                Text(
                  _last,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: _lastOk == 'ok'
                            ? Colors.green.shade800
                            : _lastOk == 'bad'
                                ? Theme.of(context).colorScheme.error
                                : null,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
