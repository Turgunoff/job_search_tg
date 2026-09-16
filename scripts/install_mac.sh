#!/usr/bin/env bash
# Mac yoqilganda skriptni avtomatik ishga tushirish (launchd).
# Login kerak emas — avval .env da CHANNELS va BOT_TOKEN ni to'ldiring.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$DIR/venv/bin/python"
LABEL="uz.zettacode.jobfilter"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

[ -x "$PY" ] || { echo "❌ $PY topilmadi. README dagi o'rnatish qadamini bajaring."; exit 1; }
[ -f "$DIR/.env" ] || { echo "❌ .env yo'q. cp .env.example .env qiling."; exit 1; }
mkdir -p "$DIR/logs" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/main.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$DIR/logs/out.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/err.log</string>
</dict></plist>
PL

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "✅ Ishga tushdi. Loglar: tail -f $DIR/logs/err.log"
echo "   To'xtatish: launchctl bootout gui/$(id -u)/$LABEL"
