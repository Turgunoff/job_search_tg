#!/usr/bin/env bash
# Mac yoqilganda skriptni avtomatik ishga tushirish (launchd).
# Avval bir marta qo'lda `python main.py --list` bilan login qiling!
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$DIR/venv/bin/python"
LABEL="uz.zettacode.jobfilter"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

[ -x "$PY" ] || { echo "❌ $PY topilmadi. README dagi o'rnatish qadamini bajaring."; exit 1; }
ls "$DIR"/*.session >/dev/null 2>&1 || { echo "❌ Session yo'q. Avval: $PY main.py --list"; exit 1; }
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
