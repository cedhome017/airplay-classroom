"""一鍵發布新版本：決定版本號 → 打包 exe／zip → git commit + tag → 推送 → 建立 GitHub Release。

用法：  雙擊 release.bat（互動模式）
        py tools\\release.py --version 1.1 --notes "修正…" --yes   （非互動）
面板的自動更新會讀取 GitHub 最新 Release 中的 zip，所以發布後各電腦即可收到更新通知。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_release as br  # noqa: E402

ROOT = br.ROOT
VERSION_RE = re.compile(r"^\d+(\.\d+){1,2}$")


def sh(*cmd: str, capture: bool = False, check: bool = True) -> str:
    r = subprocess.run(cmd, cwd=ROOT, check=check, text=True, encoding="utf-8", errors="replace",
                       capture_output=capture)
    return (r.stdout or "").strip() if capture else ""


def vtuple(v: str) -> tuple[int, ...]:
    t = [int(x) for x in v.split(".")]
    while len(t) > 1 and t[-1] == 0:
        t.pop()
    return tuple(t)


def write_version(v: str) -> None:
    text = br.VERSION_FILE.read_text(encoding="utf-8")
    br.VERSION_FILE.write_text(re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{v}"', text),
                               encoding="utf-8")


def released_tags() -> set[str]:
    out = sh("git", "ls-remote", "--tags", "origin", capture=True, check=False)
    tags = {line.rsplit("/", 1)[-1].removesuffix("^{}") for line in out.splitlines() if "refs/tags/" in line}
    return tags | set(sh("git", "tag", "-l", capture=True, check=False).split())


def suggest(cur: str, tags: set[str]) -> str:
    if f"v{cur}" not in tags:
        return cur  # 目前版本還沒發布過（例如第一次發布 v1.0）
    parts = [int(x) for x in cur.split(".")]
    parts[-1] += 1
    return ".".join(map(str, parts))


def repo_slug() -> str:
    url = sh("git", "remote", "get-url", "origin", capture=True)
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    if not m:
        raise SystemExit(f"origin 不是 GitHub repo：{url}")
    return m.group(1)


def ask(prompt: str, default: str = "") -> str:
    s = input(f"{prompt}{f'［{default}］' if default else ''}：").strip()
    return s or default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version")
    ap.add_argument("--notes")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()

    print("=" * 60)
    print(" CYT_airplay — 發布新版本")
    print("=" * 60)

    # ---- 前置檢查
    slug = repo_slug()
    owner = slug.split("/")[0]
    user = sh("gh", "api", "user", "--jq", ".login", capture=True, check=False)
    if user.lower() != owner.lower():
        print(f"✗ GitHub 目前登入的是「{user or '未登入'}」，但 repo 屬於「{owner}」。")
        print(f"  請先執行：gh auth switch --hostname github.com --user {owner}")
        return 1
    branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD", capture=True)

    cur = br.read_version()
    tags = released_tags()
    sug = suggest(cur, tags)
    print(f"GitHub repo：{slug}（帳號 {user}，分支 {branch}）")
    print(f"目前版本：v{cur}{'（已發布）' if f'v{cur}' in tags else '（尚未發布）'}")
    changed = sh("git", "status", "--short", capture=True)
    print("本次變更的檔案：\n" + ("\n".join("  " + x for x in changed.splitlines()) if changed else "  （無）"))
    print()

    # ---- 版本號
    while True:
        v = (a.version or ask(f"新版本號（直接 Enter 採用建議 v{sug}）", sug)).lstrip("vV")
        err = None
        if not VERSION_RE.match(v):
            err = "格式應為 1.1 或 1.1.2"
        elif f"v{v}" in tags:
            err = f"v{v} 已經發布過了"
        elif vtuple(v) < vtuple(cur):
            err = f"不可小於目前版本 v{cur}"
        if not err:
            break
        print(f"  ✗ {err}")
        if a.version:
            return 1
    notes = a.notes or ask("這次更新的說明（會顯示在更新通知中）", "功能改進與錯誤修正")

    print(f"\n即將發布 v{v}：打包 exe／zip → commit → tag v{v} → 推送 → 建立 GitHub Release")
    if not a.yes and ask("確定執行？(Y/N)", "Y").upper() != "Y":
        print("已取消。")
        return 0

    # ---- 打包（失敗就還原版本號）
    write_version(v)
    try:
        zpath = br.build(v)
    except BaseException:
        write_version(cur)
        print("✗ 打包失敗，版本號已還原。")
        raise

    # ---- git
    sh("git", "add", "-A")
    if sh("git", "status", "--porcelain", capture=True):
        sh("git", "commit", "-q", "-m", f"v{v}：{notes}")
    sh("git", "tag", "-a", f"v{v}", "-m", f"v{v}：{notes}")
    sh("git", "push", "origin", branch)
    sh("git", "push", "origin", f"v{v}")

    # ---- GitHub Release
    print("上傳 Release（zip 約 100 MB 以上，需要一點時間）…")
    sh("gh", "release", "create", f"v{v}", str(zpath), "--repo", slug,
       "--title", f"v{v}", "--notes", notes, "--latest")
    print("\n" + "=" * 60)
    print(f" ✓ v{v} 發布完成")
    print(f"   https://github.com/{slug}/releases/tag/v{v}")
    print(f"   本機 zip：{zpath}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"\n✗ 指令失敗：{' '.join(map(str, e.cmd))}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已中斷。")
        sys.exit(1)
