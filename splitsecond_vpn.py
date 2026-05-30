"""Split/Second VPN — cliente GUI para a rede tinc 'splitsecond'.

Interface wizard com passos numerados, detecção automática de estado
e navegação livre. Cross-platform (Windows + Linux).
"""

from __future__ import annotations

import csv
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from dataclasses import dataclass, asdict
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk


NETWORK_NAME = "splitsecond"
WINDOWS_SERVICE_NAME = f"tinc.{NETWORK_NAME}"  # nome do serviço criado por 'tinc start'
SERVER_VPN_IP = "10.20.0.1"
VPN_SUBNET_MASK = "255.255.255.0"
VPN_CIDR_BITS = 24
TINC_PORT = 11655

APP_TITLE = "Split/Second VPN"
APP_VERSION = "1.0.3"

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
    server_host: str = ""        # Address actual no hosts/server
    server_public_ip: str = ""   # IP público inserido manualmente
    host_file_url: str = ""      # opcional: URL para descarregar hosts/server
    auto_update_ip: bool = True  # actualizar Address antes de ligar
    setup_done: bool = False     # ficheiros + chaves gerados com sucesso
    host_file_sent: bool = False # utilizador confirmou envio do host file

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
    try:
        if IS_WINDOWS:
            # Específico da nossa rede: o 'tinc start' regista um serviço
            # chamado tinc.<rede>. Verificar 'tincd.exe' genérico dava falsos
            # positivos quando havia outro tincd ou um serviço deixado a correr.
            rc, out, _ = run_cmd(["sc", "query", WINDOWS_SERVICE_NAME], timeout=10)
            return rc == 0 and "RUNNING" in out.upper()
        rc, out, _ = run_cmd(["pgrep", "-a", "tincd"], timeout=5)
        return rc == 0 and NETWORK_NAME in out
    except Exception:
        return False


def ensure_tinc_dirs() -> None:
    d = tinc_dir()
    (d / "hosts").mkdir(parents=True, exist_ok=True)


def write_text_maybe_sudo(path: Path, content: str, *, executable: bool = False) -> None:
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
    run_cmd(sp + ["mkdir", "-p", str(path.parent)], check=True)
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
        if rc == 0:
            # 'tinc start' regista o serviço como arranque automático; passá-lo a
            # manual para que um reboot não reconecte sozinho (e mostre "ligado").
            run_cmd(["sc", "config", WINDOWS_SERVICE_NAME, "start=", "demand"], timeout=10)
        return rc == 0, (out + err).strip()
    sp = sudo_prefix()
    rc, out, err = run_cmd(sp + [tincd_binary(), "-n", NETWORK_NAME], timeout=20)
    return rc == 0, (out + err).strip()


def stop_tinc() -> tuple[bool, str]:
    if IS_WINDOWS:
        # Paragem graciosa via tinc (best-effort — pode faltar o tinc.exe), mas a
        # remoção do serviço é o que garante que não volta a arrancar no boot.
        rc, out, err = run_cmd([tinc_binary(), "-n", NETWORK_NAME, "stop"], timeout=20)
        run_cmd(["sc", "stop", WINDOWS_SERVICE_NAME], timeout=15)
        run_cmd(["sc", "delete", WINDOWS_SERVICE_NAME], timeout=15)
        # Sucesso = o serviço já não está a correr (independente do tinc.exe).
        return (not tinc_status()), (out + err).strip()
    sp = sudo_prefix()
    rc, out, err = run_cmd(sp + ["pkill", "-f", f"tincd.*{NETWORK_NAME}"], timeout=10)
    return rc in (0, 1), (out + err).strip()


def find_windows_tap_name() -> str:
    """Nome da ligação do adaptador TAP-Windows (ex.: 'Ethernet 2'), ou '' se não existir.

    O instalador do TAP cria o dispositivo 'tap0901' mas a *ligação* fica com um
    nome automático ('Ethernet 2', etc.). Detectamos pela descrição do driver
    ('TAP-Windows Adapter V9') em vez de assumir que se chama 'tap0901'.
    """
    if not IS_WINDOWS:
        return ""
    # getmac é nativo e rápido; a coluna 'Network Adapter' tem a descrição do driver.
    rc, out, _ = run_cmd(["getmac", "/v", "/fo", "csv"], timeout=15)
    if rc == 0 and out.strip():
        try:
            for row in csv.reader(out.splitlines()):
                if len(row) >= 2 and "tap-win" in row[1].lower():
                    return row[0].strip()
        except Exception:
            pass
    # Fallback: Get-NetAdapter apanha também adaptadores desligados (sem media).
    ps = ("Get-NetAdapter | Where-Object { $_.InterfaceDescription -like '*TAP-Win*' }"
          " | Select-Object -First 1 -ExpandProperty Name")
    rc, out, _ = run_cmd(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=20)
    if rc == 0 and out.strip():
        return out.strip().splitlines()[0].strip()
    return ""


def set_windows_tap_ip(ip: str) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return True, ""
    name = find_windows_tap_name()
    if not name:
        return False, ("Adaptador TAP não encontrado — instala o driver TAP (Passo 2) "
                       "e tenta de novo.")
    rc, out, err = run_cmd(
        ["netsh", "interface", "ip", "set", "address", name, "static", ip, VPN_SUBNET_MASK],
        timeout=30,
    )
    msg = (out + err).strip()
    if rc != 0:
        return False, msg or f"netsh falhou (código {rc}) ao configurar '{name}'."
    return True, f"IP {ip} definido em '{name}'."


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
    if IP_RE.search(content):
        return IP_RE.sub(f"Address = {new_addr}", content, count=1)
    lines = content.splitlines()
    lines.insert(0, f"Address = {new_addr}")
    return "\n".join(lines) + ("\n" if not content.endswith("\n") else "")


def fetch_url(url: str, timeout: int = 8) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_TITLE}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ----------------------------- step helpers -----------------------------

def linux_install_cmd() -> str:
    try:
        txt = Path("/etc/os-release").read_text().lower()
    except Exception:
        return "sudo apt install tinc -y"
    for keywords, cmd in [
        (("arch", "cachyos", "manjaro", "endeavour"), "sudo pacman -S tinc"),
        (("fedora", "rhel", "centos", "rocky", "alma"), "sudo dnf install tinc"),
        (("opensuse",), "sudo zypper install tinc"),
        (("bazzite",), "sudo rpm-ostree install tinc  # requer reinício"),
    ]:
        if any(k in txt for k in keywords):
            return cmd
    return "sudo apt install tinc -y"


def tinc_version() -> str:
    rc, out, err = run_cmd([tincd_binary(), "--version"], timeout=5)
    if rc == 0:
        return (out + err).split("\n")[0].strip()
    return ""


def check_tap_installed() -> bool:
    """Windows: True se existir um adaptador TAP-Windows (independente do nome)."""
    if not IS_WINDOWS:
        return True
    try:
        return bool(find_windows_tap_name())
    except Exception:
        return False


def step_config_done(player_name: str, setup_done_flag: bool = False) -> bool:
    if setup_done_flag:
        return True
    if not player_name:
        return False
    try:
        d = tinc_dir()
        if not (d / "tinc.conf").exists():
            return False
        content = (d / "hosts" / player_name).read_text(encoding="utf-8", errors="replace")
        return "BEGIN" in content
    except Exception:
        return False


def step_server_done() -> bool:
    try:
        text = (tinc_dir() / "hosts" / "server").read_text(encoding="utf-8", errors="replace")
        return bool(IP_RE.search(text))
    except Exception:
        return False


# ----------------------------- auto-install helpers -----------------------------

def install_tinc_linux() -> tuple[bool, str]:
    """Instala tinc via o gestor de pacotes detectado."""
    sp = sudo_prefix()
    if not sp:
        return False, "Sem pkexec/sudo disponível. Instala manualmente."
    try:
        txt = Path("/etc/os-release").read_text().lower()
    except Exception:
        txt = ""
    for keywords, args in [
        (("bazzite",), None),
        (("arch", "cachyos", "manjaro", "endeavour"), ["pacman", "-S", "--noconfirm", "tinc"]),
        (("fedora", "rhel", "centos", "rocky", "alma"),  ["dnf", "install", "-y", "tinc"]),
        (("opensuse",), ["zypper", "--non-interactive", "install", "tinc"]),
    ]:
        if any(k in txt for k in keywords):
            if args is None:
                return False, (
                    "Bazzite usa rpm-ostree e requer reinício após a instalação.\n"
                    "Corre manualmente:  sudo rpm-ostree install tinc\ne reinicia o sistema."
                )
            rc, out, err = run_cmd(sp + args, timeout=180)
            return rc == 0, (out + err).strip()
    # Default: apt
    env_prefix = ["env", "DEBIAN_FRONTEND=noninteractive"] if shutil.which("apt") else []
    rc, out, err = run_cmd(sp + env_prefix + ["apt", "install", "-y", "tinc"], timeout=180)
    return rc == 0, (out + err).strip()


def install_tinc_windows() -> tuple[bool, str]:
    """Descarrega e instala tinc 1.1pre18 silenciosamente no Windows."""
    import tempfile
    url = "https://www.tinc-vpn.org/packages/windows/tinc-1.1pre18-install.exe"
    tmp = Path(tempfile.gettempdir()) / "tinc-1.1pre18-install.exe"
    try:
        urllib.request.urlretrieve(url, str(tmp))
    except Exception as e:
        return False, f"Falha ao descarregar o instalador: {e}"
    # /S = NSIS silent install
    rc, out, err = run_cmd([str(tmp), "/S"], timeout=180)
    msg = (out + err).strip() or ("Instalação concluída." if rc == 0 else f"Instalador retornou {rc}")
    return rc == 0, msg


def install_tap_driver() -> tuple[bool, str]:
    """Instala o driver TAP no Windows (requer modo administrador)."""
    if not IS_WINDOWS:
        return True, ""
    base = Path(r"C:\Program Files\tinc\tap-win64")
    tapinstall = base / "tapinstall.exe"
    inf = base / "OemWin2k.inf"
    if not tapinstall.exists():
        return False, (
            "tapinstall.exe não encontrado.\n"
            "Instala o tinc primeiro (Passo 1) e tenta de novo."
        )
    rc, out, err = run_cmd([str(tapinstall), "install", str(inf), "tap0901"], timeout=60)
    return rc == 0, (out + err).strip() or ("Driver TAP instalado." if rc == 0 else f"Erro {rc}")


# ----------------------------- GUI -----------------------------

ACCENT = "#ff6a00"
ACCENT_HOVER = "#cf5500"
DANGER = "#d23636"
DANGER_HOVER = "#a32626"
OK_COLOR = "#3ddc84"
BAD_COLOR = "#ff5555"
WARN_COLOR = "#ffbb33"
BG_DARK = "#101216"
PANEL = "#181b21"
SIDEBAR_W = 196

_STEP_DEFS: list[tuple[str, str, bool]] = [
    # (id, title, windows_only)
    ("tinc",     "Instalar tinc",         False),
    ("tap",      "Driver TAP",            True),
    ("config",   "Configurar jogador",    False),
    ("server",   "Ficheiro do servidor",  False),
    ("hostfile", "Enviar host file",      False),
    ("connect",  "Ligar à VPN",           False),
]


class App(ctk.CTk):

    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title(f"{APP_TITLE} — {APP_VERSION}")
        self.geometry("940x700")
        self.minsize(820, 580)
        self.configure(fg_color=BG_DARK)

        # Build filtered step list
        self._steps: list[dict] = []
        for sid, title, wo in _STEP_DEFS:
            if wo and not IS_WINDOWS:
                continue
            self._steps.append({"id": sid, "title": title})
        for i, s in enumerate(self._steps):
            s["num"] = i + 1

        self._current: int = 0
        self._connected_state: bool = False
        self._step_frames: dict[str, ctk.CTkScrollableFrame] = {}
        self._sidebar_items: list[dict] = []

        self._build_ui()
        self._log(f"{APP_TITLE} {APP_VERSION} — {platform.system()} {platform.release()}")
        if not tinc_installed():
            self._log("⚠  tinc não instalado nesta máquina.")
        self.after(150, self._auto_detect_step)
        self.after(5000, self._poll_status)

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        # ── Header ──────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, height=54)
        hdr.pack(side="top", fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr, text="SPLIT / SECOND  VPN",
            font=ctk.CTkFont(family="Helvetica", size=20, weight="bold"),
            text_color=ACCENT,
        ).pack(side="left", padx=20, pady=10)
        self.status_dot = ctk.CTkLabel(hdr, text="●", font=ctk.CTkFont(size=20), text_color=BAD_COLOR)
        self.status_dot.pack(side="right", padx=(0, 16))
        self.status_label = ctk.CTkLabel(hdr, text="DESLIGADO", font=ctk.CTkFont(size=13, weight="bold"))
        self.status_label.pack(side="right")

        # ── Body ─────────────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        body.pack(fill="both", expand=True)

        # Sidebar
        sidebar = ctk.CTkFrame(body, fg_color=PANEL, width=SIDEBAR_W, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ctk.CTkLabel(
            sidebar, text="PASSOS",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#555",
        ).pack(anchor="w", padx=16, pady=(16, 8))
        for i, step in enumerate(self._steps):
            self._sidebar_items.append(self._build_sidebar_item(sidebar, step, i))

        # Thin divider
        ctk.CTkFrame(body, fg_color="#252830", width=1, corner_radius=0).pack(side="left", fill="y")

        # Right panel
        right = ctk.CTkFrame(body, fg_color=BG_DARK, corner_radius=0)
        right.pack(side="left", fill="both", expand=True)
        right.grid_rowconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=0)
        right.grid_columnconfigure(0, weight=1)

        # Content host — all step frames go here, shown one at a time
        self._content_host = ctk.CTkFrame(right, fg_color=BG_DARK, corner_radius=0)
        self._content_host.grid(row=0, column=0, sticky="nsew")
        self._content_host.grid_rowconfigure(0, weight=1)
        self._content_host.grid_columnconfigure(0, weight=1)

        # Build all step frames
        self._build_step_tinc()
        if IS_WINDOWS:
            self._build_step_tap()
        self._build_step_config()
        self._build_step_server()
        self._build_step_hostfile()
        self._build_step_connect()

        # Navigation bar
        nav = ctk.CTkFrame(right, fg_color=PANEL, height=52, corner_radius=0)
        nav.grid(row=1, column=0, sticky="ew")
        nav.pack_propagate(False)
        self.btn_prev = ctk.CTkButton(
            nav, text="← Anterior", width=130,
            fg_color="#2b2d35", hover_color="#3a3d47",
            command=self.prev_step,
        )
        self.btn_prev.pack(side="left", padx=14, pady=10)
        self.lbl_counter = ctk.CTkLabel(nav, text="", font=ctk.CTkFont(size=12))
        self.lbl_counter.pack(side="left", expand=True)
        self.btn_next = ctk.CTkButton(
            nav, text="Seguinte →", width=130,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self.next_step,
        )
        self.btn_next.pack(side="right", padx=14, pady=10)

        # Log box
        self.log_box = ctk.CTkTextbox(
            self, height=88, fg_color=PANEL,
            font=ctk.CTkFont(family="Consolas", size=11), corner_radius=0,
        )
        self.log_box.pack(side="bottom", fill="x")
        self.log_box.configure(state="disabled")

        self.go_to_step(0)

    # ------------------------------------------------------------------ sidebar

    def _build_sidebar_item(self, parent: ctk.CTkFrame, step: dict, idx: int) -> dict:
        frame = ctk.CTkFrame(parent, fg_color="transparent", cursor="hand2", height=46)
        frame.pack(fill="x", padx=8, pady=2)
        frame.pack_propagate(False)

        circle = ctk.CTkFrame(frame, width=28, height=28, corner_radius=14)
        circle.pack(side="left", padx=(10, 10), pady=9)
        circle.pack_propagate(False)
        num_lbl = ctk.CTkLabel(circle, text=str(step["num"]),
                                font=ctk.CTkFont(size=11, weight="bold"))
        num_lbl.pack(expand=True)

        title_lbl = ctk.CTkLabel(frame, text=step["title"],
                                  font=ctk.CTkFont(size=12), anchor="w")
        title_lbl.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def _click(e, i=idx):
            self.go_to_step(i)

        for w in (frame, circle, num_lbl, title_lbl):
            w.bind("<Button-1>", _click)

        return {"frame": frame, "circle": circle, "num_lbl": num_lbl, "title_lbl": title_lbl}

    def _update_sidebar(self) -> None:
        for i, (step, item) in enumerate(zip(self._steps, self._sidebar_items)):
            is_cur = i == self._current
            is_done = self._is_step_complete(step["id"])
            if is_cur:
                item["circle"].configure(fg_color=ACCENT)
                item["num_lbl"].configure(text=str(step["num"]), text_color="white")
                item["title_lbl"].configure(
                    text_color="white", font=ctk.CTkFont(size=12, weight="bold"))
                item["frame"].configure(fg_color="#252830")
            elif is_done:
                item["circle"].configure(fg_color="#1d3d2a")
                item["num_lbl"].configure(text="✓", text_color=OK_COLOR)
                item["title_lbl"].configure(
                    text_color=OK_COLOR, font=ctk.CTkFont(size=12))
                item["frame"].configure(fg_color="transparent")
            else:
                item["circle"].configure(fg_color="#252830")
                item["num_lbl"].configure(text=str(step["num"]), text_color="#666")
                item["title_lbl"].configure(
                    text_color="#666", font=ctk.CTkFont(size=12))
                item["frame"].configure(fg_color="transparent")

    def _is_step_complete(self, step_id: str) -> bool:
        try:
            if step_id == "tinc":     return tinc_installed()
            if step_id == "tap":      return check_tap_installed()
            if step_id == "config":   return step_config_done(
                self.settings.player_name, self.settings.setup_done)
            if step_id == "server":   return step_server_done()
            if step_id == "hostfile": return self.settings.host_file_sent
            if step_id == "connect":  return self._connected_state
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------ step frames

    def _make_step_frame(self, step_id: str) -> ctk.CTkScrollableFrame:
        f = ctk.CTkScrollableFrame(self._content_host, fg_color=BG_DARK, corner_radius=0)
        f.grid(row=0, column=0, sticky="nsew")
        f.grid_remove()
        self._step_frames[step_id] = f
        return f

    def _step_header(self, parent: ctk.CTkBaseClass,
                     num: int, title: str, subtitle: str = "") -> None:
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", padx=28, pady=(22, 6))
        ctk.CTkLabel(hdr, text=f"Passo {num}",
                     font=ctk.CTkFont(size=11), text_color="#555").pack(anchor="w")
        ctk.CTkLabel(hdr, text=title,
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(hdr, text=subtitle, wraplength=640, justify="left",
                         font=ctk.CTkFont(size=12), text_color="#888").pack(anchor="w", pady=(2, 0))
        ctk.CTkFrame(parent, fg_color="#252830", height=1, corner_radius=0).pack(
            fill="x", padx=28, pady=(8, 4))

    def _card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=8)
        f.pack(fill="x", padx=28, pady=8)
        return f

    # ---- Step 1 — Instalar tinc ----

    def _build_step_tinc(self) -> None:
        step = next(s for s in self._steps if s["id"] == "tinc")
        frame = self._make_step_frame("tinc")
        self._step_header(frame, step["num"], "Instalar tinc",
                          "O tinc é o software de VPN que liga todos os jogadores em modo Layer 2.")

        status_card = self._card(frame)
        self.tinc_status_lbl = ctk.CTkLabel(
            status_card, text="A verificar…",
            font=ctk.CTkFont(size=13), justify="left")
        self.tinc_status_lbl.pack(anchor="w", padx=18, pady=(14, 6))
        btn_row_t = ctk.CTkFrame(status_card, fg_color="transparent")
        btn_row_t.pack(anchor="w", padx=14, pady=(2, 14))
        ctk.CTkButton(btn_row_t, text="Verificar", width=120,
                       command=self._refresh_tinc_step).pack(side="left", padx=4)
        install_lbl = "Instalar automaticamente"
        ctk.CTkButton(btn_row_t, text=install_lbl,
                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                       command=self.on_install_tinc).pack(side="left", padx=4)

        inst_card = self._card(frame)
        if IS_WINDOWS:
            ctk.CTkLabel(inst_card, text="Windows",
                         font=ctk.CTkFont(size=13, weight="bold")).pack(
                anchor="w", padx=18, pady=(14, 4))
            ctk.CTkLabel(
                inst_card,
                text="⚠  Usar obrigatoriamente a versão 1.1pre18.\n"
                     "   O tinc 1.0.x não funciona no Windows 10/11.",
                text_color=WARN_COLOR, justify="left", wraplength=580,
            ).pack(anchor="w", padx=18, pady=(0, 8))
            ctk.CTkButton(
                inst_card, text="Descarregar tinc 1.1pre18",
                fg_color=ACCENT, hover_color=ACCENT_HOVER,
                command=lambda: webbrowser.open(
                    "https://www.tinc-vpn.org/packages/windows/tinc-1.1pre18-install.exe"),
            ).pack(anchor="w", padx=18, pady=(0, 14))
        else:
            cmd = linux_install_cmd()
            ctk.CTkLabel(inst_card, text="Linux",
                         font=ctk.CTkFont(size=13, weight="bold")).pack(
                anchor="w", padx=18, pady=(14, 4))
            cmd_box = ctk.CTkTextbox(inst_card, height=38,
                                      font=ctk.CTkFont(family="Consolas", size=12),
                                      fg_color=BG_DARK)
            cmd_box.pack(fill="x", padx=18, pady=(0, 4))
            cmd_box.insert("1.0", cmd)
            cmd_box.configure(state="disabled")
            ctk.CTkButton(inst_card, text="Copiar comando", width=150,
                           command=lambda c=cmd: (
                               self.clipboard_clear(), self.clipboard_append(c),
                               self._log(f"Copiado: {c}"))).pack(
                anchor="w", padx=18, pady=(0, 14))

    def _refresh_tinc_step(self) -> None:
        def worker() -> None:
            ok = tinc_installed()
            if ok:
                ver = tinc_version()
                msg = f"✓  tinc encontrado: {tincd_binary()}"
                if ver:
                    msg += f"\n    {ver}"
                color = OK_COLOR
            else:
                msg = ("✗  tinc não encontrado.\n"
                       "   Instala-o com o comando/link abaixo e clica 'Verificar novamente'.")
                color = BAD_COLOR
            self.after(0, lambda: self.tinc_status_lbl.configure(text=msg, text_color=color))
            self.after(0, self._update_sidebar)
        threading.Thread(target=worker, daemon=True).start()

    # ---- Step 2 — Driver TAP (Windows only) ----

    def _build_step_tap(self) -> None:
        if not any(s["id"] == "tap" for s in self._steps):
            return
        step = next(s for s in self._steps if s["id"] == "tap")
        frame = self._make_step_frame("tap")
        self._step_header(frame, step["num"], "Driver TAP (Windows)",
                          "O tinc precisa de um adaptador TAP virtual para criar a interface de rede VPN.")

        status_card = self._card(frame)
        self.tap_status_lbl = ctk.CTkLabel(status_card, text="A verificar…",
                                            font=ctk.CTkFont(size=13), justify="left")
        self.tap_status_lbl.pack(anchor="w", padx=18, pady=(14, 6))
        btn_row_tap = ctk.CTkFrame(status_card, fg_color="transparent")
        btn_row_tap.pack(anchor="w", padx=14, pady=(2, 14))
        ctk.CTkButton(btn_row_tap, text="Verificar", width=120,
                       command=self._refresh_tap_step).pack(side="left", padx=4)
        ctk.CTkButton(btn_row_tap, text="Instalar driver TAP",
                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                       command=self.on_install_tap).pack(side="left", padx=4)

        inst_card = self._card(frame)
        ctk.CTkLabel(inst_card, text="Como instalar",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=18, pady=(14, 6))
        ctk.CTkLabel(inst_card,
                     text="1. Abre uma Linha de Comandos como Administrador\n"
                          "2. Corre:",
                     justify="left", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=18, pady=(0, 4))

        cmds = ('cd "C:\\Program Files\\tinc\\tap-win64"\n'
                'tapinstall.exe install OemWin2k.inf tap0901')
        cmd_box = ctk.CTkTextbox(inst_card, height=52,
                                  font=ctk.CTkFont(family="Consolas", size=11), fg_color=BG_DARK)
        cmd_box.pack(fill="x", padx=18, pady=(0, 4))
        cmd_box.insert("1.0", cmds)
        cmd_box.configure(state="disabled")
        ctk.CTkButton(inst_card, text="Copiar", width=100,
                       command=lambda: (self.clipboard_clear(), self.clipboard_append(cmds),
                                        self._log("Comandos TAP copiados."))).pack(
            anchor="w", padx=18, pady=(0, 8))

        ctk.CTkLabel(inst_card,
                     text="3. Em 'Ligações de Rede', confirma que o adaptador se chama 'tap0901'.\n"
                          "   Se tiver outro nome:",
                     justify="left", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=18, pady=(4, 4))
        rename = 'netsh interface set interface name="NOME_ACTUAL" newname="tap0901"'
        r_box = ctk.CTkTextbox(inst_card, height=36,
                                font=ctk.CTkFont(family="Consolas", size=11), fg_color=BG_DARK)
        r_box.pack(fill="x", padx=18, pady=(0, 14))
        r_box.insert("1.0", rename)
        r_box.configure(state="disabled")

    def _refresh_tap_step(self) -> None:
        def worker() -> None:
            try:
                ok = check_tap_installed()
                msg = "✓  Adaptador TAP encontrado." if ok else "✗  Adaptador TAP não encontrado."
                color = OK_COLOR if ok else BAD_COLOR
                self.after(0, lambda: self.tap_status_lbl.configure(text=msg, text_color=color))
                self.after(0, self._update_sidebar)
            except Exception as e:
                self.after(0, lambda: self.tap_status_lbl.configure(
                    text=f"Erro ao verificar TAP: {e}", text_color=BAD_COLOR))
        threading.Thread(target=worker, daemon=True).start()

    # ---- Step 3 — Configurar jogador ----

    def _build_step_config(self) -> None:
        step = next(s for s in self._steps if s["id"] == "config")
        frame = self._make_step_frame("config")
        self._step_header(frame, step["num"], "Configurar jogador",
                          "Define o teu nome e IP na rede VPN, depois gera os ficheiros de configuração e chaves.")

        form_card = self._card(frame)

        ctk.CTkLabel(form_card, text="Nome do jogador",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=18, pady=(14, 2))
        ctk.CTkLabel(form_card, text="Sem espaços · letras, números, _ ou - · 2 a 32 caracteres",
                     font=ctk.CTkFont(size=11), text_color="#777").pack(anchor="w", padx=18)
        self.entry_name = ctk.CTkEntry(form_card, width=300, placeholder_text="ex: Simao")
        self.entry_name.pack(anchor="w", padx=18, pady=(6, 14))
        if self.settings.player_name:
            self.entry_name.insert(0, self.settings.player_name)

        ctk.CTkLabel(form_card, text="IP VPN — último octeto  (10.20.0.X)",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=18, pady=(0, 2))
        ctk.CTkLabel(form_card, text="O organizador atribui um número de 2 a 254 a cada jogador.",
                     font=ctk.CTkFont(size=11), text_color="#777").pack(anchor="w", padx=18)
        ip_row = ctk.CTkFrame(form_card, fg_color="transparent")
        ip_row.pack(anchor="w", padx=18, pady=(6, 14))
        ctk.CTkLabel(ip_row, text="10.20.0.",
                     font=ctk.CTkFont(family="Consolas", size=13)).pack(side="left")
        self.entry_octet = ctk.CTkEntry(ip_row, width=72, placeholder_text="2")
        self.entry_octet.pack(side="left")
        self.entry_octet.insert(0, str(self.settings.last_octet))

        # Estado dos ficheiros
        self.config_state_lbl = ctk.CTkLabel(form_card, text="",
                                              font=ctk.CTkFont(size=12), justify="left")
        self.config_state_lbl.pack(anchor="w", padx=18, pady=(2, 6))

        btn_row = ctk.CTkFrame(form_card, fg_color="transparent")
        btn_row.pack(anchor="w", padx=14, pady=(2, 14))
        ctk.CTkButton(btn_row, text="Criar ficheiros + gerar chaves",
                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                       command=self.on_setup_files).pack(side="left", padx=4)
        if IS_WINDOWS:
            ctk.CTkButton(btn_row, text="Regras de firewall",
                           command=self.on_firewall).pack(side="left", padx=4)

    def _refresh_config_step(self) -> None:
        name = self.settings.player_name
        if not name:
            self.config_state_lbl.configure(
                text="Preenche o nome e IP e clica o botão.", text_color="#666")
            return
        done = step_config_done(name, self.settings.setup_done)
        if done:
            self.config_state_lbl.configure(
                text=f"✓  Ficheiros e chaves prontos para '{name}' ({self.settings.vpn_ip})",
                text_color=OK_COLOR)
        else:
            d = tinc_dir()
            flags = []
            try:
                exists_conf = (d / "tinc.conf").exists()
            except Exception:
                exists_conf = False
            try:
                host_text = (d / "hosts" / name).read_text(errors="replace")
                exists_host = True
                has_key = "BEGIN" in host_text
            except Exception:
                exists_host = False
                has_key = False
            flags.append(("✓" if exists_conf else "○") + " tinc.conf")
            flags.append(("✓" if exists_host else "○") + f" hosts/{name}")
            flags.append(("✓" if has_key else "○") + " chaves")
            self.config_state_lbl.configure(
                text="   ".join(flags), text_color="#aaa")

    # ---- Step 4 — Ficheiro do servidor ----

    def _build_step_server(self) -> None:
        step = next(s for s in self._steps if s["id"] == "server")
        frame = self._make_step_frame("server")
        self._step_header(frame, step["num"], "Ficheiro do servidor",
                          "Cola o conteúdo do ficheiro hosts/server que o organizador te enviou.")

        paste_card = self._card(frame)
        ctk.CTkLabel(paste_card, text="Conteúdo do hosts/server  (chave pública + Address + Port):",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=18, pady=(14, 4))
        self.txt_server = ctk.CTkTextbox(paste_card, height=170,
                                          font=ctk.CTkFont(family="Consolas", size=11))
        self.txt_server.pack(fill="x", padx=18, pady=(0, 6))
        self.server_state_lbl = ctk.CTkLabel(paste_card, text="",
                                              font=ctk.CTkFont(size=12), justify="left")
        self.server_state_lbl.pack(anchor="w", padx=18)
        ctk.CTkButton(paste_card, text="Aplicar ficheiro do servidor",
                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                       command=self.on_apply_server).pack(anchor="w", padx=18, pady=(8, 14))

        ip_card = self._card(frame)
        ctk.CTkLabel(ip_card, text="IP público do servidor",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=18, pady=(14, 2))
        ctk.CTkLabel(ip_card,
                     text="Quando o IP do servidor mudar, pede-o ao organizador e actualiza aqui.",
                     font=ctk.CTkFont(size=11), text_color="#777",
                     wraplength=580).pack(anchor="w", padx=18, pady=(0, 6))
        ip_row = ctk.CTkFrame(ip_card, fg_color="transparent")
        ip_row.pack(anchor="w", padx=18, pady=(0, 6))
        self.entry_public_ip = ctk.CTkEntry(ip_row, width=210,
                                             placeholder_text="ex: 203.0.113.42")
        self.entry_public_ip.pack(side="left", padx=(0, 8))
        if self.settings.server_public_ip:
            self.entry_public_ip.insert(0, self.settings.server_public_ip)
        ctk.CTkButton(ip_row, text="Aplicar IP", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                       command=self.on_apply_public_ip).pack(side="left")
        self.chk_auto_update_ip = ctk.CTkCheckBox(
            ip_card, text="Actualizar Address automaticamente antes de cada ligação")
        self.chk_auto_update_ip.pack(anchor="w", padx=18, pady=(6, 14))
        if self.settings.auto_update_ip:
            self.chk_auto_update_ip.select()

        url_card = self._card(frame)
        ctk.CTkLabel(url_card, text="Descarregar hosts/server de URL  (opcional)",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=18, pady=(14, 4))
        url_row = ctk.CTkFrame(url_card, fg_color="transparent")
        url_row.pack(anchor="w", padx=18, pady=(0, 14))
        self.entry_url = ctk.CTkEntry(url_row, width=380, placeholder_text="https://…")
        self.entry_url.pack(side="left", padx=(0, 8))
        if self.settings.host_file_url:
            self.entry_url.insert(0, self.settings.host_file_url)
        ctk.CTkButton(url_row, text="Descarregar",
                       command=self.on_pull_url).pack(side="left")

    def _refresh_server_step(self) -> None:
        done = step_server_done()
        if done:
            try:
                text = (tinc_dir() / "hosts" / "server").read_text(errors="replace")
                m = IP_RE.search(text)
                addr = m.group(1) if m else "?"
                msg, color = f"✓  hosts/server aplicado  —  Address = {addr}", OK_COLOR
            except Exception:
                msg, color = "✓  hosts/server presente", OK_COLOR
        else:
            msg, color = "○  hosts/server não encontrado ou sem Address", "#888"
        self.server_state_lbl.configure(text=msg, text_color=color)

    # ---- Step 5 — Enviar host file ----

    def _build_step_hostfile(self) -> None:
        step = next(s for s in self._steps if s["id"] == "hostfile")
        frame = self._make_step_frame("hostfile")
        self._step_header(frame, step["num"], "Enviar host file ao organizador",
                          "O organizador precisa do teu ficheiro de host para te aceitar na rede.")

        info_card = self._card(frame)
        ctk.CTkLabel(
            info_card,
            text="Copia o conteúdo abaixo e envia ao organizador (Discord, WhatsApp, email…).\n"
                 "Contém apenas a tua chave pública e IP VPN — não há dados sensíveis.\n"
                 "Aguarda confirmação de que ele adicionou o teu host e reiniciou o servidor tinc.",
            justify="left", font=ctk.CTkFont(size=12), wraplength=620,
        ).pack(anchor="w", padx=18, pady=14)

        host_card = self._card(frame)
        ctk.CTkLabel(host_card, text="O teu ficheiro de host:",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=18, pady=(14, 4))
        self.txt_my_host = ctk.CTkTextbox(host_card, height=170,
                                           font=ctk.CTkFont(family="Consolas", size=11))
        self.txt_my_host.pack(fill="x", padx=18, pady=(0, 8))
        btn_row = ctk.CTkFrame(host_card, fg_color="transparent")
        btn_row.pack(anchor="w", padx=14, pady=(0, 14))
        ctk.CTkButton(btn_row, text="Carregar do disco",
                       command=self.on_load_my_host).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Copiar",
                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                       command=self.on_copy_my_host).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Guardar em ficheiro…",
                       command=self.on_export_my_host).pack(side="left", padx=4)

        sent_card = self._card(frame)
        self.chk_sent = ctk.CTkCheckBox(
            sent_card,
            text="Já enviei o meu host file ao organizador e recebi confirmação",
            command=self._on_sent_changed,
        )
        self.chk_sent.pack(anchor="w", padx=18, pady=16)
        if self.settings.host_file_sent:
            self.chk_sent.select()

    def _on_sent_changed(self) -> None:
        self.settings.host_file_sent = bool(self.chk_sent.get())
        self.settings.save()
        self._update_sidebar()

    def _refresh_hostfile_step(self) -> None:
        if self.settings.player_name:
            try:
                self._populate_my_host(read_self_host_file(self.settings.player_name))
            except Exception:
                pass

    # ---- Step 6 — Ligar ----

    def _build_step_connect(self) -> None:
        step = next(s for s in self._steps if s["id"] == "connect")
        frame = self._make_step_frame("connect")
        self._step_header(frame, step["num"], "Ligar à VPN",
                          "Liga-te à rede tinc e verifica o ping antes de abrir o jogo.")

        state_card = self._card(frame)
        self.connect_status = ctk.CTkLabel(state_card, text="Desligado",
                                            font=ctk.CTkFont(size=15))
        self.connect_status.pack(anchor="w", padx=18, pady=(14, 6))
        info_bg = ctk.CTkFrame(state_card, fg_color=BG_DARK, corner_radius=6)
        info_bg.pack(fill="x", padx=18, pady=(0, 8))
        self.lbl_info = ctk.CTkLabel(info_bg, text=self._info_text(), justify="left",
                                      font=ctk.CTkFont(family="Consolas", size=11))
        self.lbl_info.pack(anchor="w", padx=12, pady=10)
        btn_row = ctk.CTkFrame(state_card, fg_color="transparent")
        btn_row.pack(anchor="w", padx=14, pady=(0, 14))
        ctk.CTkButton(btn_row, text="LIGAR", height=46, width=160,
                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                       font=ctk.CTkFont(size=14, weight="bold"),
                       command=self.on_connect).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="DESLIGAR", height=46, width=160,
                       fg_color=DANGER, hover_color=DANGER_HOVER,
                       font=ctk.CTkFont(size=14, weight="bold"),
                       command=self.on_disconnect).pack(side="left", padx=4)

        ping_card = self._card(frame)
        self.ping_label = ctk.CTkLabel(ping_card, text="Ping ao servidor: —",
                                        font=ctk.CTkFont(size=12))
        self.ping_label.pack(anchor="w", padx=18, pady=(12, 4))
        ctk.CTkButton(ping_card, text="Testar ping agora", width=150,
                       command=self.on_ping).pack(anchor="w", padx=18, pady=(0, 12))

        tips_card = self._card(frame)
        ctk.CTkLabel(tips_card, text="Dicas",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=18, pady=(12, 4))
        tips = (
            "• Aguarda o ping OK antes de abrir o jogo\n"
            "• O jogo usa a porta 9100 UDP para descoberta LAN\n"
        )
        if IS_WINDOWS:
            tips += "• Se tiveres Radmin VPN instalado, desactiva o seu adaptador nas Ligações de Rede\n"
        if IS_LINUX:
            tips += ("• No Linux (Proton/Wine) o jogo pode fazer bind na interface errada\n"
                     "  → solução: network namespace com apenas a interface tinc")
        ctk.CTkLabel(tips_card, text=tips, justify="left",
                     font=ctk.CTkFont(size=11), text_color="#aaa",
                     wraplength=580).pack(anchor="w", padx=18, pady=(0, 14))

    # ------------------------------------------------------------------ navigation

    def go_to_step(self, idx: int) -> None:
        idx = max(0, min(idx, len(self._steps) - 1))
        # Hide current frame
        if self._step_frames:
            old_id = self._steps[self._current]["id"]
            if old_id in self._step_frames:
                self._step_frames[old_id].grid_remove()
        self._current = idx
        step_id = self._steps[idx]["id"]
        if step_id in self._step_frames:
            self._step_frames[step_id].grid()
        self._update_sidebar()
        self._update_nav_bar()
        self._refresh_current_step()

    def next_step(self) -> None:
        if self._current < len(self._steps) - 1:
            self.go_to_step(self._current + 1)

    def prev_step(self) -> None:
        if self._current > 0:
            self.go_to_step(self._current - 1)

    def _update_nav_bar(self) -> None:
        n, cur = len(self._steps), self._current
        self.lbl_counter.configure(text=f"{cur + 1} / {n}")
        self.btn_prev.configure(state="normal" if cur > 0 else "disabled")
        self.btn_next.configure(state="normal" if cur < n - 1 else "disabled")

    def _auto_detect_step(self) -> None:
        def worker() -> None:
            for i, step in enumerate(self._steps):
                if not self._is_step_complete(step["id"]):
                    self.after(0, lambda idx=i: self.go_to_step(idx))
                    return
            self.after(0, lambda: self.go_to_step(len(self._steps) - 1))
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_current_step(self) -> None:
        sid = self._steps[self._current]["id"]
        {
            "tinc":     self._refresh_tinc_step,
            "tap":      self._refresh_tap_step if IS_WINDOWS else lambda: None,
            "config":   self._refresh_config_step,
            "server":   self._refresh_server_step,
            "hostfile": self._refresh_hostfile_step,
        }.get(sid, lambda: None)()

    def _poll_status(self) -> None:
        self._refresh_status_async()
        self.after(5000, self._poll_status)

    # ------------------------------------------------------------------ helpers

    def _log(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
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
        color = OK_COLOR if on else BAD_COLOR
        self.status_dot.configure(text_color=color)
        self.status_label.configure(text="LIGADO" if on else "DESLIGADO")
        if hasattr(self, "connect_status"):
            self.connect_status.configure(
                text=f"Ligado como {self.settings.vpn_ip}" if on else "Desligado",
                text_color=color)
        self._update_sidebar()

    def _refresh_status_async(self) -> None:
        def worker() -> None:
            try:
                connected = tinc_status()
                self.after(0, lambda: self._set_connected(connected))
                if connected and hasattr(self, "ping_label"):
                    ok = ping_server()
                    self.after(0, lambda: self.ping_label.configure(
                        text=f"Ping ao servidor: {'OK ✓' if ok else 'sem resposta ✗'}"))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _populate_my_host(self, content: str) -> None:
        if hasattr(self, "txt_my_host"):
            self.txt_my_host.delete("1.0", "end")
            self.txt_my_host.insert("1.0", content)

    # ------------------------------------------------------------------ actions

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
        self.settings.server_public_ip = (
            self.entry_public_ip.get().strip() if hasattr(self, "entry_public_ip") else "")
        self.settings.host_file_url = (
            self.entry_url.get().strip() if hasattr(self, "entry_url") else "")
        self.settings.auto_update_ip = (
            bool(self.chk_auto_update_ip.get()) if hasattr(self, "chk_auto_update_ip") else True)
        self.settings.save()
        if hasattr(self, "lbl_info"):
            self.lbl_info.configure(text=self._info_text())
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
                self.after(0, lambda: self._log("Ficheiros criados em " + str(tinc_dir())))
                ok, out = generate_keys()
                self.after(0, lambda: self._log(
                    "Chaves geradas." if ok else f"Falha a gerar chaves: {out}"))
                if ok:
                    self.settings.setup_done = True
                    self.settings.save()
                try:
                    content = read_self_host_file(self.settings.player_name)
                    self.after(0, lambda c=content: self._populate_my_host(c))
                except Exception as e:
                    self.after(0, lambda err=e: self._log(f"Não consegui ler o host file: {err}"))
                self.after(0, self._refresh_config_step)
                self.after(0, self._update_sidebar)
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror(APP_TITLE, str(err)))

        threading.Thread(target=worker, daemon=True).start()

    def on_load_my_host(self) -> None:
        if not self.settings.player_name:
            messagebox.showerror(APP_TITLE, "Define primeiro o nome do jogador (Passo 3).")
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
            title="Guardar host file", defaultextension="",
            initialfile=self.settings.player_name or "player",
        )
        if not path:
            return
        Path(path).write_text(text + "\n", encoding="utf-8")
        self._log(f"Host file guardado em {path}")

    def on_install_tinc(self) -> None:
        def worker() -> None:
            self.after(0, lambda: self._log("A instalar tinc…"))
            if IS_WINDOWS:
                self.after(0, lambda: self._log("A descarregar instalador (~4 MB)…"))
                ok, msg = install_tinc_windows()
            else:
                ok, msg = install_tinc_linux()
            if msg:
                self.after(0, lambda m=msg: self._log(m))
            if ok:
                self.after(0, lambda: self._log("tinc instalado com sucesso."))
                self.after(0, self._refresh_tinc_step)
            else:
                self.after(0, lambda: self._log("⚠  Instalação não concluída — vê o log."))
        threading.Thread(target=worker, daemon=True).start()

    def on_install_tap(self) -> None:
        def worker() -> None:
            try:
                self.after(0, lambda: self._log("A instalar driver TAP…"))
                ok, msg = install_tap_driver()
                if msg:
                    self.after(0, lambda m=msg: self._log(m))
                self.after(0, lambda: self._log("Driver TAP instalado." if ok else "⚠  Falha — vê o log."))
                self.after(0, self._refresh_tap_step)
            except Exception as e:
                self.after(0, lambda e=e: self._log(f"Erro ao instalar TAP: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def on_firewall(self) -> None:
        def worker() -> None:
            ok, log = add_windows_firewall_rules()
            self.after(0, lambda: self._log("Firewall: " + ("OK" if ok else "falha")))
            if log:
                self.after(0, lambda: self._log(log))
        threading.Thread(target=worker, daemon=True).start()

    def on_apply_server(self) -> None:
        text = self.txt_server.get("1.0", "end").strip()
        if not text:
            messagebox.showerror(APP_TITLE, "Cola o conteúdo do hosts/server primeiro.")
            return
        m = IP_RE.search(text)
        if not m and not messagebox.askyesno(
                APP_TITLE, "O conteúdo não tem 'Address = ...'. Aplicar mesmo assim?"):
            return
        try:
            write_server_host_file(text + ("\n" if not text.endswith("\n") else ""))
            if m:
                self.settings.server_host = m.group(1)
                self.settings.save()
            if hasattr(self, "lbl_info"):
                self.lbl_info.configure(text=self._info_text())
            self._log("hosts/server escrito.")
            self._refresh_server_step()
            self._update_sidebar()
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))

    def on_apply_public_ip(self) -> None:
        ip = self.entry_public_ip.get().strip()
        if not ip:
            messagebox.showerror(APP_TITLE, "Introduz o IP público do servidor.")
            return
        if not re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ip):
            messagebox.showerror(APP_TITLE, "Formato de IP inválido (ex: 203.0.113.42).")
            return

        def worker() -> None:
            try:
                current = read_text_maybe_sudo(tinc_dir() / "hosts" / "server")
            except Exception:
                current = ""
            if not current:
                self.after(0, lambda: messagebox.showinfo(
                    APP_TITLE,
                    "Ainda não tens um hosts/server local.\n"
                    "Cola-o primeiro e clica 'Aplicar ficheiro do servidor'."))
                return
            try:
                new = replace_address_in_host_file(current, ip)
                write_server_host_file(new)
                self.settings.server_public_ip = ip
                self.settings.server_host = ip
                self.settings.save()
                if hasattr(self, "lbl_info"):
                    self.after(0, lambda: self.lbl_info.configure(text=self._info_text()))
                self.after(0, lambda: self._log(f"Address actualizado para {ip}."))
                self.after(0, self._refresh_server_step)
                self.after(0, self._update_sidebar)
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror(APP_TITLE, str(err)))

        threading.Thread(target=worker, daemon=True).start()

    def on_pull_url(self) -> None:
        url = self.entry_url.get().strip()
        if not url:
            messagebox.showerror(APP_TITLE, "Define um URL.")
            return

        def worker() -> None:
            try:
                content = fetch_url(url)
                self.after(0, lambda c=content: (
                    self.txt_server.delete("1.0", "end"),
                    self.txt_server.insert("1.0", c)))
                self.after(0, lambda: self._log(f"Descarregado de {url}"))
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror(APP_TITLE, f"Download falhou: {err}"))

        threading.Thread(target=worker, daemon=True).start()

    def on_connect(self) -> None:
        if not self.settings.player_name:
            messagebox.showerror(APP_TITLE, "Configura primeiro o jogador (Passo 3).")
            self.go_to_step(next(i for i, s in enumerate(self._steps) if s["id"] == "config"))
            return

        def worker() -> None:
            if self.settings.auto_update_ip and self.settings.server_public_ip:
                try:
                    ip = self.settings.server_public_ip
                    current = read_text_maybe_sudo(tinc_dir() / "hosts" / "server")
                    new = replace_address_in_host_file(current, ip)
                    if new != current:
                        write_server_host_file(new)
                        self.settings.server_host = ip
                        self.settings.save()
                        self.after(0, lambda: self._log(f"hosts/server actualizado com IP {ip}"))
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
            if hasattr(self, "ping_label"):
                self.after(0, lambda: self.ping_label.configure(
                    text=f"Ping ao servidor: {'OK ✓' if ok else 'sem resposta ✗'}"))
            self.after(0, lambda: self._log(f"Ping {SERVER_VPN_IP}: {'OK' if ok else 'falhou'}"))
        threading.Thread(target=worker, daemon=True).start()


# ------------------------------------------------------------------ entry

def main() -> int:
    if IS_WINDOWS and not is_admin():
        reexec_as_admin_windows()

    # Em Linux/Wayland, $DISPLAY pode não existir; tkinter precisa dele.
    if IS_LINUX and not os.environ.get("DISPLAY"):
        wl = os.environ.get("WAYLAND_DISPLAY", "")
        if wl:
            os.environ["DISPLAY"] = ":0"
        else:
            print("Erro: nenhum display gráfico detectado ($DISPLAY / $WAYLAND_DISPLAY).",
                  file=sys.stderr)
            print("Executa o programa a partir de uma sessão gráfica (não uses sudo directamente).",
                  file=sys.stderr)
            return 1

    try:
        app = App()
    except Exception as e:
        if "display" in str(e).lower() or "DISPLAY" in str(e):
            print("Erro: não foi possível ligar ao servidor gráfico.", file=sys.stderr)
            print("", file=sys.stderr)
            if os.environ.get("WAYLAND_DISPLAY"):
                print("Estás numa sessão Wayland sem XWayland disponível.", file=sys.stderr)
                print("Instala o XWayland (ex: 'sudo dnf install xorg-x11-server-Xwayland')", file=sys.stderr)
                print("ou, no Bazzite: 'rpm-ostree install xorg-x11-server-Xwayland' e reinicia.", file=sys.stderr)
            else:
                print("Certifica-te de que estás numa sessão gráfica e não usas sudo.", file=sys.stderr)
            return 1
        raise
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
