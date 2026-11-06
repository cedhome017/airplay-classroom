"""打包發行版：PyInstaller 產生 exe（含版本資訊）→ 組成資料夾 → 壓成 zip。

用法：  py tools\\build_release.py          （單純打包，不改版本、不上傳）
        發布新版請用 release.bat
產出：  dist\\CYT_airplay\\               （可直接執行的資料夾）
        dist\\CYT_airplay_v<版本>.zip      （上傳雲端／GitHub Release 用）
需要：  pip install pyinstaller，且 vendor\\uxplay-windows\\ 已放好。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP = "CYT_airplay"
TITLE = "CYT_airplay 課堂投影控制面板"
VENDOR = ROOT / "vendor" / "uxplay-windows"
VERSION_FILE = ROOT / "app" / "version.py"


def read_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', VERSION_FILE.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"讀不到版本號：{VERSION_FILE}")
    return m.group(1)


def _version_resource(version: str) -> Path:
    nums = [int(n) for n in re.findall(r"\d+", version)][:4]
    nums += [0] * (4 - len(nums))
    t = tuple(nums)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040404B0', [
      StringStruct('FileDescription', '{TITLE}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{APP}'),
      StringStruct('OriginalFilename', '{APP}.exe'),
      StringStruct('ProductName', '{TITLE}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [0x0404, 1200])])
  ]
)
"""
    BUILD.mkdir(exist_ok=True)
    f = BUILD / "version_info.txt"
    f.write_text(text, encoding="utf-8")
    return f


def build(version: str | None = None) -> Path:
    """打包並回傳 zip 路徑。"""
    version = version or read_version()
    if not (VENDOR / "uxplay-windows.exe").is_file():
        raise SystemExit(f"找不到 {VENDOR}\\uxplay-windows.exe，請先放好 uxplay-windows")

    print(f"1/3 PyInstaller 打包 exe（v{version}）…")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
        "--onefile", "--windowed", "--name", APP,
        "--icon", str(ROOT / "app" / "icon.ico"),
        "--add-data", f"{ROOT / 'app' / 'icon.ico'};.",
        "--version-file", str(_version_resource(version)),
        "--paths", str(ROOT / "app"),
        "--workpath", str(BUILD), "--specpath", str(BUILD), "--distpath", str(DIST),
        str(ROOT / "app" / "main.py"),
    ], check=True, cwd=ROOT)

    print("2/3 組成發行資料夾…")
    out = DIST / APP
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.move(str(DIST / f"{APP}.exe"), out / f"{APP}.exe")
    shutil.copytree(VENDOR, out / "vendor" / "uxplay-windows")
    shutil.copy2(ROOT / "README.md", out / "使用說明.md")

    print("3/3 壓縮 zip…")
    for old in DIST.glob(f"{APP}_*.zip"):
        old.unlink()
    zpath = DIST / f"{APP}_v{version}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, Path(APP) / f.relative_to(out))
    print(f"完成：{zpath}（{zpath.stat().st_size / 1024 / 1024:.0f} MB）")
    return zpath


if __name__ == "__main__":
    build()
