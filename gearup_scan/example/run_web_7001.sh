#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Free TCP port 7001 (macOS/Linux)
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -ti tcp:7001 2>/dev/null || true)
  if [ -n "${PIDS:-}" ]; then
    echo "Stopping process(es) on port 7001: $PIDS"
    kill -9 $PIDS 2>/dev/null || true
    sleep 0.5
  else
    echo "Port 7001 is free."
  fi
fi

# Resolve Flutter (override with FLUTTER_BIN=/path/to/flutter)
FLUTTER_BIN="${FLUTTER_BIN:-}"
if [ -z "$FLUTTER_BIN" ]; then
  if command -v flutter >/dev/null 2>&1; then
    FLUTTER_BIN="$(command -v flutter)"
  elif [ -x "${HOME}/android/flutter/bin/flutter" ]; then
    FLUTTER_BIN="${HOME}/android/flutter/bin/flutter"
  elif [ -x "${HOME}/flutter/bin/flutter" ]; then
    FLUTTER_BIN="${HOME}/flutter/bin/flutter"
  fi
fi

if [ -z "$FLUTTER_BIN" ] || [ ! -x "$FLUTTER_BIN" ]; then
  echo "Flutter not found. Install it or set FLUTTER_BIN to your flutter executable." >&2
  exit 1
fi

echo "Using: $FLUTTER_BIN"
"$FLUTTER_BIN" pub get
exec "$FLUTTER_BIN" run -d chrome --web-port=7001
