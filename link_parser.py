#!/usr/bin/env python3
"""
link_parser.py — parses vless:// share links and subscription URLs
into xray JSON configs + server metadata.

Supported formats:
  vless://UUID@host:port?security=reality&sni=...&pbk=...&sid=...&fp=...&flow=...#Name
  vless://UUID@host:port?security=tls&sni=...#Name
  vless://UUID@host:port?security=none#Name
  Subscription URL (HTTP) → base64 list of vless:// links, one per line
"""

import base64
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


# ── vless:// parser ───────────────────────────────────────────────────────────

def parse_vless_link(link: str) -> Optional[dict]:
    """
    Returns {"server_meta": {...}, "xray_config": {...}} or None on error.
    """
    link = link.strip()
    if not link.startswith("vless://"):
        return None

    try:
        # vless://UUID@host:port?params#fragment
        rest = link[len("vless://"):]
        fragment = ""
        if "#" in rest:
            rest, fragment = rest.rsplit("#", 1)
            fragment = urllib.parse.unquote(fragment)

        if "@" not in rest:
            return None

        uuid, hostpart = rest.split("@", 1)

        if "?" in hostpart:
            netloc, query_str = hostpart.split("?", 1)
        else:
            netloc, query_str = hostpart, ""

        # Parse host:port (handle IPv6 [::1]:port)
        if netloc.startswith("["):
            # IPv6
            m = re.match(r"\[(.+)\]:(\d+)", netloc)
            if not m:
                return None
            host, port = m.group(1), int(m.group(2))
        else:
            parts = netloc.rsplit(":", 1)
            host = parts[0]
            port = int(parts[1]) if len(parts) == 2 else 443

        params = urllib.parse.parse_qs(query_str, keep_blank_values=True)
        def p(key, default=""):
            v = params.get(key, [default])
            return v[0] if v else default

        security    = p("security", "none")
        sni         = p("sni") or p("serverName") or host
        fingerprint = p("fp", "chrome")
        public_key  = p("pbk")
        short_id    = p("sid", "")
        flow        = p("flow", "")
        network     = p("type", "tcp")

        # ── Derive human name and flag from fragment ──────────────────────────
        name, flag, country_code = _parse_name(fragment, host)

        # ── Build xray config ─────────────────────────────────────────────────
        xray_config = _build_xray_config(
            host=host, port=port, uuid=uuid,
            security=security, sni=sni, fingerprint=fingerprint,
            public_key=public_key, short_id=short_id,
            flow=flow, network=network,
        )

        server_meta = {
            "id": _make_id(name, host),
            "flag": flag,
            "name": name,
            "host": host,
            "config": f"{_make_id(name, host)}.json",
        }

        return {"server_meta": server_meta, "xray_config": xray_config}

    except Exception as e:
        print(f"[parser] Error parsing link: {e}")
        return None


def _parse_name(fragment: str, host: str) -> tuple[str, str, str]:
    """Extract display name, emoji flag, country code from link fragment."""
    COUNTRY_FLAGS = {
        "nl": ("🇳🇱", "Netherlands"), "netherlands": ("🇳🇱", "Netherlands"),
        "se": ("🇸🇪", "Sweden"),      "sweden":      ("🇸🇪", "Sweden"),
        "pl": ("🇵🇱", "Poland"),      "poland":      ("🇵🇱", "Poland"),
        "de": ("🇩🇪", "Germany"),     "germany":     ("🇩🇪", "Germany"),
        "gb": ("🇬🇧", "UK"),          "uk":          ("🇬🇧", "UK"),
        "us": ("🇺🇸", "USA"),         "usa":         ("🇺🇸", "USA"),
        "fr": ("🇫🇷", "France"),      "france":      ("🇫🇷", "France"),
        "fi": ("🇫🇮", "Finland"),     "finland":     ("🇫🇮", "Finland"),
        "lt": ("🇱🇹", "Lithuania"),   "lithuania":   ("🇱🇹", "Lithuania"),
        "lv": ("🇱🇻", "Latvia"),      "latvia":      ("🇱🇻", "Latvia"),
        "ee": ("🇪🇪", "Estonia"),     "estonia":     ("🇪🇪", "Estonia"),
        "ch": ("🇨🇭", "Switzerland"), "switzerland": ("🇨🇭", "Switzerland"),
        "at": ("🇦🇹", "Austria"),     "austria":     ("🇦🇹", "Austria"),
        "cz": ("🇨🇿", "Czechia"),     "czechia":     ("🇨🇿", "Czechia"),
        "tr": ("🇹🇷", "Turkey"),      "turkey":      ("🇹🇷", "Turkey"),
    }

    name = fragment.strip() if fragment.strip() else host
    flag = "🌐"

    # Detect country from HOST (more reliable than fragment)
    COUNTRY_FLAGS = {
        "nl": ("🇳🇱", "Netherlands"),
        "se": ("🇸🇪", "Sweden"),
        "pl": ("🇵🇱", "Poland"),
        "de": ("🇩🇪", "Germany"),
        "gb": ("🇬🇧", "UK"),
        "uk": ("🇬🇧", "UK"),
        "us": ("🇺🇸", "USA"),
        "fr": ("🇫🇷", "France"),
        "fi": ("🇫🇮", "Finland"),
        "lt": ("🇱🇹", "Lithuania"),
        "lv": ("🇱🇻", "Latvia"),
        "ee": ("🇪🇪", "Estonia"),
        "ch": ("🇨🇭", "Switzerland"),
        "at": ("🇦🇹", "Austria"),
        "cz": ("🇨🇿", "Czechia"),
        "tr": ("🇹🇷", "Turkey"),
    }

    # Match against host first (e.g. nl1.example.com → nl)
    host_lower = host.lower()
    for code, (f, country) in COUNTRY_FLAGS.items():
        # Match at start of hostname segment: nl1., de2., us1. etc
        if re.match(rf'^{code}\d*\.', host_lower) or host_lower.startswith(code + "."):
            flag = f
            if not fragment.strip():
                name = country
            break
    else:
        # Fallback: search in fragment
        name_lower = name.lower()
        for code, (f, country) in COUNTRY_FLAGS.items():
            if f" {code}" in f" {name_lower} " or name_lower.startswith(code):
                flag = f
                if not fragment.strip():
                    name = country
                break

    name = re.sub(r"[^\w\s\-🇦-🇿]", "", name).strip()[:32] or host
    return name, flag, host


def _make_id(name: str, host: str) -> str:
    """Create a filesystem-safe server ID."""
    base = re.sub(r"[^a-z0-9]", "-", name.lower())
    base = re.sub(r"-+", "-", base).strip("-")
    return base[:20] or re.sub(r"[^a-z0-9]", "-", host)[:20]


def _build_xray_config(
    host, port, uuid, security, sni, fingerprint,
    public_key, short_id, flow, network,
) -> dict:
    """Build a minimal valid xray outbound config."""
    stream_settings: dict = {"network": network}

    if security == "reality":
        stream_settings["security"] = "reality"
        stream_settings["realitySettings"] = {
            "serverName": sni,
            "fingerprint": fingerprint or "chrome",
            "publicKey": public_key,
            "shortId": short_id,
        }
    elif security == "tls":
        stream_settings["security"] = "tls"
        stream_settings["tlsSettings"] = {
            "serverName": sni,
            "fingerprint": fingerprint or "chrome",
        }
    else:
        stream_settings["security"] = "none"

    user = {"id": uuid, "encryption": "none"}
    if flow:
        user["flow"] = flow

    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "port": 10808,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
                "tag": "socks-in",
            },
            {
                "port": 10809,
                "listen": "127.0.0.1",
                "protocol": "http",
                "tag": "http-in",
            },
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [{"address": host, "port": port, "users": [user]}]
                },
                "streamSettings": stream_settings,
                "tag": "vless-out",
            },
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "rules": [
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}
            ]
        },
    }


# ── Subscription URL fetcher ──────────────────────────────────────────────────

def fetch_subscription(url: str, timeout: int = 10) -> list[dict]:
    """
    Fetches a subscription URL, decodes base64 content,
    and returns a list of parsed server dicts.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "v2rayN/6.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()

        # Decode base64 (standard or URL-safe)
        try:
            decoded = base64.b64decode(raw + b"==").decode("utf-8", errors="replace")
        except Exception:
            decoded = raw.decode("utf-8", errors="replace")

        links = [l.strip() for l in decoded.splitlines() if l.strip()]
        results = []
        for link in links:
            if link.startswith("vless://"):
                parsed = parse_vless_link(link)
                if parsed:
                    results.append(parsed)
        return results

    except Exception as e:
        raise RuntimeError(f"Subscription fetch failed: {e}")


# ── Save parsed server to disk ────────────────────────────────────────────────

def save_server(parsed: dict, config_dir: Path) -> dict:
    """
    Writes the xray config JSON and updates servers.json.
    Returns updated server_meta dict with final id (in case of conflicts).
    """
    meta   = parsed["server_meta"]
    config = parsed["xray_config"]

    # Resolve ID conflicts
    servers_path = config_dir / "servers.json"
    servers = json.loads(servers_path.read_text()) if servers_path.exists() else []

    existing_ids = {s["id"] for s in servers}
    base_id = meta["id"]
    final_id = base_id
    counter = 2
    while final_id in existing_ids:
        final_id = f"{base_id}-{counter}"
        counter += 1
    meta["id"] = final_id
    meta["config"] = f"{final_id}.json"

    # Write xray config
    config_path = config_dir / "configs" / meta["config"]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False))

    # Update servers.json (skip if already has same host+uuid)
    existing_hosts = {s["host"] for s in servers}
    if meta["host"] not in existing_hosts:
        servers.append(meta)
        servers_path.write_text(json.dumps(servers, indent=2, ensure_ascii=False))

    return meta


# ── CLI usage ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: link_parser.py <vless://... | https://sub.url>")
        sys.exit(1)

    arg = sys.argv[1]
    config_dir = Path.home() / ".config" / "unlimitz-vpn"

    if arg.startswith("vless://"):
        result = parse_vless_link(arg)
        if result:
            saved = save_server(result, config_dir)
            print(f"✓ Added: {saved['flag']} {saved['name']} ({saved['host']})")
        else:
            print("✗ Failed to parse link")
            sys.exit(1)

    elif arg.startswith("http://") or arg.startswith("https://"):
        print(f"Fetching subscription: {arg}")
        try:
            results = fetch_subscription(arg)
            print(f"Found {len(results)} servers")
            for r in results:
                saved = save_server(r, config_dir)
                print(f"  ✓ {saved['flag']} {saved['name']} ({saved['host']})")
        except RuntimeError as e:
            print(f"✗ {e}")
            sys.exit(1)

    else:
        print("✗ Unsupported format. Use vless:// or https:// subscription URL")
        sys.exit(1)