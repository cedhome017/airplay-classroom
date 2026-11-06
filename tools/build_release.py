"""打包發行版：PyInstaller 產生 exe → 組成資料夾 → 壓成 zip。

用法：  py tools\\build_release.py
產出：  dist\\AirPlayClassroom\\           （可直接執行的資料夾）
        dist\\AirPlayClassroom_<日期>.zip  （上傳雲端用）
需要：  pip install pyinstaller，且 vendor\\uxplay-windows\\ 已放好。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP = "AirPlayClassroom"
VENDOR = ROOT / "vendor" / "uxplay-windows"


def main() -> int:
    if not (VENDOR / "uxplay-windows.exe").is_file():
        print(f"找不到 {VENDOR}\\uxplay-windows.exe，請先放好 uxplay-windows")
        return 1

    print("1/3 PyInstaller 打包 exe…")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--workpath", str(ROOT / "build"),
                    "--distpath", str(DIST), str(ROOT / f"{APP}.spec")], check=True, cwd=ROOT)

    print("2/3 組成發行資料夾…")
    out = DIST / APP
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.move(str(DIST / f"{APP}.exe"), out / f"{APP}.exe")
    shutil.copytree(VENDOR, out / "vendor" / "uxplay-windows")
    shutil.copy2(ROOT / "README.md", out / "使用說明.md")

    print("3/3 壓縮 zip…")
    zpath = DIST / f"{APP}_{time.strftime('%Y%m%d')}.zip"
    zpath.unlink(missing_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, Path(APP) / f.relative_to(out))
    print(f"完成：{zpath}（{zpath.stat().st_size / 1024 / 1024:.0f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
