#!/usr/bin/env bash
set -euo pipefail

LT_BASE="${RUNNER_TEMP:-/tmp}/webactueel-languagetool"
LT_URL="${LANGUAGETOOL_ARCHIVE_URL:-https://languagetool.org/download/LanguageTool-6.6.zip}"
LT_SHA256="${LANGUAGETOOL_ARCHIVE_SHA256:-53600506b399bb5ffe1e4c8dec794fd378212f14aaf38ccef9b6f89314d11631}"
LT_NAME="$(basename "$LT_URL")"

mkdir -p "$LT_BASE"
rm -rf "$LT_BASE"/LanguageTool-* "$LT_BASE"/*.zip
ZIP="$LT_BASE/$LT_NAME"

curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$LT_URL" -o "$ZIP"
printf '%s  %s\n' "$LT_SHA256" "$ZIP" | sha256sum -c -
unzip -q "$ZIP" -d "$LT_BASE"
ROOT="$(find "$LT_BASE" -maxdepth 1 -type d -name 'LanguageTool-*' | head -n 1)"
if [ -z "$ROOT" ]; then
  echo 'LanguageTool map niet gevonden.' >&2
  exit 1
fi

: > "$ROOT/server.properties"
nohup java -Xms128m -Xmx512m -cp "$ROOT/languagetool-server.jar" org.languagetool.server.HTTPServer \
  --config "$ROOT/server.properties" --port 8010 > "$LT_BASE/server.log" 2>&1 &

echo $! > "$LT_BASE/server.pid"
for _ in $(seq 1 45); do
  if curl --fail --silent --show-error http://127.0.0.1:8010/v2/languages >/dev/null; then
    echo "LanguageTool vastgepind archief $LT_NAME lokaal gestart; SHA-256 geverifieerd."
    exit 0
  fi
  sleep 2
done
cat "$LT_BASE/server.log" >&2 || true
echo 'LanguageTool startte niet op tijd.' >&2
exit 1
