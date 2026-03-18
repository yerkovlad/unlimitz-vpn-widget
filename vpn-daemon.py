#!/usr/bin/env python3
"""
Unlimitz VPN Daemon — xray SOCKS5 + tun2socks TUN mode.
Works like nekoray: all traffic routed through VPN.
DNS is NOT touched — systemd-resolved works automatically through TUN.
"""

import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path

CONFIG_DIR  = Path.home() / ".config" / "unlimitz-vpn"
SOCKET_PATH = "/tmp/vpn-daemon.sock"
SOCKS_PORT  = 10808
HTTP_PORT   = 10809
TUN_IFACE   = "tun0"
TUN_ADDR    = "198.18.0.1"
TUN_MASK    = "15"
USER        = os.environ.get("USER", "yevlad")


def sh(cmd: list[str], sudo=False, inp=None) -> tuple[int, str]:
    if sudo:
        cmd = ["sudo", "-n"] + cmd
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=10, input=inp)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


class VPNDaemon:
    def __init__(self):
        self.servers: list[dict] = []
        self.current_server: dict | None = None
        self.xray_proc: subprocess.Popen | None = None
        self.tun_proc:  subprocess.Popen | None = None

        self.status = "disconnected"
        self.ping_ms: float | None = None
        self.upload_speed = 0.0
        self.download_speed = 0.0
        self.current_ip: str | None = None
        self.current_country: str | None = None
        self.tun_active = False

        self._orig_gw:  str | None = None
        self._orig_dev: str | None = None
        self._prev_rx = self._prev_tx = 0
        self._prev_t = 0.0

        self._load_servers()

    def _load_servers(self):
        path = CONFIG_DIR / "servers.json"
        try:
            self.servers = json.loads(path.read_text()) if path.exists() else []
        except Exception:
            self.servers = []

    # ── Commands ──────────────────────────────────────────────────────────────

    async def cmd_connect(self, server_id: str) -> dict:
        server = next((s for s in self.servers if s["id"] == server_id), None)
        if not server:
            return {"error": f"Unknown server: {server_id}"}

        await self._teardown()
        self.current_server  = server
        self.status          = "connecting"
        self.current_ip      = None
        self.current_country = None
        self.ping_ms         = None

        # 1. Start xray
        cfg = CONFIG_DIR / "configs" / server["config"]
        if not cfg.exists():
            self.status = "disconnected"; self.current_server = None
            return {"error": f"Config not found: {cfg}"}

        try:
            self.xray_proc = subprocess.Popen(
                ["xray", "run", "-c", str(cfg)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            self.status = "disconnected"; self.current_server = None
            return {"error": "xray not found"}

        await asyncio.sleep(2)
        if self.xray_proc.poll() is not None:
            self.status = "disconnected"; self.current_server = None
            return {"error": "xray exited — check config"}

        # 2. Get gateway before touching routes
        self._orig_gw, self._orig_dev = self._default_gw()
        if not self._orig_gw:
            await self._teardown()
            return {"error": "No default gateway detected"}

        # 3. Setup TUN interface
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, self._tun_up, server["host"])
        if not ok:
            await self._teardown()
            return {"error": "TUN setup failed — check sudoers"}

        # 4. Start tun2socks
        try:
            self.tun_proc = subprocess.Popen(
                ["tun2socks",
                 "-device", TUN_IFACE,
                 "-proxy",  f"socks5://127.0.0.1:{SOCKS_PORT}",
                 "-loglevel", "silent"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            await self._teardown()
            return {"error": "tun2socks not found — yay -S tun2socks-bin"}

        await asyncio.sleep(1)
        if self.tun_proc.poll() is not None:
            await self._teardown()
            return {"error": "tun2socks exited immediately"}

        self.tun_active = True
        self.status = "connected"
        print(f"[INFO] Connected → {server['name']} via TUN")
        asyncio.create_task(self._fetch_ip())
        return {"ok": True}

    async def cmd_disconnect(self) -> dict:
        await self._teardown()
        self.status = "disconnected"; self.current_server = None
        self.current_ip = None; self.current_country = None
        self.ping_ms = None; self.upload_speed = 0.0
        self.download_speed = 0.0; self._prev_t = 0.0
        print("[INFO] Disconnected")
        return {"ok": True}

    def cmd_status(self) -> dict:
        self._load_servers()
        return {
            "status":         self.status,
            "server":         self.current_server,
            "ip":             self.current_ip,
            "country":        self.current_country,
            "ping_ms":        self.ping_ms,
            "upload_speed":   self.upload_speed,
            "download_speed": self.download_speed,
            "servers":        self.servers,
        }

    # ── TUN setup ─────────────────────────────────────────────────────────────

    def _tun_up(self, server_host: str) -> bool:
        # Create and configure TUN interface
        for cmd in [
            ["ip", "tuntap", "add", "dev", TUN_IFACE, "mode", "tun", "user", USER],
            ["ip", "addr",   "add", f"{TUN_ADDR}/{TUN_MASK}", "dev", TUN_IFACE],
            ["ip", "link",   "set", "dev", TUN_IFACE, "up"],
        ]:
            rc, out = sh(cmd, sudo=True)
            if rc != 0:
                print(f"[ERR] {cmd}: {out}")
                return False

        # Bypass route: VPN server IP goes via REAL gateway (not through tunnel)
        # This is critical — without this the tunnel can't reach the VPN server
        rc, out = sh(["ip", "route", "add", f"{server_host}/32",
                      "via", self._orig_gw, "dev", self._orig_dev], sudo=True)
        if rc != 0:
            print(f"[WARN] bypass route: {out}")
            # Try to resolve hostname to IP if it's a domain
            try:
                import socket
                ip = socket.gethostbyname(server_host)
                if ip != server_host:
                    sh(["ip", "route", "add", f"{ip}/32",
                        "via", self._orig_gw, "dev", self._orig_dev], sudo=True)
                    print(f"[INFO] bypass route via resolved IP: {ip}")
            except Exception:
                pass

        # Route ALL traffic through tun0 (split into two /1 to avoid
        # replacing the default route which we still need for bypass)
        for pfx in ["0.0.0.0/1", "128.0.0.0/1"]:
            rc, out = sh(["ip", "route", "add", pfx, "dev", TUN_IFACE], sudo=True)
            if rc != 0:
                print(f"[ERR] route {pfx}: {out}")
                self._tun_down(server_host)
                return False

        print(f"[INFO] TUN up — gw={self._orig_gw} dev={self._orig_dev}")
        return True

    def _tun_down(self, server_host: str | None):
        for pfx in ["0.0.0.0/1", "128.0.0.0/1"]:
            sh(["ip", "route", "del", pfx], sudo=True)

        if server_host:
            sh(["ip", "route", "del", f"{server_host}/32"], sudo=True)
            # Also try resolved IP
            try:
                import socket
                ip = socket.gethostbyname(server_host)
                if ip != server_host:
                    sh(["ip", "route", "del", f"{ip}/32"], sudo=True)
            except Exception:
                pass

        sh(["ip", "link",   "set",  "dev", TUN_IFACE, "down"],        sudo=True)
        sh(["ip", "tuntap", "del",  "dev", TUN_IFACE, "mode", "tun"], sudo=True)
        print("[INFO] TUN down")

    async def _teardown(self):
        host = self.current_server["host"] if self.current_server else None
        loop = asyncio.get_event_loop()

        if self.tun_proc:
            self.tun_proc.terminate()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, self.tun_proc.wait), timeout=3)
            except asyncio.TimeoutError:
                self.tun_proc.kill()
            self.tun_proc = None

        if self.tun_active:
            await loop.run_in_executor(None, self._tun_down, host)
            self.tun_active = False

        if self.xray_proc:
            self.xray_proc.terminate()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, self.xray_proc.wait), timeout=4)
            except asyncio.TimeoutError:
                self.xray_proc.kill()
            self.xray_proc = None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _default_gw(self) -> tuple[str | None, str | None]:
        try:
            out = subprocess.check_output(
                ["ip", "route", "show", "default"],
                stderr=subprocess.DEVNULL).decode()
            gw  = re.search(r"via (\S+)", out)
            dev = re.search(r"dev (\S+)", out)
            return gw.group(1) if gw else None, dev.group(1) if dev else None
        except Exception:
            return None, None

    async def _fetch_ip(self):
        """After TUN is up, curl goes through VPN automatically."""
        await asyncio.sleep(3)
        try:
            p = await asyncio.create_subprocess_exec(
                "curl", "-s", "--max-time", "10", "https://ipapi.co/json/",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            out, _ = await p.communicate()
            d = json.loads(out.decode())
            self.current_ip      = d.get("ip")
            self.current_country = d.get("country_name")
            print(f"[INFO] IP: {self.current_ip} ({self.current_country})")
        except Exception as e:
            print(f"[WARN] IP fetch: {e}")

    # ── Background loops ──────────────────────────────────────────────────────

    async def _watchdog(self):
        while True:
            await asyncio.sleep(5)
            if self.status == "connected":
                dead = (self.xray_proc and self.xray_proc.poll() is not None) or \
                       (self.tun_proc  and self.tun_proc.poll()  is not None)
                if dead:
                    print("[WARN] process crashed, reconnecting")
                    sid = self.current_server["id"]
                    self.status = "reconnecting"
                    await self.cmd_disconnect()
                    await asyncio.sleep(2)
                    await self.cmd_connect(sid)

    async def _ping_loop(self):
        while True:
            await asyncio.sleep(5)
            if self.status == "connected" and self.current_server:
                try:
                    p = await asyncio.create_subprocess_exec(
                        "ping", "-c", "1", "-W", "3",
                        self.current_server["host"],
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL)
                    out, _ = await p.communicate()
                    m = re.search(r"time=(\d+\.?\d*)", out.decode())
                    self.ping_ms = float(m.group(1)) if m else None
                except Exception:
                    self.ping_ms = None

    async def _traffic_loop(self):
        while True:
            await asyncio.sleep(2)
            if self.status != "connected" or not self.tun_active:
                self.upload_speed = self.download_speed = 0.0
                self._prev_t = 0.0
                continue
            try:
                for line in open("/proc/net/dev"):
                    if TUN_IFACE + ":" in line:
                        p = line.split()
                        rx, tx = int(p[1]), int(p[9])
                        now = time.monotonic()
                        if self._prev_t > 0:
                            dt = now - self._prev_t
                            if dt > 0:
                                self.download_speed = max(0, (rx - self._prev_rx) / dt)
                                self.upload_speed   = max(0, (tx - self._prev_tx) / dt)
                        self._prev_rx, self._prev_tx, self._prev_t = rx, tx, now
                        break
            except Exception:
                pass

    # ── Socket ────────────────────────────────────────────────────────────────

    async def _handle(self, reader, writer):
        try:
            raw    = await asyncio.wait_for(reader.read(4096), timeout=5)
            cmd    = json.loads(raw.decode())
            action = cmd.get("cmd")
            if   action == "status":     resp = self.cmd_status()
            elif action == "connect":    resp = await self.cmd_connect(cmd["server"])
            elif action == "disconnect": resp = await self.cmd_disconnect()
            else:                        resp = {"error": f"Unknown: {action}"}
            writer.write(json.dumps(resp).encode())
            await writer.drain()
        except Exception as e:
            try:
                writer.write(json.dumps({"error": str(e)}).encode())
                await writer.drain()
            except Exception:
                pass
        finally:
            try: writer.close()
            except Exception: pass

    async def run(self):
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        srv = await asyncio.start_unix_server(self._handle, path=SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o600)
        print(f"[INFO] Daemon ready — {SOCKET_PATH}")
        asyncio.create_task(self._watchdog())
        asyncio.create_task(self._ping_loop())
        asyncio.create_task(self._traffic_loop())
        async with srv:
            await srv.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(VPNDaemon().run())
    except KeyboardInterrupt:
        print("\n[INFO] Stopped")