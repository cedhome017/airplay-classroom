"""自動更新：查 GitHub 最新 Release → 下載 zip → 解壓 → 由外部 PowerShell 腳本替換檔案並重開。

執行中的 exe 無法覆蓋自己，所以替換工作交給一個背景 PowerShell 腳本：
等面板（含 PyInstaller 外層程序）結束 → 停掉 uxplay-windows → robocopy 新檔 → 重新開啟面板。
config.json 等使用者檔案不在 zip 內，不會被覆蓋。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from version import GITHUB_REPO, __version__

API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
EXE_NAME = "CYT_airplay.exe"
UA = {"User-Agent": "CYT_airplay-updater", "Accept": "application/vnd.github+json"}


def parse_version(v: str) -> tuple[int, ...]:
    nums = [int(n) for n in re.findall(r"\d+", v)]
    while len(nums) > 1 and nums[-1] == 0:  # 1.0 == 1.0.0
        nums.pop()
    return tuple(nums) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


@dataclass
class ReleaseInfo:
    version: str
    notes: str
    zip_url: str
    zip_name: str
    zip_size: int
    page_url: str


def fetch_latest(timeout: float = 8) -> ReleaseInfo | None:
    req = urllib.request.Request(API_LATEST, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:  # 尚未發布任何 Release
            return None
        raise
    asset = next((a for a in data.get("assets", []) if a["name"].lower().endswith(".zip")), None)
    if not asset:
        return None
    return ReleaseInfo(
        version=data["tag_name"].lstrip("vV"),
        notes=(data.get("body") or "").strip(),
        zip_url=asset["browser_download_url"],
        zip_name=asset["name"],
        zip_size=int(asset.get("size") or 0),
        page_url=data.get("html_url") or RELEASES_PAGE,
    )


def check_update() -> ReleaseInfo | None:
    """有新版回傳 ReleaseInfo，否則 None；網路錯誤會丟出例外。"""
    info = fetch_latest()
    return info if info and is_newer(info.version) else None


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def can_self_update() -> tuple[bool, str]:
    if not getattr(sys, "frozen", False):
        return False, "目前是開發模式（直接執行 .py），請用 git pull 更新程式碼。"
    d = install_dir()
    try:
        with tempfile.NamedTemporaryFile(dir=d, prefix=".write_test_", delete=True):
            pass
    except OSError:
        return False, f"沒有寫入權限：{d}\n請把程式資料夾放在可寫入的位置（例如 D:\\ 或桌面），或手動下載新版。"
    return True, ""


def download(info: ReleaseInfo, dest_dir: Path, progress=lambda done, total: None,
             cancelled=lambda: False) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / info.zip_name
    req = urllib.request.Request(info.zip_url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as r, open(out, "wb") as f:  # noqa: S310
        total = int(r.headers.get("Content-Length") or info.zip_size or 0)
        done = 0
        while chunk := r.read(256 * 1024):
            if cancelled():
                raise InterruptedError("已取消下載")
            f.write(chunk)
            done += len(chunk)
            progress(done, total)
    if info.zip_size and out.stat().st_size != info.zip_size:
        raise IOError("下載的檔案大小不符，可能不完整，請再試一次")
    return out


def extract(zip_path: Path, dest_dir: Path) -> Path:
    """解壓並回傳含有 CYT_airplay.exe 的資料夾。"""
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest_dir)
    hit = next(dest_dir.rglob(EXE_NAME), None)
    if not hit:
        raise IOError(f"更新檔中找不到 {EXE_NAME}")
    return hit.parent


def _ps_quote(p: Path | str) -> str:
    return "'" + str(p).replace("'", "''") + "'"


def launch_replacer(src: Path, dst: Path, work: Path, wait_pids: list[int]) -> None:
    """寫出並在背景執行替換腳本；呼叫後面板應立即結束。"""
    script = work / "apply_update.ps1"
    pids = ",".join(str(p) for p in wait_pids)
    script.write_text(f"""
$ErrorActionPreference = 'Continue'
$src = {_ps_quote(src)}
$dst = {_ps_quote(dst)}
$work = {_ps_quote(work)}
foreach ($id in @({pids})) {{ Wait-Process -Id $id -Timeout 30 -ErrorAction SilentlyContinue }}
Get-Process uxplay-windows, uxplay-bluetooth-beacon -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
robocopy $src $dst /E /R:5 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
$code = $LASTEXITCODE
if ($code -ge 8) {{
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("更新失敗（robocopy 代碼 $code）。`n請關閉所有相關程式後再試，或手動下載新版。", 'CYT_airplay') | Out-Null
}} else {{
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}}
Start-Process -FilePath (Join-Path $dst '{EXE_NAME}') -WorkingDirectory $dst
""", encoding="utf-8-sig")  # PowerShell 5.1 需要 BOM 才會以 UTF-8 讀中文
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", str(script)], creationflags=flags, close_fds=True, env=clean_env())


def clean_env() -> dict[str, str]:
    """給「全新啟動」的子程序用的環境變數。

    PyInstaller onefile 會設定 _PYI_*／_MEIPASS2 等變數指向本程序的暫存解壓資料夾；
    若被新版 exe 繼承，新版會去找已刪除的資料夾而出現「Failed to load Python DLL」。
    """
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("_PYI_", "_MEIPASS")) and k.upper() not in ("TCL_LIBRARY", "TK_LIBRARY")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:  # 從 PATH 移除暫存資料夾
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                      if not p.startswith(meipass))
    return env


def pids_to_wait() -> list[int]:
    """PyInstaller onefile 有外層程序鎖住 exe，兩個都要等。"""
    pids = [os.getpid()]
    try:
        pids.append(os.getppid())
    except OSError:
        pass
    return pids
