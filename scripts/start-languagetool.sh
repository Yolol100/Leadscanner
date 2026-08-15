#!/usr/bin/env bash
set -euo pipefail

LT_BASE="${RUNNER_TEMP:-/tmp}/webactueel-languagetool"
ZIP="$LT_BASE/LanguageTool-latest-snapshot.zip"
mkdir -p "$LT_BASE"
rm -rf "$LT_BASE"/LanguageTool-* "$ZIP"

curl -fsSL https://languagetool.org/download/LanguageTool-latest-snapshot.zip -o "$ZIP"
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
  if curl -fsS http://127.0.0.1:8010/v2/languages >/dev/null; then
    echo 'LanguageTool lokaal gestart op 127.0.0.1:8010.'
    exit 0
  fi
  sleep 2
done
cat "$LT_BASE/server.log" >&2 || true
echo 'LanguageTool startte niet op tijd.' >&2
exit 1
