"""控制 uxplay-windows：找程式、讀寫 arguments.txt、啟動／停止、查詢狀態。

uxplay-windows 2.x 把 UxPlay 引擎內建在 uxplay-windows.exe 中，
啟動參數從 arguments.txt 讀取（ProgramData 版優先於 AppData 版），
改參數後必須重新啟動程式才會生效。
只用標準函式庫與 Windows 內建指令（tasklist／netstat／taskkill）。
"""
from __future__ import annotations

import csv
import io
import os
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

EXE_NAME = "uxplay-windows.exe"
CHILD_NAMES = ("uxplay-bluetooth-beacon.exe",)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

ARGS_PROGRAMDATA = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "uxplay-windows" / "arguments.txt"
ARGS_APPDATA = Path(os.environ.get("APPDATA", "")) / "leapbtw" / "uxplay-windows" / "arguments.txt"
DEFAULT_ARGS = "-n uxplay-windows -nh"


def _run(cmd: list[str], timeout: float = 15) -> str:
    out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW).stdout
    for enc in ("utf-8", "mbcs"):
        try:
            return out.decode(enc)
        except UnicodeDecodeError:
            continue
    return out.decode("utf-8", "replace")


# ------------------------------------------------------------------ 找程式
def find_exe(project_root: Path, configured: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(project_root / "vendor" / "uxplay-windows" / EXE_NAME)
    home = Path.home()
    for base in (home / "Desktop", home / "OneDrive" / "Desktop",
                 Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"):
        candidates.append(base / "uxplay-windows" / EXE_NAME)
    for c in candidates:
        if c.is_file():
            return c
    return None


# ------------------------------------------------------------------ 必要元件
UXPLAY_DOWNLOAD_URL = "https://github.com/leapbtw/uxplay-windows/releases/latest"
BONJOUR_DOWNLOAD_URL = "https://support.apple.com/en-us/106380"  # Apple 官方 Bonjour Print Services 頁面
BONJOUR_SERVICE = "Bonjour Service"


def bonjour_state() -> str:
    """回傳 'running'、'stopped' 或 'missing'。"""
    try:
        out = _run(["sc", "query", BONJOUR_SERVICE])
    except OSError:
        return "missing"
    if "RUNNING" in out:
        return "running"
    if "STATE" in out:
        return "stopped"
    return "missing"


# ------------------------------------------------------------------ 參數
FULLSCREEN_SINK = "d3d11videosink"  # UxPlay 的 -fs 在 Windows 需搭配 D3D11/12 videosink


@dataclass
class UxArgs:
    name: str = "uxplay-windows"
    no_hostname: bool = True
    resolution: str = ""   # 空字串 = UxPlay 預設（1920x1080）
    fps: str = ""          # 空字串 = UxPlay 預設（30）
    fullscreen: bool = False
    pin: str = ""          # 4 位數字；空字串 = 不使用 PIN
    nohold: bool = False   # 新裝置連線時踢掉目前的裝置
    record_to: str = ""    # 錄影檔路徑（不含副檔名）；空字串 = 不錄影
    extra: list[str] = field(default_factory=list)  # 其他未處理的參數，原樣保留

    @classmethod
    def parse(cls, text: str) -> "UxArgs":
        toks = text.split()
        a = cls(name="", no_hostname=False)
        vs = None
        i = 0
        while i < len(toks):
            t = toks[i]
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if t == "-n" and nxt is not None:
                a.name, i = nxt, i + 2
            elif t == "-nh":
                a.no_hostname, i = True, i + 1
            elif t == "-s" and nxt is not None:
                a.resolution, i = nxt, i + 2
            elif t == "-fps" and nxt is not None:
                a.fps, i = nxt, i + 2
            elif t == "-fs":
                a.fullscreen, i = True, i + 1
            elif t == "-vs" and nxt is not None:
                vs, i = nxt, i + 2
            elif t == "-nohold":
                a.nohold, i = True, i + 1
            elif t.startswith("-pin"):
                if t[4:].isdigit():
                    a.pin, i = t[4:], i + 1
                elif nxt is not None and nxt.isdigit():
                    a.pin, i = nxt, i + 2
                else:
                    i += 1  # 隨機 PIN 在 uxplay-windows 看不到，改由面板管理
            elif t == "-vdmp":
                i += 1
                if i < len(toks) and toks[i].isdigit():
                    i += 1
                if i < len(toks) and not toks[i].startswith("-"):
                    a.record_to, i = toks[i], i + 1
                else:
                    a.record_to = "videodump"
            else:
                a.extra.append(t)
                i += 1
        if vs and not (a.fullscreen and vs == FULLSCREEN_SINK):
            a.extra[:0] = ["-vs", vs]
        return a

    def to_text(self) -> str:
        parts: list[str] = []
        if self.name:
            parts += ["-n", self.name]
        if self.no_hostname:
            parts.append("-nh")
        if self.resolution:
            parts += ["-s", self.resolution]
        if self.fps:
            parts += ["-fps", self.fps]
        if self.fullscreen:
            if "-vs" not in self.extra:
                parts += ["-vs", FULLSCREEN_SINK]
            parts.append("-fs")
        if self.pin:
            parts += ["-pin", self.pin]
        if self.nohold:
            parts.append("-nohold")
        if self.record_to:
            parts += ["-vdmp", self.record_to]
        parts += self.extra
        return " ".join(parts)


def validate_pin(pin: str) -> str | None:
    if pin and not (len(pin) == 4 and pin.isdigit()):
        return "PIN 碼必須是 4 位數字"
    return None


def validate_path_token(p: str) -> str | None:
    if any(c.isspace() for c in p):
        return f"路徑不可包含空白：{p}"
    return None


def validate_name(name: str) -> str | None:
    """回傳錯誤訊息；沒問題回傳 None。"""
    if not name:
        return "名稱不可空白"
    if any(c.isspace() for c in name):
        return "名稱不可包含空白（uxplay-windows 以空白分隔參數）"
    if name.startswith("-"):
        return "名稱不可以「-」開頭"
    if len(name.encode("utf-8")) > 60:
        return "名稱太長"
    return None


def active_args_file() -> Path:
    """uxplay-windows 實際會讀的檔案。"""
    return ARGS_PROGRAMDATA if ARGS_PROGRAMDATA.is_file() else ARGS_APPDATA


def read_args() -> UxArgs:
    f = active_args_file()
    text = f.read_text(encoding="utf-8-sig", errors="replace") if f.is_file() else DEFAULT_ARGS
    return UxArgs.parse(text or DEFAULT_ARGS)


def write_args(args: UxArgs) -> Path:
    """寫入 AppData 版（不需管理員權限）。若 ProgramData 版存在會蓋過它，呼叫端應提醒。"""
    ARGS_APPDATA.parent.mkdir(parents=True, exist_ok=True)
    ARGS_APPDATA.write_text(args.to_text(), encoding="utf-8")  # UTF-8 無 BOM
    return ARGS_APPDATA


# ------------------------------------------------------------------ 程序
def _pids(image: str) -> list[int]:
    out = _run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"])
    pids = []
    for row in csv.reader(io.StringIO(out)):
        if len(row) >= 2 and row[0].lower() == image.lower():
            pids.append(int(row[1]))
    return pids


def is_running() -> bool:
    return bool(_pids(EXE_NAME))


def start(exe: Path) -> None:
    if is_running():
        return
    from updater import clean_env  # 避免把 PyInstaller 暫存路徑傳給 uxplay-windows
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True, env=clean_env(),
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def stop(timeout: float = 2) -> None:
    """先溫和關閉，逾時再強制結束（含藍牙信標子程序）。"""
    if not is_running():
        return
    _run(["taskkill", "/IM", EXE_NAME, "/T"])
    end = time.time() + timeout
    while time.time() < end and is_running():
        time.sleep(0.3)
    if is_running():
        _run(["taskkill", "/IM", EXE_NAME, "/T", "/F"])
    for child in CHILD_NAMES:  # 以防子程序殘留
        if _pids(child):
            _run(["taskkill", "/IM", child, "/T", "/F"])


def restart(exe: Path) -> None:
    stop()
    time.sleep(1)
    start(exe)


# ------------------------------------------------------------------ 狀態
@dataclass
class Status:
    running: bool
    pids: list[int]
    listen_ports: list[int]
    clients: list[str]


_LOOPBACK = ("127.", "[::1]", "::1", "0.0.0.0", "[::]")


def get_status() -> Status:
    pids = _pids(EXE_NAME)
    if not pids:
        return Status(False, [], [], [])
    pidset = {str(p) for p in pids}
    listen: set[int] = set()
    clients: set[str] = set()
    for line in _run(["netstat", "-ano", "-p", "TCP"]).splitlines() + \
            _run(["netstat", "-ano", "-p", "TCPv6"]).splitlines():
        cols = line.split()
        if len(cols) != 5 or cols[0] not in ("TCP", "TCPv6") or cols[4] not in pidset:
            continue
        local, remote, state = cols[1], cols[2], cols[3]
        if state == "LISTENING":
            listen.add(int(local.rsplit(":", 1)[1]))
        elif state == "ESTABLISHED":
            host = remote.rsplit(":", 1)[0]
            if not host.startswith(_LOOPBACK):
                clients.add(host.strip("[]"))
    return Status(True, pids, sorted(listen), sorted(clients))


def local_ipv4() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254.")):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)
