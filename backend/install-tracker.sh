#!/usr/bin/env bash
# Installs app_tracker.py as a launchd agent so it starts with login.
# Usage: ./install-tracker.sh           (install)
#        ./install-tracker.sh uninstall (remove)

set -e

PLIST_LABEL="com.cristopher.apptracker"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
BACKEND_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$BACKEND_DIR/venv/bin/python"
TRACKER_SCRIPT="$BACKEND_DIR/app_tracker.py"
LOG_DIR="$HOME/Library/Logs"

if [ "$1" = "uninstall" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "Tracker uninstalled."
    exit 0
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "Error: $PYTHON_BIN not found. Create venv first: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
    exit 1
fi

mkdir -p "$(dirname "$PLIST_PATH")" "$LOG_DIR"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$TRACKER_SCRIPT</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$BACKEND_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/cristopher-tracker.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/cristopher-tracker.err.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Tracker installed and running."
echo "  Plist: $PLIST_PATH"
echo "  Logs:  $LOG_DIR/cristopher-tracker.log"
echo ""
echo "IMPORTANT: grant Accessibility permission in"
echo "  System Settings -> Privacy & Security -> Accessibility"
echo "  Add: $PYTHON_BIN (otherwise window titles come back empty)"
