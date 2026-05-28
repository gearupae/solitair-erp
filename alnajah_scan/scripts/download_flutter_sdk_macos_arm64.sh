#!/usr/bin/env bash
# Download (resume-capable) official Flutter macOS ARM64 stable SDK for local APK builds.
# Needs several GB free during download+unzip; after success you can delete the .zip.
#
# Usage:
#   bash scripts/download_flutter_sdk_macos_arm64.sh
#   export FLUTTER_ROOT="$HOME/flutter_sdk_arm64/flutter"
#   bash scripts/build_apk.sh
set -euo pipefail

URL="${FLUTTER_SDK_URL:-https://storage.googleapis.com/flutter_infra_release/releases/stable/macos/flutter_macos_arm64_3.41.6-stable.zip}"
ZIP="${FLUTTER_SDK_ZIP:-$HOME/flutter_macos_arm64_stable.zip}"
DEST_PARENT="${FLUTTER_SDK_PARENT:-$HOME}"
DEST_SDK="$DEST_PARENT/flutter_sdk_arm64"

echo "ZIP=$ZIP"
echo "DEST_PARENT=$DEST_PARENT (creates $DEST_SDK/flutter/)"
mkdir -p "$DEST_PARENT"

if [[ -d "$DEST_SDK/flutter" && -x "$DEST_SDK/flutter/bin/flutter" ]]; then
  echo "Already present: $DEST_SDK/flutter/bin/flutter"
  exit 0
fi

echo "Downloading (curl -C - resumes partial files)..."
curl -fL --connect-timeout 30 --retry 3 --retry-delay 5 -C - -o "$ZIP" "$URL"

echo "Unpacking..."
rm -rf "$DEST_SDK"
mkdir -p "$DEST_SDK"
unzip -q "$ZIP" -d "$DEST_SDK"

if [[ ! -x "$DEST_SDK/flutter/bin/flutter" ]]; then
  echo "Expected $DEST_SDK/flutter/bin/flutter after unzip — archive layout may have changed."
  exit 1
fi

echo "Done."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "export FLUTTER_ROOT=\"$DEST_SDK/flutter\""
echo "Then: bash \"$SCRIPT_DIR/build_apk.sh\""
