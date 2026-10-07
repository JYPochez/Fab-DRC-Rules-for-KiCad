#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installs the Fab DRC Rules plugin for KiCad on Linux.
#   ./install_linux.sh               install for KiCad 10.0
#   ./install_linux.sh 9.0           install for another KiCad version
#   ./install_linux.sh --uninstall   remove it (add a version to pick one)
# Installs into the native KiCad folder, and into the Flatpak one when the
# Flatpak build (org.kicad.KiCad) is present.
set -euo pipefail

PLUGIN="fab_drc_rules"
VERSION="10.0"
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --uninstall) UNINSTALL=1 ;;
        -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
        *) VERSION="$arg" ;;
    esac
done

SOURCE="$(cd "$(dirname "$0")/.." && pwd)/$PLUGIN"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
TARGET_DIRS=("$DATA_HOME/kicad/$VERSION/scripting/plugins")
FLATPAK_DATA="$HOME/.var/app/org.kicad.KiCad/data"
if [ -d "$FLATPAK_DATA" ]; then
    TARGET_DIRS+=("$FLATPAK_DATA/kicad/$VERSION/scripting/plugins")
fi

install_into() {
    local target="$1/$PLUGIN" saved=""
    mkdir -p "$1"
    if [ -f "$target/settings.json" ]; then
        saved="$(mktemp)"; cp "$target/settings.json" "$saved"
    fi
    rm -rf "$target"
    mkdir -p "$target"
    # cp + cleanup rather than rsync, which is not installed everywhere.
    cp -R "$SOURCE/." "$target/"
    rm -rf "$target/__pycache__" "$target/settings.json" "$target/.DS_Store"
    if [ -n "$saved" ]; then mv "$saved" "$target/settings.json"; fi
    echo "Installed in $target"
}

if [ "$UNINSTALL" = 1 ]; then
    for dir in "${TARGET_DIRS[@]}"; do rm -rf "$dir/$PLUGIN"; echo "Removed $dir/$PLUGIN"; done
    exit 0
fi

[ -f "$SOURCE/__init__.py" ] || { echo "Plugin source not found: $SOURCE" >&2; exit 1; }
for dir in "${TARGET_DIRS[@]}"; do install_into "$dir"; done
echo "In the PCB editor: Tools > External Plugins > Refresh Plugins (or restart KiCad)."
