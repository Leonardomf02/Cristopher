#!/usr/bin/env bash
# Builds a CristopherTracker.app bundle that runs app_tracker.py in background.
# The .app can be added to Accessibility (System Settings) and Login Items.

set -e

BACKEND_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$HOME/Applications/CristopherTracker.app"
PYTHON_BIN="$BACKEND_DIR/venv/bin/python"
TRACKER_SCRIPT="$BACKEND_DIR/app_tracker.py"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "Error: $PYTHON_BIN not found. Create venv first."
    exit 1
fi

mkdir -p "$HOME/Applications"
rm -rf "$APP_PATH"

TMP_SCRIPT="$(mktemp -t cristopher_tracker).applescript"
cat > "$TMP_SCRIPT" <<APPLESCRIPT
on run
    do shell script "nohup $PYTHON_BIN $TRACKER_SCRIPT >> \$HOME/Library/Logs/cristopher-tracker.log 2>&1 &"
end run
APPLESCRIPT

osacompile -o "$APP_PATH" "$TMP_SCRIPT"
rm -f "$TMP_SCRIPT"

# Mark as stay-open-less; we just want the shell command to fire and release.
echo "Built: $APP_PATH"
echo ""
echo "Next steps:"
echo "  1. Open System Settings -> Privacy & Security -> Accessibility"
echo "     Click +  ->  navigate to ~/Applications  ->  select CristopherTracker.app"
echo "     Toggle it ON"
echo "  2. System Settings -> General -> Login Items -> Open at Login"
echo "     Click +  ->  select CristopherTracker.app"
echo "  3. Double-click CristopherTracker.app once to start it now"
