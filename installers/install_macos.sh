#!/bin/bash
# Installs the Fab DRC Rules plugin for KiCad on macOS.
#   ./install_macos.sh               install for KiCad 10.0
#   ./install_macos.sh 9.0           install for another KiCad version
#   ./install_macos.sh --uninstall   remove it (add a version to pick one)
set -euo pipefail

PLUGIN="fab_drc_rules"
VERSION="10.0"
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --uninstall) UNINSTALL=1 ;;
        -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
        *) VERSION="$arg" ;;
    esac
done

SOURCE="$(cd "$(dirname "$0")/.." && pwd)/$PLUGIN"
TARGET_DIR="$HOME/Documents/KiCad/$VERSION/scripting/plugins"
TARGET="$TARGET_DIR/$PLUGIN"

if [ "$UNINSTALL" = 1 ]; then
    rm -rf "$TARGET"
    echo "Removed $TARGET"
    exit 0
fi

[ -f "$SOURCE/__init__.py" ] || { echo "Plugin source not found: $SOURCE" >&2; exit 1; }
mkdir -p "$TARGET_DIR"

# Keep the user's saved choices across updates.
SAVED=""
if [ -f "$TARGET/settings.json" ]; then
    SAVED="$(mktemp)"; cp "$TARGET/settings.json" "$SAVED"
fi
rm -rf "$TARGET"
mkdir -p "$TARGET"
rsync -a --exclude '__pycache__' --exclude '.DS_Store' --exclude 'settings.json' "$SOURCE/" "$TARGET/"
if [ -n "$SAVED" ]; then mv "$SAVED" "$TARGET/settings.json"; fi

echo "Installed in $TARGET"
echo "In the PCB editor: Tools > External Plugins > Refresh Plugins (or restart KiCad)."
