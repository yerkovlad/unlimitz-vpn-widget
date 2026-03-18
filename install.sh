#!/usr/bin/env bash
# install.sh — One-shot installer for Unlimitz VPN Widget
set -e

CONFIG_DIR="$HOME/.config/unlimitz-vpn"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$HOME/.config/systemd/user"

echo ""
echo "╔══════════════════════════════════╗"
echo "║    Unlimitz VPN Widget — Setup   ║"
echo "╚══════════════════════════════════╝"
echo ""

# ── Check dependencies ──────────────────────────────────────────────────────
check_dep() {
    if ! command -v "$1" &>/dev/null; then
        echo "  ✗ Missing: $1  ($2)"
        MISSING=1
    else
        echo "  ✓ $1"
    fi
}

echo "Checking dependencies..."
MISSING=0
check_dep python3      "pacman -S python"
check_dep xray         "pacman -S xray  (or yay -S xray)"
check_dep socat        "pacman -S socat"
check_dep curl         "pacman -S curl"
check_dep ping         "pacman -S iputils"
python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')" 2>/dev/null \
    && echo "  ✓ python-gobject / libadwaita" \
    || { echo "  ✗ Missing: python-gobject / libadwaita  (pacman -S python-gobject libadwaita)"; MISSING=1; }

if [[ $MISSING -eq 1 ]]; then
    echo ""
    echo "Install missing dependencies first, then re-run install.sh"
    exit 1
fi

echo ""

# ── Create directories ───────────────────────────────────────────────────────
echo "Creating config directory..."
mkdir -p "$CONFIG_DIR/configs"
mkdir -p "$SERVICE_DIR"

# ── Copy scripts ─────────────────────────────────────────────────────────────
echo "Copying scripts..."
cp "$SCRIPT_DIR/vpn-daemon.py"   "$CONFIG_DIR/"
cp "$SCRIPT_DIR/vpn-widget.py"   "$CONFIG_DIR/"
cp "$SCRIPT_DIR/waybar-vpn.sh"   "$CONFIG_DIR/"
chmod +x "$CONFIG_DIR/waybar-vpn.sh"

# servers.json — don't overwrite if already exists
if [[ ! -f "$CONFIG_DIR/servers.json" ]]; then
    cp "$SCRIPT_DIR/servers.json" "$CONFIG_DIR/"
    echo "  Created servers.json — edit it with your server details"
else
    echo "  Kept existing servers.json"
fi

# ── Systemd service ───────────────────────────────────────────────────────────
echo "Installing systemd user service..."
cp "$SCRIPT_DIR/unlimitz-vpn.service" "$SERVICE_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now unlimitz-vpn.service
echo "  Service started!"

# ── Print next steps ──────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                        Next steps                           ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              ║"
echo "║  1. Add your VLESS xray configs:                            ║"
echo "║       $CONFIG_DIR/configs/nl.json"
echo "║       $CONFIG_DIR/configs/se.json  etc."
echo "║     (see configs/nl.json.example for format)                ║"
echo "║                                                              ║"
echo "║  2. Edit servers.json with correct hosts/UUIDs:             ║"
echo "║       $CONFIG_DIR/servers.json"
echo "║                                                              ║"
echo "║  3. Add to hyprland.conf:                                   ║"
echo "║       bind = \$mainMod, V, exec, python3 $CONFIG_DIR/vpn-widget.py"
echo "║       windowrule = float, class:com.unlimitz.vpn            ║"
echo "║       windowrule = center, class:com.unlimitz.vpn           ║"
echo "║                                                              ║"
echo "║  4. Add to waybar config (see waybar-example.jsonc)         ║"
echo "║                                                              ║"
echo "║  Check daemon logs:                                          ║"
echo "║       journalctl --user -u unlimitz-vpn -f                  ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
