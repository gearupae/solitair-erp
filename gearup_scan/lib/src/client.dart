import 'package:cookie_jar/cookie_jar.dart';
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';

import 'models.dart';

class MeResponse {
  MeResponse(this.user, this.canInventoryScan);
  final ScanUser user;
  final bool canInventoryScan;
}

/// HTTP client for `/api/scan/v1/` — uses Django **session** cookies (same login as web).
class GearupScanClient {
  GearupScanClient({
    required String baseUrl,
    CookieJar? cookieJar,
    Dio? dio,
  })  : _origin = _normalizeOrigin(baseUrl),
        _jar = cookieJar ?? CookieJar(),
        _dio = dio ?? Dio() {
    _dio.options.connectTimeout = const Duration(seconds: 30);
    _dio.options.receiveTimeout = const Duration(seconds: 30);
    _dio.options.validateStatus = (s) => s != null && s < 500;
    _dio.interceptors.add(CookieManager(_jar));
  }

  final String _origin;
  final CookieJar _jar;
  final Dio _dio;

  static String _normalizeOrigin(String u) {
    var s = u.trim();
    if (s.endsWith('/')) {
      s = s.substring(0, s.length - 1);
    }
    return s;
  }

  String _u(String path) => '$_origin/api/scan/v1$path';

  /// Login with ERP username/password. Stores session cookie for subsequent calls.
  Future<ScanUser> login({required String username, required String password}) async {
    final r = await _dio.post<Map<String, dynamic>>(
      _u('/auth/login/'),
      data: {'username': username, 'password': password},
      options: Options(contentType: Headers.jsonContentType),
    );
    final data = r.data ?? {};
    if (data['ok'] != true) {
      throw GearupScanException(data['error']?.toString() ?? 'Login failed', r.statusCode);
    }
    final u = data['user'] as Map<String, dynamic>?;
    if (u == null) {
      throw GearupScanException('Invalid login response', r.statusCode);
    }
    return ScanUser.fromJson(u);
  }

  Future<void> logout() async {
    await _dio.post<Map<String, dynamic>>(
      _u('/auth/logout/'),
      data: const {},
      options: Options(contentType: Headers.jsonContentType),
    );
  }

  Future<MeResponse> me() async {
    final r = await _dio.get<Map<String, dynamic>>(_u('/auth/me/'));
    final data = r.data ?? {};
    if (data['ok'] != true) {
      throw GearupScanException(data['error']?.toString() ?? 'Not authenticated', r.statusCode);
    }
    final u = ScanUser.fromJson(data['user'] as Map<String, dynamic>);
    final can = data['can_inventory_scan'] as bool? ?? false;
    return MeResponse(u, can);
  }

  Future<List<StockTakeSessionSummary>> listStockTakeSessions() async {
    final r = await _dio.get<Map<String, dynamic>>(_u('/stock-take/sessions/'));
    final data = r.data ?? {};
    if (data['ok'] != true) {
      throw GearupScanException(data['error']?.toString() ?? 'Request failed', r.statusCode);
    }
    final list = data['sessions'] as List<dynamic>? ?? [];
    return list
        .map((e) => StockTakeSessionSummary.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<StockTakeSessionDetail> getStockTakeSession(int pk) async {
    final r = await _dio.get<Map<String, dynamic>>(_u('/stock-take/sessions/$pk/'));
    final data = r.data ?? {};
    if (data['ok'] != true) {
      throw GearupScanException(data['error']?.toString() ?? 'Request failed', r.statusCode);
    }
    return StockTakeSessionDetail.fromJson(data);
  }

  /// Increment count for a scanned barcode / scan code, or manual set via [sku] + [setActual].
  Future<ScanSubmitResult> submitScan(
    int sessionId, {
    String? barcode,
    String? sku,
    String? setActual,
  }) async {
    final hasBarcode = barcode != null && barcode.trim().isNotEmpty;
    final hasManual = sku != null &&
        sku.trim().isNotEmpty &&
        setActual != null &&
        setActual.toString().trim().isNotEmpty;
    if (!hasBarcode && !hasManual) {
      throw ArgumentError('Provide a non-empty barcode, or sku with set_actual.');
    }
    final body = <String, dynamic>{};
    if (hasBarcode) {
      body['barcode'] = barcode!.trim();
    } else {
      body['sku'] = sku!.trim();
      body['set_actual'] = setActual;
    }
    final r = await _dio.post<Map<String, dynamic>>(
      _u('/stock-take/sessions/$sessionId/scan/'),
      data: body,
      options: Options(contentType: Headers.jsonContentType),
    );
    final data = r.data ?? {};
    return ScanSubmitResult.fromJson(data);
  }
}

class GearupScanException implements Exception {
  GearupScanException(this.message, this.statusCode);
  final String message;
  final int? statusCode;

  @override
  String toString() => 'GearupScanException($statusCode): $message';
}
