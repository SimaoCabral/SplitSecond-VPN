"""Split/Second VPN — cliente GUI para a rede tinc 'splitsecond'.

Cross-platform (Windows + Linux). Funcionalidades:
- Setup inicial (nome, IP, geração de chaves, firewall no Windows)
- Importar hosts/server (colar conteúdo ou obter via URL/DuckDNS)
- Ligar/Desligar tinc e configurar o IP do adaptador
- Estado em tempo real com ping ao servidor
- Auto-elevação no Windows
- Configuração persistente
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk


NETWORK_NAME = "splitsecond"
SERVER_VPN_IP = "10.20.0.1"
VPN_SUBNET_MASK = "255.255.255.0"
VPN_CIDR_BITS = 24
TINC_PORT = 11655

APP_TITLE = "Split/Second VPN"
APP_VERSION = "1.0.0"

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


# ----------------------------- platform paths -----------------------------

def windows_tinc_exe() -> Path:
    return Path(r"C:\Program Files\tinc\tinc.exe")


def windows_tincd_exe() -> Path:
    return Path(r"C:\Program Files\tinc\tincd.exe")


def tinc_dir() -> Path:
    if IS_WINDOWS:
        return Path(r"C:\Program Files\tinc") / NETWORK_NAME
    return Path("/etc/tinc") / NETWORK_NAME


def config_dir() -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
        d = base / "SplitSecondVPN"
    else:
        d = Path.home() / ".config" / "splitsecond-vpn"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file() -> Path:
    return config_dir() / "settings.json"


# ----------------------------- elevation -----------------------------

def is_admin() -> bool:
    if IS_WINDOWS:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def reexec_as_admin_windows() -> None:
    """Re-launch this process with UAC elevation. No-op if already elevated."""
    if not IS_WINDOWS or is_admin():
        return
    params = " ".join(f'"{a}"' for a in sys.argv)
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    finally:
        sys.exit(0)


# ----------------------------- settings -----------------------------

@dataclass
class Settings:
    player_name: str = ""
    last_octet: int = 2
    server_host: str = ""  # hostname/IP usado no hosts/server (substituído sempre que muda)
    duckdns_host: str = ""  # opcional: <name>.duckdns.org
    host_file_url: str = ""  # opcional: URL para descarregar hosts/server
    auto_pull_on_connect: bool = True

    @classmethod
    def load(cls) -> "Settings":
        p = config_file()
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception:
            return cls()

    def save(self) -> None:
        config_file().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @property
    def vpn_ip(self) -> str:
        return f"10.20.0.{self.last_octet}"


# ----------------------------- shell helpers -----------------------------

def _flags_no_window() -> int:
    if IS_WINDOWS:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def run_cmd(args: list[str], *, timeout: int = 30, check: bool = False) -> tuple[int, str, str]:
    """Run a command. Returns (rc, stdout, stderr). Never raises unless check=True."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_flags_no_window(),
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"{' '.join(args)} -> {proc.returncode}: {proc.stderr.strip()}")
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout: {e}"


def sudo_prefix() -> list[str]:
    """On Linux we need root for tinc + ip; prefer pkexec for GUI prompt."""
    if IS_WINDOWS:
        return []
    if shutil.which("pkexec"):
        return ["pkexec"]
    if shutil.which("sudo"):
        return ["sudo", "-n"]
    return []


# ----------------------------- tinc operations -----------------------------

def tinc_binary() -> str:
    if IS_WINDOWS:
        return str(windows_tinc_exe())
    return shutil.which("tinc") or "tinc"


def tincd_binary() -> str:
    if IS_WINDOWS:
        return str(windows_tincd_exe())
    return shutil.which("tincd") or "tincd"


def tinc_installed() -> bool:
    if IS_WINDOWS:
        return windows_tinc_exe().exists()
    return shutil.which("tincd") is not None


def tinc_status() -> bool:
    """Roughly check if tincd is running for this network."""
    if IS_WINDOWS:
        rc, out, _ = run_cmd(["tasklist", "/FI", "IMAGENAME eq tincd.exe"], timeout=10)
        return rc == 0 and "tincd.exe" in out.lower()
    rc, out, _ = run_cmd(["pgrep", "-a", "tincd"], timeout=5)
    return rc == 0 and NETWORK_NAME in out


def ensure_tinc_dirs() -> None:
    d = tinc_dir()
    (d / "hosts").mkdir(parents=True, exist_ok=True)


def write_text_maybe_sudo(path: Path, content: str, *, executable: bool = False) -> None:
    """Write a file. On Linux uses pkexec/sudo + tee for protected paths."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if executable and not IS_WINDOWS:
            path.chmod(0o755)
        return
    except PermissionError:
        pass
    if IS_WINDOWS:
        raise
    sp = sudo_prefix()
    if not sp:
        raise PermissionError(f"Sem privilégios para escrever em {path}")
    # mkdir
    run_cmd(sp + ["mkdir", "-p", str(path.parent)], check=True)
    # write via tee
    proc = subprocess.run(
        sp + ["tee", str(path)],
        input=content.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"tee {path}: {proc.stderr.decode(errors='replace')}")
    if executable:
        run_cmd(sp + ["chmod", "+x", str(path)], check=True)


def read_text_maybe_sudo(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except PermissionError:
        if IS_WINDOWS:
            raise
        sp = sudo_prefix()
        if not sp:
            raise
        rc, out, err = run_cmd(sp + ["cat", str(path)])
        if rc != 0:
            raise RuntimeError(err.strip() or f"cat {path} falhou")
        return out


def write_tinc_conf(player_name: str) -> None:
    content = f"Name = {player_name}\nMode = switch\nConnectTo = server\n"
    write_text_maybe_sudo(tinc_dir() / "tinc.conf", content)


def write_host_self(player_name: str, last_octet: int, pubkey_block: str = "") -> None:
    content = f"Subnet = 10.20.0.{last_octet}/32\n"
    if pubkey_block:
        content += "\n" + pubkey_block.strip() + "\n"
    write_text_maybe_sudo(tinc_dir() / "hosts" / player_name, content)


def write_linux_scripts(last_octet: int) -> None:
    if not IS_LINUX:
        return
    up = (
        "#!/bin/bash\n"
        "ip link set $INTERFACE up\n"
        f"ip addr add 10.20.0.{last_octet}/{VPN_CIDR_BITS} dev $INTERFACE\n"
    )
    down = (
        "#!/bin/bash\n"
        f"ip addr del 10.20.0.{last_octet}/{VPN_CIDR_BITS} dev $INTERFACE || true\n"
        "ip link set $INTERFACE down || true\n"
    )
    write_text_maybe_sudo(tinc_dir() / "tinc-up", up, executable=True)
    write_text_maybe_sudo(tinc_dir() / "tinc-down", down, executable=True)


def generate_keys() -> tuple[bool, str]:
    """Generate RSA + ed25519 keys for the configured network."""
    if IS_WINDOWS:
        rc1, o1, e1 = run_cmd([tinc_binary(), "-n", NETWORK_NAME, "generate-rsa-keys"], timeout=60)
        rc2, o2, e2 = run_cmd([tinc_binary(), "-n", NETWORK_NAME, "generate-ed25519-keys"], timeout=60)
        ok = rc1 == 0 and rc2 == 0
        return ok, (o1 + o2 + e1 + e2).strip()
    sp = sudo_prefix()
    rc, out, err = run_cmd(sp + [tincd_binary(), "-n", NETWORK_NAME, "--generate-keys"], timeout=60)
    return rc == 0, (out + err).strip()


def write_server_host_file(content: str) -> None:
    write_text_maybe_sudo(tinc_dir() / "hosts" / "server", content)


def read_self_host_file(player_name: str) -> str:
    return read_text_maybe_sudo(tinc_dir() / "hosts" / player_name)


# ----------------------------- connect / disconnect -----------------------------

def start_tinc() -> tuple[bool, str]:
    if IS_WINDOWS:
        rc, out, err = run_cmd([tinc_binary(), "-n", NETWORK_NAME, "start"], timeout=20)
        return rc == 0, (out + err).strip()
    sp = sudo_prefix()
    rc, out, err = run_cmd(sp + [tincd_binary(), "-n", NETWORK_NAME], timeout=20)
    return rc == 0, (out + err).strip()


def stop_tinc() -> tuple[bool, str]:
    if IS_WINDOWS:
        rc, out, err = run_cmd([tinc_binary(), "-n", NETWORK_NAME, "stop"], timeout=20)
        return rc == 0, (out + err).strip()
    sp = sudo_prefix()
    rc, out, err = run_cmd(sp + ["pkill", "-f", f"tincd.*{NETWORK_NAME}"], timeout=10)
    # pkill returns 1 when no process matched; treat that as success
    return rc in (0, 1), (out + err).strip()


def set_windows_tap_ip(ip: str) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return True, ""
    rc, out, err = run_cmd(
        ["netsh", "interface", "ip", "set", "address", "tap0901", "static", ip, VPN_SUBNET_MASK],
        timeout=30,
    )
    return rc == 0, (out + err).strip()


def add_windows_firewall_rules() -> tuple[bool, str]:
    if not IS_WINDOWS:
        return True, ""
    log: list[str] = []
    rules = [
        ["netsh", "advfirewall", "firewall", "add", "rule", "name=tinc-tcp", "dir=in",
         "action=allow", "protocol=TCP", f"localport={TINC_PORT}"],
        ["netsh", "advfirewall", "firewall", "add", "rule", "name=tinc-udp", "dir=in",
         "action=allow", "protocol=UDP", f"localport={TINC_PORT}"],
        ["netsh", "advfirewall", "firewall", "add", "rule", "name=ICMP-Allow",
         "protocol=icmpv4:8,any", "dir=in", "action=allow"],
    ]
    all_ok = True
    for cmd in rules:
        rc, out, err = run_cmd(cmd, timeout=15)
        if rc != 0:
            all_ok = False
        log.append((out + err).strip())
    return all_ok, "\n".join(filter(None, log))


def ping_server(timeout_s: int = 2) -> bool:
    if IS_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(timeout_s * 1000), SERVER_VPN_IP]
    else:
        cmd = ["ping", "-c", "1", "-W", str(timeout_s), SERVER_VPN_IP]
    rc, _, _ = run_cmd(cmd, timeout=timeout_s + 3)
    return rc == 0


# ----------------------------- host file helpers -----------------------------

IP_RE = re.compile(r"^\s*Address\s*=\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


def replace_address_in_host_file(content: str, new_addr: str) -> str:
    """Substitui (ou insere) a linha 'Address = ...' no host file."""
    if IP_RE.search(content):
        return IP_RE.sub(f"Address = {new_addr}", content, count=1)
    lines = content.splitlines()
    lines.insert(0, f"Address = {new_addr}")
    return "\n".join(lines) + ("\n" if not content.endswith("\n") else "")


def fetch_url(url: str, timeout: int = 8) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_TITLE}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def resolve_duckdns(host: str) -> str:
    return socket.gethostbyname(host)


# ----------------------------- GUI -----------------------------

ACCENT = "#ff6a00"     # laranja/racing
ACCENT_HOVER = "#cf5500"
DANGER = "#d23636"
DANGER_HOVER = "#a32626"
OK_COLOR = "#3ddc84"
BAD_COLOR = "#ff5555"
BG_DARK = "#101216"
PANEL = "#181b21"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title(f"{APP_TITLE} — {APP_VERSION}")
        self.geometry("820x640")
        self.minsize(760, 600)
        self.configure(fg_color=BG_DARK)

        self._connected_state: bool = False
        self._build_ui()
        self._refresh_status_async()
        # periodic status refresh
        self.after(5000, self._poll_status)

    # ---------- layout ----------

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, height=64)
        header.pack(side="top", fill="x")
        ctk.CTkLabel(
            header,
            text="SPLIT / SECOND  VPN",
            font=ctk.CTkFont(family="Helvetica", size=22, weight="bold"),
            text_color=ACCENT,
        ).pack(side="left", padx=20, pady=12)
        self.status_dot = ctk.CTkLabel(header, text="●", font=ctk.CTkFont(size=22), text_color=BAD_COLOR)
        self.status_dot.pack(side="right", padx=(0, 10), pady=12)
        self.status_label = ctk.CTkLabel(header, text="DESLIGADO", font=ctk.CTkFont(size=14, weight="bold"))
        self.status_label.pack(side="right", padx=(0, 4), pady=12)

        self.tabs = ctk.CTkTabview(self, fg_color=BG_DARK, segmented_button_selected_color=ACCENT,
                                   segmented_button_selected_hover_color=ACCENT_HOVER)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=12)
        self.tabs.add("Ligação")
        self.tabs.add("Configuração")
        self.tabs.add("Servidor")
        self.tabs.add("Diagnóstico")

        self._build_connect_tab(self.tabs.tab("Ligação"))
        self._build_setup_tab(self.tabs.tab("Configuração"))
        self._build_server_tab(self.tabs.tab("Servidor"))
        self._build_diag_tab(self.tabs.tab("Diagnóstico"))

        self.log_box = ctk.CTkTextbox(self, height=110, fg_color=PANEL, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_box.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")
        self._log(f"{APP_TITLE} {APP_VERSION} pronto. Plataforma: {platform.system()} {platform.release()}")
        if not tinc_installed():
            self._log("⚠  tinc não está instalado nesta máquina.")

    def _build_connect_tab(self, parent: ctk.CTkBaseClass) -> None:
        frame = ctk.CTkFrame(parent, fg_color=PANEL)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(frame, text="Estado da ligação", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=20, pady=(20, 4)
        )
        self.connect_status = ctk.CTkLabel(frame, text="Desligado", font=ctk.CTkFont(size=14))
        self.connect_status.pack(anchor="w", padx=20)

        info = ctk.CTkFrame(frame, fg_color=BG_DARK)
        info.pack(fill="x", padx=20, pady=14)
        self.lbl_name = ctk.CTkLabel(info, text=self._info_text(), justify="left",
                                     font=ctk.CTkFont(family="Consolas", size=12))
        self.lbl_name.pack(anchor="w", padx=12, pady=10)

        btn_row = ctk.CTkFrame(frame, fg_color=PANEL)
        btn_row.pack(fill="x", padx=20, pady=(4, 6))
        self.btn_connect = ctk.CTkButton(
            btn_row, text="LIGAR", height=48, width=180,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self.on_connect,
        )
        self.btn_connect.pack(side="left", padx=(0, 10))
        self.btn_disconnect = ctk.CTkButton(
            btn_row, text="DESLIGAR", height=48, width=180,
            fg_color=DANGER, hover_color=DANGER_HOVER,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self.on_disconnect,
        )
        self.btn_disconnect.pack(side="left")

        self.ping_label = ctk.CTkLabel(frame, text="Ping ao servidor: —", font=ctk.CTkFont(size=12))
        self.ping_label.pack(anchor="w", padx=20, pady=(16, 20))

    def _build_setup_tab(self, parent: ctk.CTkBaseClass) -> None:
        frame = ctk.CTkScrollableFrame(parent, fg_color=PANEL)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(frame, text="Dados do jogador", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=10, pady=(10, 4)
        )

        ctk.CTkLabel(frame, text="Nome do jogador (sem espaços)").pack(anchor="w", padx=10, pady=(8, 0))
        self.entry_name = ctk.CTkEntry(frame, width=320)
        self.entry_name.pack(anchor="w", padx=10)
        if self.settings.player_name:
            self.entry_name.insert(0, self.settings.player_name)

        ctk.CTkLabel(frame, text="Último octeto do IP VPN (10.20.0.X, 2-254)").pack(anchor="w", padx=10, pady=(10, 0))
        self.entry_octet = ctk.CTkEntry(frame, width=120)
        self.entry_octet.pack(anchor="w", padx=10)
        self.entry_octet.insert(0, str(self.settings.last_octet))

        btns = ctk.CTkFrame(frame, fg_color=PANEL)
        btns.pack(anchor="w", padx=4, pady=16)
        ctk.CTkButton(btns, text="Guardar configuração", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self.on_save_settings).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Criar ficheiros + gerar chaves",
                      command=self.on_setup_files).pack(side="left", padx=6)
        if IS_WINDOWS:
            ctk.CTkButton(btns, text="Adicionar regras de firewall",
                          command=self.on_firewall).pack(side="left", padx=6)

        ctk.CTkLabel(frame, text="O teu ficheiro de host (envia ao organizador):",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=10, pady=(18, 4))
        self.txt_my_host = ctk.CTkTextbox(frame, height=160, font=ctk.CTkFont(family="Consolas", size=11))
        self.txt_my_host.pack(fill="x", padx=10)

        host_btns = ctk.CTkFrame(frame, fg_color=PANEL)
        host_btns.pack(anchor="w", padx=4, pady=8)
        ctk.CTkButton(host_btns, text="Carregar do disco", command=self.on_load_my_host).pack(side="left", padx=6)
        ctk.CTkButton(host_btns, text="Copiar", command=self.on_copy_my_host).pack(side="left", padx=6)
        ctk.CTkButton(host_btns, text="Guardar em ficheiro…",
                      command=self.on_export_my_host).pack(side="left", padx=6)

    def _build_server_tab(self, parent: ctk.CTkBaseClass) -> None:
        frame = ctk.CTkScrollableFrame(parent, fg_color=PANEL)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(frame, text="Ficheiro hosts/server", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        ctk.CTkLabel(frame, text="Cola aqui o conteúdo enviado pelo organizador (chave + Address).",
                     wraplength=720, justify="left").pack(anchor="w", padx=10)

        self.txt_server = ctk.CTkTextbox(frame, height=200, font=ctk.CTkFont(family="Consolas", size=11))
        self.txt_server.pack(fill="x", padx=10, pady=8)

        ctk.CTkButton(frame, text="Aplicar ficheiro do servidor",
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self.on_apply_server).pack(anchor="w", padx=10, pady=(2, 12))

        ctk.CTkLabel(frame, text="Atualização automática do IP do servidor",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(10, 4))

        ctk.CTkLabel(frame, text="DuckDNS hostname (ex: meujogo.duckdns.org)").pack(anchor="w", padx=10, pady=(4, 0))
        self.entry_duck = ctk.CTkEntry(frame, width=360)
        self.entry_duck.pack(anchor="w", padx=10)
        self.entry_duck.insert(0, self.settings.duckdns_host)

        ctk.CTkLabel(frame, text="URL para descarregar hosts/server (opcional)").pack(anchor="w", padx=10, pady=(10, 0))
        self.entry_url = ctk.CTkEntry(frame, width=520)
        self.entry_url.pack(anchor="w", padx=10)
        self.entry_url.insert(0, self.settings.host_file_url)

        self.chk_auto_pull = ctk.CTkCheckBox(frame, text="Atualizar automaticamente antes de cada ligação")
        self.chk_auto_pull.pack(anchor="w", padx=10, pady=10)
        if self.settings.auto_pull_on_connect:
            self.chk_auto_pull.select()

        row = ctk.CTkFrame(frame, fg_color=PANEL)
        row.pack(anchor="w", padx=4, pady=6)
        ctk.CTkButton(row, text="Resolver DuckDNS agora", command=self.on_pull_duckdns).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Descarregar do URL", command=self.on_pull_url).pack(side="left", padx=6)

    def _build_diag_tab(self, parent: ctk.CTkBaseClass) -> None:
        frame = ctk.CTkFrame(parent, fg_color=PANEL)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(frame, text="Diagnóstico rápido", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=10, pady=(10, 6)
        )
        info = (
            f"Plataforma: {platform.system()} {platform.release()}\n"
            f"Python: {sys.version.split()[0]}\n"
            f"tinc binário: {tinc_binary()}\n"
            f"Pasta tinc: {tinc_dir()}\n"
            f"Pasta config app: {config_dir()}\n"
        )
        ctk.CTkLabel(frame, text=info, justify="left",
                     font=ctk.CTkFont(family="Consolas", size=11)).pack(anchor="w", padx=10)

        row = ctk.CTkFrame(frame, fg_color=PANEL)
        row.pack(anchor="w", padx=6, pady=10)
        ctk.CTkButton(row, text="Ping ao servidor (10.20.0.1)", command=self.on_ping).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Abrir pasta tinc", command=self.on_open_tinc).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Estado tinc", command=self._refresh_status_async).pack(side="left", padx=6)

    # ---------- helpers ----------

    def _log(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{ts}] {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _info_text(self) -> str:
        s = self.settings
        return (
            f"Jogador:   {s.player_name or '— não configurado —'}\n"
            f"IP VPN:    {s.vpn_ip}\n"
            f"Servidor:  {s.server_host or '— sem hosts/server —'}\n"
        )

    def _set_connected(self, on: bool) -> None:
        self._connected_state = on
        if on:
            self.status_dot.configure(text_color=OK_COLOR)
            self.status_label.configure(text="LIGADO")
            self.connect_status.configure(text=f"Ligado à VPN como {self.settings.vpn_ip}")
        else:
            self.status_dot.configure(text_color=BAD_COLOR)
            self.status_label.configure(text="DESLIGADO")
            self.connect_status.configure(text="Desligado")

    def _refresh_status_async(self) -> None:
        def worker() -> None:
            connected = tinc_status()
            self.after(0, lambda: self._set_connected(connected))
            if connected:
                ok = ping_server()
                self.after(0, lambda: self.ping_label.configure(
                    text=f"Ping ao servidor: {'OK' if ok else 'sem resposta'}"
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_status(self) -> None:
        self._refresh_status_async()
        self.after(5000, self._poll_status)

    # ---------- actions ----------

    def on_save_settings(self) -> None:
        name = self.entry_name.get().strip()
        try:
            octet = int(self.entry_octet.get().strip())
        except ValueError:
            messagebox.showerror(APP_TITLE, "Octeto inválido.")
            return
        if not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", name):
            messagebox.showerror(APP_TITLE, "Nome inválido (letras, números, _ ou -; 2-32 chars).")
            return
        if not 2 <= octet <= 254:
            messagebox.showerror(APP_TITLE, "Octeto fora do intervalo 2-254.")
            return
        self.settings.player_name = name
        self.settings.last_octet = octet
        self.settings.duckdns_host = self.entry_duck.get().strip() if hasattr(self, "entry_duck") else ""
        self.settings.host_file_url = self.entry_url.get().strip() if hasattr(self, "entry_url") else ""
        self.settings.auto_pull_on_connect = bool(self.chk_auto_pull.get()) if hasattr(self, "chk_auto_pull") else True
        self.settings.save()
        self.lbl_name.configure(text=self._info_text())
        self._log("Configuração guardada.")

    def on_setup_files(self) -> None:
        self.on_save_settings()
        if not self.settings.player_name:
            return

        def worker() -> None:
            try:
                ensure_tinc_dirs()
                write_tinc_conf(self.settings.player_name)
                write_host_self(self.settings.player_name, self.settings.last_octet)
                write_linux_scripts(self.settings.last_octet)
                self.after(0, lambda: self._log("Ficheiros base criados em " + str(tinc_dir())))
                ok, out = generate_keys()
                self.after(0, lambda: self._log(("Chaves geradas." if ok else f"Falha a gerar chaves: {out}")))
                # Após gerar, o tinc costuma anexar a chave pública ao host file próprio
                try:
                    content = read_self_host_file(self.settings.player_name)
                    self.after(0, lambda c=content: self._populate_my_host(c))
                except Exception as e:
                    self.after(0, lambda err=e: self._log(f"Não consegui ler o host file: {err}"))
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror(APP_TITLE, str(err)))

        threading.Thread(target=worker, daemon=True).start()

    def _populate_my_host(self, content: str) -> None:
        self.txt_my_host.delete("1.0", "end")
        self.txt_my_host.insert("1.0", content)

    def on_load_my_host(self) -> None:
        if not self.settings.player_name:
            messagebox.showerror(APP_TITLE, "Define primeiro o nome do jogador.")
            return
        try:
            self._populate_my_host(read_self_host_file(self.settings.player_name))
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Erro a ler: {e}")

    def on_copy_my_host(self) -> None:
        text = self.txt_my_host.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._log("Host file copiado para o clipboard.")

    def on_export_my_host(self) -> None:
        text = self.txt_my_host.get("1.0", "end").strip()
        if not text:
            return
        path = filedialog.asksaveasfilename(
            title="Guardar host file",
            defaultextension="",
            initialfile=self.settings.player_name or "player",
        )
        if not path:
            return
        Path(path).write_text(text + "\n", encoding="utf-8")
        self._log(f"Host file guardado em {path}")

    def on_firewall(self) -> None:
        def worker() -> None:
            ok, log = add_windows_firewall_rules()
            self.after(0, lambda: self._log("Firewall: " + ("OK" if ok else "falha — ver detalhes")))
            if log:
                self.after(0, lambda: self._log(log))
        threading.Thread(target=worker, daemon=True).start()

    def on_apply_server(self) -> None:
        text = self.txt_server.get("1.0", "end").strip()
        if not text:
            messagebox.showerror(APP_TITLE, "Cola o conteúdo do hosts/server primeiro.")
            return
        m = IP_RE.search(text)
        if not m:
            if not messagebox.askyesno(APP_TITLE,
                                       "O conteúdo não tem 'Address = ...'. Aplicar mesmo assim?"):
                return
        try:
            write_server_host_file(text + ("\n" if not text.endswith("\n") else ""))
            if m:
                self.settings.server_host = m.group(1)
                self.settings.save()
            self.lbl_name.configure(text=self._info_text())
            self._log("hosts/server escrito.")
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))

    def on_pull_duckdns(self) -> None:
        host = self.entry_duck.get().strip()
        if not host:
            messagebox.showerror(APP_TITLE, "Define um DuckDNS hostname.")
            return

        def worker() -> None:
            try:
                ip = resolve_duckdns(host)
                self.after(0, lambda: self._log(f"DuckDNS {host} -> {ip}"))
                try:
                    current = read_text_maybe_sudo(tinc_dir() / "hosts" / "server")
                except Exception:
                    current = ""
                if not current:
                    self.after(0, lambda: messagebox.showinfo(
                        APP_TITLE,
                        "Ainda não tens um hosts/server local. Cola-o primeiro no separador Servidor."
                    ))
                    return
                new = replace_address_in_host_file(current, ip)
                write_server_host_file(new)
                self.settings.server_host = ip
                self.settings.save()
                self.after(0, lambda: self.lbl_name.configure(text=self._info_text()))
                self.after(0, lambda: self._log("Address atualizado no hosts/server."))
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror(APP_TITLE, f"DuckDNS falhou: {err}"))

        threading.Thread(target=worker, daemon=True).start()

    def on_pull_url(self) -> None:
        url = self.entry_url.get().strip()
        if not url:
            messagebox.showerror(APP_TITLE, "Define um URL.")
            return

        def worker() -> None:
            try:
                content = fetch_url(url)
                self.after(0, lambda c=content: (self.txt_server.delete("1.0", "end"),
                                                 self.txt_server.insert("1.0", c)))
                self.after(0, lambda: self._log(f"Descarregado de {url}"))
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror(APP_TITLE, f"Download falhou: {err}"))

        threading.Thread(target=worker, daemon=True).start()

    def on_connect(self) -> None:
        if not self.settings.player_name:
            messagebox.showerror(APP_TITLE, "Configura primeiro nome e IP.")
            self.tabs.set("Configuração")
            return

        def worker() -> None:
            if self.settings.auto_pull_on_connect and self.settings.duckdns_host:
                try:
                    ip = resolve_duckdns(self.settings.duckdns_host)
                    current = read_text_maybe_sudo(tinc_dir() / "hosts" / "server")
                    new = replace_address_in_host_file(current, ip)
                    if new != current:
                        write_server_host_file(new)
                        self.settings.server_host = ip
                        self.settings.save()
                        self.after(0, lambda: self._log(f"hosts/server atualizado (DuckDNS -> {ip})"))
                except Exception as e:
                    self.after(0, lambda err=e: self._log(f"Aviso: auto-update falhou ({err})"))

            self.after(0, lambda: self._log("A iniciar tinc…"))
            ok, log = start_tinc()
            if log:
                self.after(0, lambda l=log: self._log(l))
            if not ok:
                self.after(0, lambda: messagebox.showerror(APP_TITLE, "tinc não arrancou. Vê o log."))
                return
            if IS_WINDOWS:
                ok2, log2 = set_windows_tap_ip(self.settings.vpn_ip)
                if log2:
                    self.after(0, lambda l=log2: self._log(l))
                self.after(0, lambda: self._log("IP TAP definido" if ok2 else "Falha a definir IP TAP"))
            time.sleep(2)
            self.after(0, self._refresh_status_async)

        threading.Thread(target=worker, daemon=True).start()

    def on_disconnect(self) -> None:
        def worker() -> None:
            self.after(0, lambda: self._log("A parar tinc…"))
            ok, log = stop_tinc()
            if log:
                self.after(0, lambda l=log: self._log(l))
            self.after(0, lambda: self._log("Desligado" if ok else "Falha a parar"))
            self.after(0, self._refresh_status_async)

        threading.Thread(target=worker, daemon=True).start()

    def on_ping(self) -> None:
        def worker() -> None:
            ok = ping_server()
            self.after(0, lambda: self.ping_label.configure(
                text=f"Ping ao servidor: {'OK' if ok else 'sem resposta'}"
            ))
            self.after(0, lambda: self._log(f"Ping {SERVER_VPN_IP}: {'OK' if ok else 'falhou'}"))

        threading.Thread(target=worker, daemon=True).start()

    def on_open_tinc(self) -> None:
        path = tinc_dir()
        try:
            if IS_WINDOWS:
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            self._log(f"Não consegui abrir {path}: {e}")


def main() -> int:
    if IS_WINDOWS and not is_admin():
        # Re-execute elevated; this call exits the current process.
        reexec_as_admin_windows()
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
