class ScanUser {
  ScanUser({required this.id, required this.username});

  final int id;
  final String username;

  factory ScanUser.fromJson(Map<String, dynamic> j) {
    return ScanUser(
      id: j['id'] as int,
      username: j['username'] as String,
    );
  }
}

class StockTakeSessionSummary {
  StockTakeSessionSummary({
    required this.id,
    required this.clientName,
    required this.location,
    required this.sessionDate,
    required this.status,
    required this.lineCount,
  });

  final int id;
  final String clientName;
  final String location;
  final String sessionDate;
  final String status;
  final int lineCount;

  factory StockTakeSessionSummary.fromJson(Map<String, dynamic> j) {
    return StockTakeSessionSummary(
      id: j['id'] as int,
      clientName: j['client_name'] as String,
      location: j['location'] as String,
      sessionDate: j['session_date'] as String,
      status: j['status'] as String,
      lineCount: j['line_count'] as int,
    );
  }
}

class StockTakeLine {
  StockTakeLine({
    required this.sku,
    required this.scanCode,
    required this.itemName,
    required this.expectedQty,
    required this.actualQty,
  });

  final String sku;
  final String scanCode;
  final String itemName;
  final String expectedQty;
  final String actualQty;

  factory StockTakeLine.fromJson(Map<String, dynamic> j) {
    return StockTakeLine(
      sku: j['sku']?.toString() ?? '',
      scanCode: j['scan_code']?.toString() ?? '',
      itemName: j['item_name']?.toString() ?? '',
      expectedQty: '${j['expected_qty'] ?? 0}',
      actualQty: '${j['actual_qty'] ?? 0}',
    );
  }
}

class StockTakeSessionDetail {
  StockTakeSessionDetail({
    required this.id,
    required this.clientName,
    required this.location,
    required this.sessionDate,
    required this.status,
    required this.unknownScanCount,
    required this.lines,
    required this.canScan,
  });

  final int id;
  final String clientName;
  final String location;
  final String sessionDate;
  final String status;
  final int unknownScanCount;
  final List<StockTakeLine> lines;
  final bool canScan;

  factory StockTakeSessionDetail.fromJson(Map<String, dynamic> j) {
    final s = j['session'] as Map<String, dynamic>;
    final rawLines = j['lines'] as List<dynamic>? ?? [];
    return StockTakeSessionDetail(
      id: s['id'] as int,
      clientName: s['client_name'] as String,
      location: s['location'] as String,
      sessionDate: s['session_date'] as String,
      status: s['status'] as String,
      unknownScanCount: s['unknown_scan_count'] as int,
      lines: rawLines
          .map((e) => StockTakeLine.fromJson(e as Map<String, dynamic>))
          .toList(),
      canScan: j['can_scan'] as bool? ?? false,
    );
  }
}

/// Response from [AlnajahScanClient.scanBarcode] / manual set (mirrors Django JSON).
class ScanSubmitResult {
  ScanSubmitResult({
    required this.ok,
    this.matched,
    this.unknown,
    this.sku,
    this.itemName,
    this.expectedQty,
    this.actualQty,
    this.error,
  });

  final bool ok;
  final bool? matched;
  final bool? unknown;
  final String? sku;
  final String? itemName;
  final String? expectedQty;
  final String? actualQty;
  final String? error;

  factory ScanSubmitResult.fromJson(Map<String, dynamic> j) {
    return ScanSubmitResult(
      ok: j['ok'] as bool? ?? false,
      matched: j['matched'] as bool?,
      unknown: j['unknown'] as bool?,
      sku: j['sku'] as String?,
      itemName: j['item_name'] as String?,
      expectedQty: j['expected_qty']?.toString(),
      actualQty: j['actual_qty']?.toString(),
      error: j['error'] as String?,
    );
  }
}
