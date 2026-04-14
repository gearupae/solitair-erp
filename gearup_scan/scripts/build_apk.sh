#!/usr/bin/env bash
# Build a release APK locally.
# - Prefer Flutter on PATH, or set FLUTTER_ROOT to the SDK root (directory that contains bin/flutter).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/example"

if [[ -n "${FLUTTER_ROOT:-}" && -x "${FLUTTER_ROOT}/bin/flutter" ]]; then
  export PATH="${FLUTTER_ROOT}/bin:${PATH}"
fi

if ! command -v flutter >/dev/null 2>&1; then
  echo "Flutter is not installed or not on PATH."
  echo "Set FLUTTER_ROOT to your SDK (folder containing bin/flutter), or install Flutter:"
  echo "  https://docs.flutter.dev/get-started/install"
  echo "Or run:  bash \"${ROOT}/scripts/download_flutter_sdk_macos_arm64.sh\""
  echo "Or use GitHub Actions: 'Build Gearup Scan APK' → download artifact gearup-scan-apk."
  exit 1
fi

if [[ ! -f android/app/build.gradle ]]; then
  echo "Generating Android/iOS folders..."
  flutter create . --project-name gearup_scan_example --org com.gearup
fi

flutter pub get

MAN=android/app/src/main/AndroidManifest.xml
if ! grep -q 'usesCleartextTraffic' "$MAN" 2>/dev/null; then
  if [[ "$(uname)" == Darwin ]]; then
    sed -i '' 's/<application/<application android:usesCleartextTraffic="true" /' "$MAN"
  else
    sed -i 's/<application/<application android:usesCleartextTraffic="true" /' "$MAN"
  fi
fi

flutter build apk --release
APK="$ROOT/example/build/app/outputs/flutter-apk/app-release.apk"
echo "Built: $APK"
ls -la "$APK"
