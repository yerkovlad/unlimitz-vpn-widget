#!/usr/bin/env python3
"""Unlimitz VPN Widget — Clean minimal UI. pip install PyQt6"""

import json, socket as sock, sys, threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QIcon, QPixmap, QPen, QBrush, QLinearGradient, QCursor
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QScrollArea, QLineEdit, QSystemTrayIcon,
    QMenu, QStackedWidget, QGraphicsDropShadowEffect, QCheckBox)

sys.path.insert(0, str(Path(__file__).parent))
import link_parser

SOCKET_PATH   = "/tmp/vpn-daemon.sock"
CONFIG_DIR    = Path.home() / ".config" / "unlimitz-vpn"
SETTINGS_FILE = CONFIG_DIR / "widget-settings.json"

# Clean dark palette
BG      = "#111118"
CARD    = "#18181f"
S1      = "#1f1f28"
S2      = "#272733"
S3      = "#323240"
BORDER  = "#2a2a38"
TEXT    = "#eeeef8"
SUB     = "#8a8aaa"
DIM     = "#55556a"
ACC     = "#5c6bc0"   # indigo — calm, professional
ACC_H   = "#7986cb"
GREEN   = "#66bb6a"
RED     = "#ef5350"
YELLOW  = "#ffa726"


def send_cmd(cmd):
    try:
        s = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
        s.settimeout(6); s.connect(SOCKET_PATH)
        s.sendall(json.dumps(cmd).encode())
        data = b""
        while chunk := s.recv(4096): data += chunk
        s.close(); return json.loads(data.decode())
    except: return None

def fmt_speed(bps):
    if bps < 1024: return f"{bps:.0f} B/s"
    if bps < 1<<20: return f"{bps/1024:.1f} KB/s"
    return f"{bps/(1<<20):.1f} MB/s"

def load_s():
    try: return json.loads(SETTINGS_FILE.read_text()) if SETTINGS_FILE.exists() else {}
    except: return {}

def save_s(d):
    try: SETTINGS_FILE.write_text(json.dumps(d, indent=2))
    except: pass

class W(QThread):
    done = pyqtSignal(object)
    def __init__(self, cmd): super().__init__(); self._c = cmd
    def run(self): self.done.emit(send_cmd(self._c))


def make_icon(status="disconnected"):
    c = {"connected": QColor(GREEN), "disconnected": QColor(RED),
         "connecting": QColor(YELLOW), "reconnecting": QColor(YELLOW)}.get(status, QColor(RED))
    px = QPixmap(64, 64); px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.moveTo(32,4); path.lineTo(58,16); path.lineTo(58,36)
    path.lineTo(32,60); path.lineTo(6,36); path.lineTo(6,16); path.closeSubpath()
    p.fillPath(path, c)
    p.setBrush(QBrush(QColor(BG))); p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(23,34,18,15,3,3)
    p.setPen(QPen(QColor(BG), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush); p.drawArc(27,22,10,15,0,180*16)
    p.end(); return QIcon(px)


# ── Reusable style helpers ────────────────────────────────────────────────────

def styled(widget, css): widget.setStyleSheet(css); return widget

def lbl(text, color=TEXT, size=13, bold=False, italic=False):
    l = QLabel(text)
    style = f"color:{color};font-size:{size}px;"
    if bold: style += "font-weight:700;"
    if italic: style += "font-style:italic;"
    l.setStyleSheet(style); return l

def section_label(text):
    l = QLabel(text)
    l.setStyleSheet(f"color:{DIM};font-size:10px;font-weight:700;letter-spacing:2px;")
    return l

def divider():
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{BORDER};margin:2px 0;"); return f

def card_frame(radius=14):
    f = QFrame()
    f.setStyleSheet(f"QFrame{{background:{S1};border:1px solid {BORDER};border-radius:{radius}px;}}")
    return f

def input_field(placeholder=""):
    e = QLineEdit(); e.setPlaceholderText(placeholder)
    e.setStyleSheet(f"""
        QLineEdit{{background:{S1};color:{TEXT};border:1px solid {BORDER};
            border-radius:10px;padding:10px 14px;font-size:13px;}}
        QLineEdit:focus{{border-color:{ACC};}}
    """); return e

def primary_btn(text, min_h=44):
    b = QPushButton(text)
    b.setMinimumHeight(min_h); b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton{{background:{ACC};color:white;border:none;
            border-radius:10px;font-size:14px;font-weight:700;padding:10px;}}
        QPushButton:hover{{background:{ACC_H};}}
        QPushButton:disabled{{background:{S2};color:{DIM};}}
    """); return b

def ghost_btn(text, size=12, color=None):
    c = color or SUB
    b = QPushButton(text); b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton{{background:transparent;color:{c};
            border:1px solid {BORDER};border-radius:8px;
            font-size:{size}px;padding:4px 10px;}}
        QPushButton:hover{{border-color:{c};color:{TEXT};}}
    """); return b

def icon_btn(text):
    b = QPushButton(text); b.setFixedSize(34,34); b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton{{background:{S1};color:{SUB};border:1px solid {BORDER};
            border-radius:9px;font-size:15px;font-weight:600;}}
        QPushButton:hover{{background:{S2};color:{TEXT};border-color:{S3};}}
    """); return b


# ── Server card ───────────────────────────────────────────────────────────────

class SrvCard(QFrame):
    clicked = pyqtSignal()
    rmb     = pyqtSignal()

    def __init__(self, srv):
        super().__init__()
        self.srv = srv; self._active = False
        self.setFixedSize(76, 70); self.setCursor(Qt.CursorShape.PointingHandCursor)
        l = QVBoxLayout(self); l.setContentsMargins(6,7,6,7); l.setSpacing(3)
        self.flag = QLabel(srv["flag"]); self.flag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.flag.setStyleSheet("font-size:24px;background:transparent;border:none;")
        self.name = QLabel(srv["name"][:3].upper()); self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_style(False)
        l.addWidget(self.flag); l.addWidget(self.name)
        self._restyle()

    def _name_style(self, active):
        self.name.setStyleSheet(
            f"font-size:9px;font-weight:700;letter-spacing:1.5px;background:transparent;border:none;"
            f"color:{ACC_H if active else DIM};")

    def set_active(self, v):
        self._active = v; self._name_style(v); self._restyle()

    def _restyle(self):
        if self._active:
            self.setStyleSheet(f"QFrame{{background:{S2};border:1.5px solid {ACC};border-radius:14px;}}")
        else:
            self.setStyleSheet(f"""
                QFrame{{background:{S1};border:1px solid {BORDER};border-radius:14px;}}
                QFrame:hover{{background:{S2};border-color:{S3};}}
            """)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self.clicked.emit()
        elif e.button() == Qt.MouseButton.RightButton: self.rmb.emit()


# ── Main page ─────────────────────────────────────────────────────────────────

class MainPage(QWidget):
    connect_req    = pyqtSignal(str)
    disconnect_req = pyqtSignal()
    edit_req       = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._cards = {}; self._sel = None; self._status = "disconnected"
        self._build()

    def _build(self):
        l = QVBoxLayout(self); l.setContentsMargins(0,0,0,0); l.setSpacing(16)

        # Servers
        l.addWidget(section_label("SERVERS"))
        scroll = QScrollArea(); scroll.setFixedHeight(84)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea{{background:transparent;border:none;}}
            QWidget{{background:transparent;}}
            QScrollBar:horizontal{{background:{S1};height:2px;border-radius:1px;}}
            QScrollBar::handle:horizontal{{background:{S3};border-radius:1px;}}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal{{width:0;}}
        """)
        sw = QWidget(); self.srv_row = QHBoxLayout(sw)
        self.srv_row.setContentsMargins(2,4,2,4); self.srv_row.setSpacing(8)
        self.srv_row.addStretch(); scroll.setWidget(sw); l.addWidget(scroll)

        l.addWidget(divider())

        # Status row
        status_row = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color:{RED};font-size:10px;")
        self.status_text = lbl("Disconnected", RED, 13, bold=True)
        self.ping_lbl = lbl("", DIM, 12)
        status_row.addWidget(self.status_dot); status_row.addSpacing(6)
        status_row.addWidget(self.status_text); status_row.addStretch()
        status_row.addWidget(self.ping_lbl)
        l.addLayout(status_row)

        # Info card
        info = card_frame(12)
        info_l = QHBoxLayout(info); info_l.setContentsMargins(16,12,16,12)

        def info_col(title):
            c = QVBoxLayout(); c.setSpacing(3)
            t = lbl(title, DIM, 10, bold=True); v = lbl("—", TEXT, 12)
            c.addWidget(t); c.addWidget(v)
            return c, v

        ip_col,  self.ip_val  = info_col("IP ADDRESS")
        co_col,  self.co_val  = info_col("COUNTRY")

        vd = QFrame(); vd.setFrameShape(QFrame.Shape.VLine)
        vd.setStyleSheet(f"color:{BORDER};margin:4px 0;"); vd.setFixedWidth(1)

        info_l.addLayout(ip_col); info_l.addStretch()
        info_l.addWidget(vd); info_l.addStretch()
        info_l.addLayout(co_col)
        l.addWidget(info)

        # Speed row
        spd = card_frame(12)
        spd_l = QHBoxLayout(spd); spd_l.setContentsMargins(16,10,16,10)

        def spd_col(arrow, color, title):
            c = QVBoxLayout(); c.setSpacing(2)
            top = QHBoxLayout(); top.setSpacing(5)
            a = QLabel(arrow); a.setStyleSheet(f"color:{color};font-size:12px;")
            t = lbl(title, DIM, 10, bold=True)
            top.addWidget(a); top.addWidget(t)
            v = lbl("0 B/s", TEXT, 16, bold=True)
            c.addLayout(top); c.addWidget(v)
            return c, v

        up_col,   self.up_val   = spd_col("↑", ACC_H,  "UPLOAD")
        down_col, self.down_val = spd_col("↓", "#4dd0e1", "DOWNLOAD")
        vd2 = QFrame(); vd2.setFrameShape(QFrame.Shape.VLine)
        vd2.setStyleSheet(f"color:{BORDER};margin:4px 0;"); vd2.setFixedWidth(1)
        spd_l.addLayout(up_col); spd_l.addStretch()
        spd_l.addWidget(vd2); spd_l.addStretch()
        spd_l.addLayout(down_col)
        l.addWidget(spd)

        # Connect button
        self.conn_btn = primary_btn("Select a server")
        self.conn_btn.setEnabled(False); self.conn_btn.clicked.connect(self._on_conn)
        l.addWidget(self.conn_btn)

    def populate(self, servers, force=False):
        existing = set(self._cards.keys())
        incoming = {s["id"] for s in servers}
        if not force and existing == incoming: return
        for c in self._cards.values():
            self.srv_row.removeWidget(c); c.deleteLater()
        self._cards.clear()
        while self.srv_row.count(): self.srv_row.takeAt(0)
        if not servers:
            self.srv_row.addWidget(lbl("No servers — press + to add", DIM, 12))
            self.srv_row.addStretch(); return
        for srv in servers:
            card = SrvCard(srv)
            card.clicked.connect(lambda s=srv: self._sel_srv(s))
            card.rmb.connect(lambda s=srv: self._ctx(s))
            self._cards[srv["id"]] = card; self.srv_row.addWidget(card)
        self.srv_row.addStretch()
        if self._sel and self._sel["id"] in self._cards:
            self._cards[self._sel["id"]].set_active(True)

    def _sel_srv(self, srv):
        if self._status in ("connecting","reconnecting"): return
        self._sel = srv
        for sid, c in self._cards.items(): c.set_active(sid == srv["id"])
        if self._status == "disconnected":
            self.conn_btn.setText(f"Connect  {srv['flag']}  {srv['name']}")
            self.conn_btn.setEnabled(True)

    def _ctx(self, srv):
        menu = QMenu(self); menu.setStyleSheet(f"""
            QMenu{{background:{CARD};border:1px solid {S3};border-radius:10px;
                padding:4px;color:{TEXT};font-size:13px;}}
            QMenu::item{{padding:7px 16px;border-radius:7px;}}
            QMenu::item:selected{{background:{S2};}}
            QMenu::separator{{background:{BORDER};height:1px;margin:3px 8px;}}
        """)
        edit = menu.addAction("✏  Rename / Edit")
        menu.addSeparator(); delete = menu.addAction("✕  Delete")
        action = menu.exec(QCursor.pos())
        if action == edit: self.edit_req.emit(srv)
        elif action == delete:
            try:
                path = CONFIG_DIR / "servers.json"
                srvs = [s for s in json.loads(path.read_text()) if s["id"] != srv["id"]]
                path.write_text(json.dumps(srvs, indent=2))
                cfg = CONFIG_DIR / "configs" / srv.get("config","")
                if cfg.exists(): cfg.unlink()
                if self._sel and self._sel["id"] == srv["id"]:
                    self._sel = None
                    self.conn_btn.setText("Select a server"); self.conn_btn.setEnabled(False)
            except: pass

    def _on_conn(self):
        if self._status == "connected":
            self.conn_btn.setEnabled(False); self.conn_btn.setText("Disconnecting…")
            self.disconnect_req.emit()
        elif self._sel and self._status == "disconnected":
            self.conn_btn.setEnabled(False); self.conn_btn.setText("Connecting…")
            self.connect_req.emit(self._sel["id"])

    def update_data(self, data):
        self._status = s = data.get("status","disconnected")
        STATUS = {
            "connected":    ("Connected",    GREEN),
            "disconnected": ("Disconnected", RED),
            "connecting":   ("Connecting…",  YELLOW),
            "reconnecting": ("Reconnecting…",YELLOW),
        }
        text, color = STATUS.get(s, ("Unknown", RED))
        self.status_dot.setStyleSheet(f"color:{color};font-size:10px;")
        self.status_text.setText(text)
        self.status_text.setStyleSheet(f"color:{color};font-size:13px;font-weight:700;")
        ping = data.get("ping_ms")
        self.ping_lbl.setText(f"{ping:.0f} ms" if ping else "")
        ip, co = data.get("ip"), data.get("country")
        self.ip_val.setText(ip or "—"); self.co_val.setText(co or "—")
        self.up_val.setText(fmt_speed(data.get("upload_speed",0)))
        self.down_val.setText(fmt_speed(data.get("download_speed",0)))

        if s == "connected":
            self.conn_btn.setText("Disconnect")
            self.conn_btn.setEnabled(True)
            self.conn_btn.setStyleSheet(f"""
                QPushButton{{background:{RED}22;color:{RED};border:1px solid {RED}44;
                    border-radius:10px;font-size:14px;font-weight:700;padding:10px;}}
                QPushButton:hover{{background:{RED}44;}}
            """)
            if active := data.get("server"):
                for sid, c in self._cards.items(): c.set_active(sid == active["id"])
        elif s in ("connecting","reconnecting"):
            self.conn_btn.setEnabled(False)
            self.conn_btn.setStyleSheet(f"""
                QPushButton{{background:{YELLOW}15;color:{YELLOW};border:1px solid {YELLOW}33;
                    border-radius:10px;font-size:14px;font-weight:700;padding:10px;}}
            """)
        else:
            self.conn_btn.setStyleSheet(f"""
                QPushButton{{background:{ACC};color:white;border:none;
                    border-radius:10px;font-size:14px;font-weight:700;padding:10px;}}
                QPushButton:hover{{background:{ACC_H};}}
                QPushButton:disabled{{background:{S2};color:{DIM};}}
            """)
            if self._sel:
                self.conn_btn.setText(f"Connect  {self._sel['flag']}  {self._sel['name']}")
                self.conn_btn.setEnabled(True)
            else:
                self.conn_btn.setText("Select a server"); self.conn_btn.setEnabled(False)
            for c in self._cards.values(): c.set_active(False)


# ── Add server page ───────────────────────────────────────────────────────────

class AddPage(QWidget):
    done = pyqtSignal()
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self); l.setContentsMargins(0,0,0,0); l.setSpacing(14)
        l.addWidget(section_label("ADD SERVER"))
        h = lbl("Paste a vless:// link or subscription URL", SUB, 12); h.setWordWrap(True)
        l.addWidget(h)
        self.entry = input_field("vless://... or https://...")
        self.entry.textChanged.connect(lambda t: self.btn.setEnabled(bool(t.strip()) and (t.startswith("vless://") or t.startswith("http"))))
        self.entry.returnPressed.connect(self._add); l.addWidget(self.entry)
        self.btn = primary_btn("Add Server"); self.btn.setEnabled(False)
        self.btn.clicked.connect(self._add); l.addWidget(self.btn)
        self.st = lbl("", GREEN, 12); self.st.setWordWrap(True); l.addWidget(self.st)
        l.addStretch()

    def _add(self):
        link = self.entry.text().strip()
        if not link: return
        self.btn.setEnabled(False); self._s("⟳ Processing…", YELLOW)
        def work():
            try:
                if link.startswith("vless://"):
                    p = link_parser.parse_vless_link(link)
                    if not p: self._s("✗ Invalid link", RED); return
                    sv = link_parser.save_server(p, CONFIG_DIR)
                    self._s(f"✓ Added {sv['flag']} {sv['name']}", GREEN)
                else:
                    rs = link_parser.fetch_subscription(link)
                    if not rs: self._s("✗ No servers found", RED); return
                    for r in rs: link_parser.save_server(r, CONFIG_DIR)
                    self._s(f"✓ Added {len(rs)} server(s)", GREEN)
                self.entry.clear()
                QTimer.singleShot(1000, self.done.emit)
            except Exception as e: self._s(f"✗ {e}", RED)
            finally: self.btn.setEnabled(True)
        threading.Thread(target=work, daemon=True).start()

    def _s(self, msg, c): self.st.setText(msg); self.st.setStyleSheet(f"color:{c};font-size:12px;")


# ── Edit server page ──────────────────────────────────────────────────────────

class EditPage(QWidget):
    done = pyqtSignal()
    def __init__(self):
        super().__init__(); self._srv = None
        l = QVBoxLayout(self); l.setContentsMargins(0,0,0,0); l.setSpacing(12)
        l.addWidget(section_label("EDIT SERVER"))
        row = QHBoxLayout(); row.setSpacing(8)
        self.flag_e = input_field("🌐"); self.flag_e.setFixedWidth(64)
        self.name_e = input_field("Display name")
        row.addWidget(self.flag_e); row.addWidget(self.name_e); l.addLayout(row)
        self.host_e = input_field("Host (e.g. nl1.unlimitz.space)"); l.addWidget(self.host_e)
        self.st = lbl("", GREEN, 12); l.addWidget(self.st)
        save = primary_btn("Save Changes"); save.clicked.connect(self._save); l.addWidget(save)
        l.addStretch()

    def load(self, srv):
        self._srv = srv
        self.flag_e.setText(srv.get("flag","🌐"))
        self.name_e.setText(srv.get("name",""))
        self.host_e.setText(srv.get("host",""))
        self.st.setText("")

    def _save(self):
        if not self._srv: return
        try:
            path = CONFIG_DIR / "servers.json"
            srvs = json.loads(path.read_text())
            for s in srvs:
                if s["id"] == self._srv["id"]:
                    s["flag"] = self.flag_e.text().strip() or s["flag"]
                    s["name"] = self.name_e.text().strip() or s["name"]
                    s["host"] = self.host_e.text().strip() or s["host"]
            path.write_text(json.dumps(srvs, indent=2))
            self.st.setText("✓ Saved"); self.st.setStyleSheet(f"color:{GREEN};font-size:12px;")
            QTimer.singleShot(600, self.done.emit)
        except Exception as e:
            self.st.setText(f"✗ {e}"); self.st.setStyleSheet(f"color:{RED};font-size:12px;")


# ── Settings page ─────────────────────────────────────────────────────────────

class CfgPage(QWidget):
    def __init__(self):
        super().__init__(); self._s = load_s()
        l = QVBoxLayout(self); l.setContentsMargins(0,0,0,0); l.setSpacing(14)
        l.addWidget(section_label("SETTINGS"))

        card = card_frame(12); cl = QVBoxLayout(card); cl.setContentsMargins(16,14,16,14); cl.setSpacing(12)

        def toggle(text, key, cb=None):
            row = QHBoxLayout()
            row.addWidget(lbl(text, TEXT, 13)); row.addStretch()
            chk = QCheckBox(); chk.setChecked(self._s.get(key, False))
            chk.setStyleSheet(f"""
                QCheckBox::indicator{{width:20px;height:20px;border-radius:6px;
                    background:{S2};border:1px solid {S3};}}
                QCheckBox::indicator:checked{{background:{ACC};border-color:{ACC};}}
                QCheckBox::indicator:hover{{border-color:{ACC};}}
            """)
            chk.toggled.connect(lambda v,k=key,c=cb: (self._s.__setitem__(k,v), save_s(self._s), c(v) if c else None))
            row.addWidget(chk); cl.addLayout(row)

        toggle("Start with system", "autostart", self._autostart)
        toggle("Auto-connect on start", "autoconnect")
        cl.addWidget(divider())

        prow = QHBoxLayout()
        prow.addWidget(lbl("SOCKS5 port", TEXT, 13)); prow.addStretch()
        self.port_e = QLineEdit(str(self._s.get("socks_port", 10808)))
        self.port_e.setFixedWidth(80)
        self.port_e.setStyleSheet(f"QLineEdit{{background:{S2};color:{TEXT};border:1px solid {S3};border-radius:8px;padding:4px 8px;font-size:13px;}} QLineEdit:focus{{border-color:{ACC};}}")
        pa = ghost_btn("Apply", color=ACC_H)
        pa.clicked.connect(lambda: (self._s.__setitem__("socks_port", int(self.port_e.text() or "10808")), save_s(self._s)))
        prow.addWidget(self.port_e); prow.addWidget(pa); cl.addLayout(prow)
        l.addWidget(card)

        about = card_frame(12); al = QVBoxLayout(about); al.setContentsMargins(16,12,16,12); al.setSpacing(3)
        al.addWidget(lbl("Unlimitz VPN Widget", TEXT, 13, bold=True))
        al.addWidget(lbl("Powered by xray-core + tun2socks", DIM, 12))
        l.addWidget(about); l.addStretch()

    def _autostart(self, v):
        f = Path.home() / ".config/autostart/unlimitz-vpn.desktop"
        if v:
            f.parent.mkdir(parents=True, exist_ok=True)
            venv_python = "/home/yevlad/programming/projects/vpn_widget/venv/bin/python3"
            f.write_text(f"[Desktop Entry]\nType=Application\nName=Unlimitz VPN\nExec={venv_python} {Path(__file__).resolve()}\nHidden=false\nNoDisplay=false\n")
        elif f.exists(): f.unlink()


# ── Main window ───────────────────────────────────────────────────────────────

class VPNWindow(QWidget):
    def __init__(self, tray):
        super().__init__()
        self._tray = tray; self._workers = []
        self.setWindowTitle("Unlimitz VPN"); self.setFixedWidth(400)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("* { font-family: 'Noto Sans', 'Segoe UI', sans-serif; }")
        self._build()
        self._timer = QTimer(self); self._timer.timeout.connect(self._poll); self._timer.start(2000)
        self._poll()

    def _build(self):
        outer = QVBoxLayout(self); outer.setContentsMargins(12,12,12,12)
        self.card = QFrame()
        self.card.setStyleSheet(f"QFrame{{background:{CARD};border-radius:18px;border:1px solid {BORDER};}}")
        sh = QGraphicsDropShadowEffect(); sh.setBlurRadius(40); sh.setOffset(0,8)
        sh.setColor(QColor(0,0,0,160)); self.card.setGraphicsEffect(sh)
        ml = QVBoxLayout(self.card); ml.setContentsMargins(22,20,22,22); ml.setSpacing(18)
        outer.addWidget(self.card)

        # Header
        hdr = QHBoxLayout(); hdr.setSpacing(0)
        shield = QLabel("🛡"); shield.setStyleSheet("font-size:22px;")
        title = lbl("Unlimitz VPN", TEXT, 17, bold=True); title.setStyleSheet("color:#eeeef8;font-size:17px;font-weight:700;margin-left:10px;")
        self.back_btn = icon_btn("←"); self.back_btn.setVisible(False); self.back_btn.clicked.connect(lambda: self._page("main"))
        self.add_btn  = icon_btn("+"); self.add_btn.clicked.connect(lambda: self._page("add"))
        self.cfg_btn  = icon_btn("⚙"); self.cfg_btn.clicked.connect(lambda: self._page("cfg"))
        hdr.addWidget(shield); hdr.addWidget(title); hdr.addStretch()
        for b in [self.back_btn, self.add_btn, self.cfg_btn]: hdr.addSpacing(6); hdr.addWidget(b)
        ml.addLayout(hdr)

        self.stack = QStackedWidget(); self.stack.setStyleSheet("background:transparent;")
        self.pg_main = MainPage()
        self.pg_add  = AddPage()
        self.pg_edit = EditPage()
        self.pg_cfg  = CfgPage()
        for pg in [self.pg_main, self.pg_add, self.pg_edit, self.pg_cfg]: self.stack.addWidget(pg)
        self.pg_main.connect_req.connect(lambda sid: self._run({"cmd":"connect","server":sid}))
        self.pg_main.disconnect_req.connect(lambda: self._run({"cmd":"disconnect"}))
        self.pg_main.edit_req.connect(lambda s: (self.pg_edit.load(s), self._page("edit")))
        self.pg_add.done.connect(lambda: (self._page("main"), self._force_poll()))
        self.pg_edit.done.connect(lambda: (self._page("main"), self._force_poll()))
        ml.addWidget(self.stack)

    def _page(self, name):
        idx = {"main":0,"add":1,"edit":2,"cfg":3}.get(name,0)
        self.stack.setCurrentIndex(idx)
        main = name == "main"
        self.back_btn.setVisible(not main)
        self.add_btn.setVisible(main); self.cfg_btn.setVisible(main)
        QTimer.singleShot(30, self.adjustSize)

    def _run(self, cmd):
        w = W(cmd); w.done.connect(lambda _: self._poll())
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w); w.start()

    def _poll(self):
        w = W({"cmd":"status"}); w.done.connect(self._update)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w); w.start()

    def _force_poll(self):
        w = W({"cmd":"status"})
        def apply(data):
            if not data: return
            self.pg_main.populate(data.get("servers",[]), force=True)
            self.pg_main.update_data(data)
        w.done.connect(apply)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w); w.start()

    def _update(self, data):
        if not data: return
        s = data.get("status","disconnected")
        self.pg_main.populate(data.get("servers",[]))
        self.pg_main.update_data(data)
        self._tray.setIcon(make_icon(s))
        ip = data.get("ip","")
        self._tray.setToolTip({"connected":f"Unlimitz VPN  ●  {ip}","disconnected":"Unlimitz VPN  ●  Off","connecting":"Unlimitz VPN  ●  Connecting…","reconnecting":"Unlimitz VPN  ●  Reconnecting…"}.get(s,"Unlimitz VPN"))

    def show_near_tray(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.adjustSize(); w, h = self.width(), self.height()
        tg = self._tray.geometry()
        if tg.isValid() and tg.width() > 0:
            x = min(max(tg.center().x()-w//2, screen.left()+8), screen.right()-w-8)
            y = (tg.top()-h-8) if tg.center().y() > screen.height()//2 else tg.bottom()+8
        else:
            x = screen.right()-w-10; y = screen.top()+8
        self.move(x,y); self.show(); self.raise_(); self.activateWindow()

    def closeEvent(self, e): e.ignore(); self.hide()


def main():
    app = QApplication(sys.argv); app.setQuitOnLastWindowClosed(False)
    tray = QSystemTrayIcon(make_icon("disconnected"), app)
    win = VPNWindow(tray)
    menu = QMenu(); menu.setStyleSheet(f"""
        QMenu{{background:{CARD};border:1px solid {S3};border-radius:10px;
            padding:4px;color:{TEXT};font-size:13px;}}
        QMenu::item{{padding:7px 16px;border-radius:7px;}}
        QMenu::item:selected{{background:{S2};}}
        QMenu::separator{{background:{BORDER};height:1px;margin:3px 8px;}}
    """)
    toggle = menu.addAction("Show / Hide"); menu.addSeparator(); quit_a = menu.addAction("Quit")
    toggle.triggered.connect(lambda: win.hide() if win.isVisible() else win.show_near_tray())
    quit_a.triggered.connect(app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: (win.hide() if win.isVisible() else win.show_near_tray()) if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    s = load_s()
    if s.get("autoconnect") and s.get("last_server"):
        QTimer.singleShot(1000, lambda: win._run({"cmd":"connect","server":s["last_server"]}))
    sys.exit(app.exec())

if __name__ == "__main__": main()