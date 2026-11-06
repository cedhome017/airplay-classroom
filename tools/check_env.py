"""階段 0：AirPlay 課堂投影環境自動檢查。

用法：  py tools\\check_env.py
（請用 py 啟動器；本機的 `python` 指令會指到 Inkscape 內建的 Python。）
只讀取系統狀態，不會修改任何設定。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

OK, WARN, FAIL, INFO = "[ OK ]", "[警告]", "[失敗]", "[資訊]"
results: list[tuple[str, str]] = []


def report(level: str, msg: str) -> None:
    results.append((level, msg))
    print(f"{level} {msg}")


def ps_json(script: str):
    """執行 PowerShell 並以 JSON 取回結果（避免中文編碼問題）。"""
    full = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        f"$r = @({script}); $r | ConvertTo-Json -Depth 3 -Compress"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", full],
            capture_output=True, timeout=60,
        ).stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]


# ---------------------------------------------------------------- 檢查項目
def check_python() -> None:
    v = sys.version_info
    lvl = OK if v >= (3, 10) else FAIL
    report(lvl, f"Python {v.major}.{v.minor}.{v.micro}（{sys.executable}）")
    try:
        import tkinter
        report(OK, f"tkinter 可用（Tk {tkinter.TkVersion}）— 控制面板介面可用")
    except Exception as e:  # noqa: BLE001
        report(FAIL, f"tkinter 無法載入：{e}")


EXE = "uxplay-windows.exe"


def find_uxplay() -> Path | None:
    """依序找：正在執行的程序 → 專案 vendor\\ → 桌面 → Program Files 等常見位置。"""
    running = ps_json("Get-CimInstance Win32_Process -Filter \"Name='uxplay-windows.exe'\" | "
                      "Select ExecutablePath")
    for r in running or []:
        if r.get("ExecutablePath"):
            return Path(r["ExecutablePath"])

    home = Path.home()
    roots = [
        Path(__file__).resolve().parents[1] / "vendor",
        home / "Desktop", home / "OneDrive" / "Desktop", home / "Downloads",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
    ]
    for base in roots:
        if (base / EXE).is_file():
            return base / EXE
        if not base.is_dir():
            continue
        for d in base.iterdir():
            if d.is_dir() and "uxplay" in d.name.lower():
                hit = next(d.rglob(EXE), None)
                if hit:
                    return hit
    return None


def check_uxplay() -> None:
    exe = find_uxplay()
    if exe:
        report(OK, f"uxplay-windows：{exe}")
        report(INFO, "此版本的 UxPlay 引擎內建於 uxplay-windows.exe（沒有獨立的 uxplay.exe）")
        if "desktop" in str(exe).lower():
            report(WARN, "程式放在桌面，容易被誤刪或移動；建議移到專案的 vendor\\uxplay-windows\\")
    else:
        report(FAIL, f"找不到 {EXE} — 尚未安裝，或放在非預設位置")

    for p in [
        Path(os.environ.get("ProgramData", "")) / "uxplay-windows" / "arguments.txt",
        Path(os.environ.get("APPDATA", "")) / "leapbtw" / "uxplay-windows" / "arguments.txt",
    ]:
        if p.is_file():
            report(INFO, f"參數檔 {p}：{p.read_text(encoding='utf-8', errors='replace').strip()}")


def check_bonjour() -> None:
    svc = ps_json("Get-Service | ? { $_.Name -match 'Bonjour|mDNS' } | "
                  "Select Name,@{n='Status';e={[string]$_.Status}},@{n='Start';e={[string]$_.StartType}}")
    if svc is None:
        report(WARN, "無法查詢服務狀態")
    elif not svc:
        report(FAIL, "找不到 Bonjour 服務 — iPad 將找不到這台電腦")
    for s in svc or []:
        lvl = OK if s["Status"] == "Running" else FAIL
        report(lvl, f"服務 {s['Name']}：{s['Status']}（啟動類型 {s['Start']}）")


def check_network() -> None:
    profiles = ps_json("Get-NetConnectionProfile | Select InterfaceAlias,Name,"
                       "@{n='Cat';e={[string]$_.NetworkCategory}}")
    for p in profiles or []:
        lvl = OK if p["Cat"] in ("Private", "DomainAuthenticated") else WARN
        hint = "" if lvl == OK else " — 『公用』網路常會擋掉 AirPlay 探索，建議改為私人"
        report(lvl, f"網路 {p['InterfaceAlias']}（{p['Name']}）類型：{p['Cat']}{hint}")

    ips = ps_json("Get-NetIPAddress -AddressFamily IPv4 | ? { $_.IPAddress -notlike '127.*' "
                  "-and $_.IPAddress -notlike '169.254.*' } | Select InterfaceAlias,IPAddress")
    for ip in ips or []:
        report(INFO, f"IPv4 {ip['IPAddress']}（{ip['InterfaceAlias']}）— iPad 需在同一網段")
    if ips and len(ips) > 1:
        report(WARN, "有多張網卡（如 VPN／虛擬網卡），AirPlay 可能廣播到錯的網卡")
    report(INFO, f"電腦名稱：{socket.gethostname()}")


def check_firewall() -> None:
    rules = ps_json("Get-NetFirewallRule | ? { $_.DisplayName -match 'uxplay|bonjour|mDNS' -and "
                    "$_.Direction -eq 'Inbound' } | Select DisplayName,"
                    "@{n='En';e={[string]$_.Enabled}},@{n='Act';e={[string]$_.Action}}")
    if rules is None:
        report(WARN, "無法讀取防火牆規則")
        return
    names = {r["DisplayName"] for r in rules if r["En"] == "True" and r["Act"] == "Allow"}
    for key, label in (("mdns", "mDNS"), ("bonjour", "Bonjour"), ("uxplay", "UxPlay")):
        hit = [n for n in names if key in n.lower()]
        if hit:
            report(OK, f"防火牆已允許 {label} 輸入（{len(hit)} 條規則）")
        else:
            lvl = WARN if key == "uxplay" else FAIL
            report(lvl, f"防火牆沒有允許 {label} 的輸入規則"
                        + ("（首次啟動 UxPlay 時請在跳出視窗勾選『私人』並允許）" if key == "uxplay" else ""))


def check_running() -> None:
    procs = ps_json("Get-Process | ? { $_.ProcessName -match 'uxplay' } | Select ProcessName,Id")
    if not procs:
        report(INFO, "UxPlay 目前未執行（要測連線時再啟動即可）")
        return
    for p in procs:
        report(OK, f"執行中：{p['ProcessName']}（PID {p['Id']}）")
    # UxPlay 預設使用動態埠，所以依程序 PID 查，而不是看固定埠號
    pids = ",".join(str(p["Id"]) for p in procs if p["ProcessName"] == "uxplay-windows")
    if not pids:
        return
    tcp = ps_json(f"Get-NetTCPConnection | ? {{ $_.OwningProcess -in {pids} }} | "
                  "Select LocalPort,RemoteAddress,@{n='State';e={[string]$_.State}}")
    listen = sorted({t["LocalPort"] for t in tcp or [] if t["State"] == "Listen"})
    clients = sorted({t["RemoteAddress"] for t in tcp or []
                      if t["State"] == "Established" and t["RemoteAddress"] not in ("127.0.0.1", "::1")})
    if listen:
        report(OK, "AirPlay 服務監聽埠：" + ", ".join(map(str, listen)))
    else:
        report(WARN, "uxplay-windows 在執行，但沒有監聽中的 TCP 埠（伺服器可能未啟動）")
    report(INFO, "目前連線中的裝置：" + (", ".join(clients) if clients else "無"))


def main() -> int:
    print("=" * 60)
    print(" AirPlay 課堂投影 — 環境檢查（階段 0）")
    print("=" * 60)
    for title, fn in (("Python", check_python), ("UxPlay", check_uxplay),
                      ("Bonjour / mDNS", check_bonjour), ("網路", check_network),
                      ("防火牆", check_firewall), ("執行狀態", check_running)):
        print(f"\n── {title}")
        fn()

    fails = sum(1 for l, _ in results if l == FAIL)
    warns = sum(1 for l, _ in results if l == WARN)
    print("\n" + "=" * 60)
    print(f" 結果：失敗 {fails} 項、警告 {warns} 項")
    print("=" * 60)

    log = Path(__file__).resolve().parents[1] / "logs" / "check_env.txt"
    log.parent.mkdir(exist_ok=True)
    log.write_text("\n".join(f"{l} {m}" for l, m in results), encoding="utf-8")
    print(f"報告已存到 {log}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
