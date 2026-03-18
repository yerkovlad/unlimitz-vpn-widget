# 🛡 Unlimitz VPN Widget

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/PyQt6-6.0+-41CD52?style=for-the-badge&logo=qt&logoColor=white)
![xray-core](https://img.shields.io/badge/xray--core-VLESS-FF6B6B?style=for-the-badge)
![KDE](https://img.shields.io/badge/KDE-Plasma-1D99F3?style=for-the-badge&logo=kde&logoColor=white)
![Arch Linux](https://img.shields.io/badge/Arch_Linux-1793D1?style=for-the-badge&logo=arch-linux&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**A native KDE system tray VPN client for VLESS + Reality protocol.**  
Built from scratch as an alternative to nekoray — lightweight, no Electron, no Qt5 bloat.

</div>

---

## ✨ Features

- 🔒 **Full TUN mode** — all traffic routed through VPN (not just browser proxy)
- 🖥 **Native KDE system tray** — lives in your taskbar, click to show/hide
- ⚡ **Real-time stats** — upload/download speed, ping, public IP, country
- 🌍 **Multi-server** — switch between servers with one click
- 🔗 **Import via links** — paste `vless://` links or subscription URLs
- ✏️ **Server editor** — rename, change flag, edit host directly in the UI
- 🔄 **Auto-reconnect** — detects crashes and reconnects automatically
- 🚀 **Autostart** — optionally launch with KDE session
- 🎨 **Clean dark UI** — minimal design, no bloat

---

## 📸 Screenshots

> Widget in system tray, server selection, connection info panel

---

## 🏗 Architecture

```
┌─────────────────────┐       Unix Socket        ┌──────────────────────┐
│   vpn-widget.py     │ ◄──────────────────────► │   vpn-daemon.py      │
│   PyQt6 UI          │    JSON IPC commands      │   asyncio background │
│   System tray       │                           │   xray + tun2socks   │
└─────────────────────┘                           └──────────────────────┘
                                                           │
                                              ┌────────────▼────────────┐
                                              │   xray-core (VLESS)     │
                                              │   SOCKS5 :10808         │
                                              └────────────┬────────────┘
                                                           │
                                              ┌────────────▼────────────┐
                                              │   tun2socks             │
                                              │   tun0 interface        │
                                              │   All traffic → VPN     │
                                              └─────────────────────────┘
```

---

## 📦 Requirements

| Package | Install |
|--------|---------|
| `xray` | `yay -S xray` |
| `tun2socks` | `yay -S tun2socks-bin` |
| `python 3.11+` | `pacman -S python` |
| `PyQt6` | `pip install PyQt6` |
| `socat` | `pacman -S socat` |
| `curl` | `pacman -S curl` |

---

## 🚀 Installation

```bash
# 1. Clone
git clone https://github.com/yourusername/unlimitz-vpn-widget
cd unlimitz-vpn-widget

# 2. Create venv and install deps
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install PyQt6

# 3. Install system dependencies
sudo pacman -S socat curl iputils
yay -S xray tun2socks-bin

# 4. Run installer
bash install.sh
```

---

## ⚙️ Sudoers Setup

The daemon needs to manage TUN interface and routes without password prompts:

```bash
sudo cp unlimitz-vpn-sudoers /etc/sudoers.d/unlimitz-vpn
sudo sed -i 's/YOUR_USERNAME/yourusername/g' /etc/sudoers.d/unlimitz-vpn
sudo chmod 440 /etc/sudoers.d/unlimitz-vpn
```

---

## 🔧 Configuration

### Adding servers

**Option 1 — In the widget:**  
Click `+` → paste your `vless://` link or subscription URL

**Option 2 — CLI:**
```bash
python3 ~/.config/unlimitz-vpn/link_parser.py "vless://uuid@host:443?security=reality&..."

# Or full subscription
python3 ~/.config/unlimitz-vpn/link_parser.py "https://your-sub-url/sub/token"
```

**Option 3 — Manual:**  
Edit `~/.config/unlimitz-vpn/servers.json` and place xray configs in `~/.config/unlimitz-vpn/configs/`

### VLESS link format

```
vless://UUID@host:port?security=reality&pbk=PUBLIC_KEY&sid=SHORT_ID&sni=SNI&fp=chrome&flow=xtls-rprx-vision#Server Name
```

---

## 📁 File Structure

```
~/.config/unlimitz-vpn/
├── vpn-daemon.py          # Background daemon (systemd user service)
├── vpn-widget.py          # PyQt6 tray application
├── link_parser.py         # vless:// and subscription parser
├── servers.json           # Server list
├── widget-settings.json   # Widget settings (autostart, port, etc.)
└── configs/
    ├── nl.json            # xray config for Netherlands server
    ├── se.json            # xray config for Sweden server
    └── ...
```

---

## 🔌 IPC Protocol

The widget communicates with the daemon via Unix socket at `/tmp/vpn-daemon.sock`:

```json
// Get status
{"cmd": "status"}

// Connect to server
{"cmd": "connect", "server": "nl"}

// Disconnect
{"cmd": "disconnect"}
```

---

## 🛠 Systemd Service

```bash
# Status
systemctl --user status unlimitz-vpn

# Logs
journalctl --user -u unlimitz-vpn -f

# Restart
systemctl --user restart unlimitz-vpn
```

---

## 🔄 How TUN mode works

1. **xray** starts and listens on `127.0.0.1:10808` (SOCKS5)
2. A **tun0** virtual network interface is created
3. **tun2socks** bridges tun0 → xray SOCKS5
4. Routes `0.0.0.0/1` and `128.0.0.0/1` are added via tun0 — all traffic goes through VPN
5. A bypass route for the VPN server IP goes via the real gateway (otherwise tunnel can't reach the server)
6. On disconnect — all routes are cleaned up, tun0 is removed

---

## 🐛 Troubleshooting

**No internet after disconnect:**
```bash
sudo ip route del 0.0.0.0/1 2>/dev/null
sudo ip route del 128.0.0.0/1 2>/dev/null
sudo ip link set tun0 down 2>/dev/null
sudo ip tuntap del dev tun0 mode tun 2>/dev/null
sudo systemctl restart systemd-resolved
sudo ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
```

**Daemon not starting:**
```bash
journalctl --user -u unlimitz-vpn -f
```

**tun2socks not found:**
```bash
yay -S tun2socks-bin
```

---

## 📄 License

MIT — do whatever you want with it.

---

<div align="center">
Made for Arch Linux + KDE Plasma
</div>
