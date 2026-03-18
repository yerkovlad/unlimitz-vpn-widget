#!/usr/bin/env bash
# waybar-vpn.sh — Called by waybar custom/vpn module every N seconds.
# Outputs JSON: { text, class, tooltip }
#
# Requires: socat (pacman -S socat)

SOCKET="/tmp/vpn-daemon.sock"

json=$(echo '{"cmd":"status"}' | socat -t3 - "UNIX-CONNECT:$SOCKET" 2>/dev/null)

if [[ -z "$json" ]]; then
    printf '{"text":"⊘ VPN","class":"disconnected","tooltip":"Daemon not running"}\n'
    exit 0
fi

read -r status server_flag server_name ping_str ip country <<< "$(python3 - <<'PYEOF'
import sys, json
d = json.loads(sys.stdin.read())
s    = d.get("status", "disconnected")
srv  = d.get("server") or {}
flag = srv.get("flag", "")
name = srv.get("name", "")[:3].upper()
ping = d.get("ping_ms")
ip   = d.get("ip") or ""
cntry= d.get("country") or ""
p_str= f"{ping:.0f}ms" if ping is not None else ""
print(s, flag, name, p_str, ip, cntry)
PYEOF
)"

case "$status" in
  connected)
    text="${server_flag} ${server_name}  ${ping_str}"
    tooltip="Connected | ${ip} (${country}) | Ping: ${ping_str}"
    class="connected"
    ;;
  connecting|reconnecting)
    text="⟳ VPN"
    tooltip="Connecting..."
    class="connecting"
    ;;
  *)
    text="⊘ VPN"
    tooltip="Disconnected — click to open"
    class="disconnected"
    ;;
esac

printf '{"text":"%s","class":"%s","tooltip":"%s"}\n' "$text" "$class" "$tooltip"
