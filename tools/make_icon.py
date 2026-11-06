"""產生 CYT_airplay 圖示：app\\icon.ico（多尺寸）與 app\\icon_preview.png。

設計：藍→青漸層圓角方形；白色螢幕框，框內「CYT」；下方 AirPlay 三角形。
小尺寸（≤24px）省略文字，只保留螢幕與三角形，維持辨識度。
用法：py tools\\make_icon.py   （需要 Pillow）
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
TOP, BOTTOM = (37, 99, 235), (6, 182, 212)  # 藍 → 青
WHITE = (255, 255, 255, 255)


def _font(px: int) -> ImageFont.FreeTypeFont:
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    s = 1024  # 先畫大圖再縮小，邊緣較平滑
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # 漸層圓角底
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / (s - 1)
        gd.line([(0, y), (s, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([24, 24, s - 24, s - 24], radius=210, fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    small = size <= 24
    stroke = 92 if small else 64

    # 螢幕框
    x0, y0, x1, y1 = 170, 180, s - 170, 700
    d.rounded_rectangle([x0, y0, x1, y1], radius=70, outline=WHITE, width=stroke)

    # 三角形（壓在螢幕下緣，先挖一個缺口讓它浮在框上）
    cx, ty, by, half = s // 2, 560, 880, 190
    gap = 70
    d.polygon([(cx, ty - gap), (cx + half + gap, by + 10), (cx - half - gap, by + 10)],
              fill=(0, 0, 0, 0))
    # 缺口要露出底色，重新貼一次漸層
    hole = Image.new("L", (s, s), 0)
    ImageDraw.Draw(hole).polygon([(cx, ty - gap), (cx + half + gap, by + 10), (cx - half - gap, by + 10)], fill=255)
    hole = Image.composite(hole, Image.new("L", (s, s), 0), mask)
    img.paste(grad, (0, 0), hole)
    d = ImageDraw.Draw(img)
    d.polygon([(cx, ty), (cx + half, by), (cx - half, by)], fill=WHITE)

    # 文字
    if not small:
        f = _font(250)
        box = d.textbbox((0, 0), "CYT", font=f)
        w, h = box[2] - box[0], box[3] - box[1]
        d.text((cx - w / 2 - box[0], 395 - h / 2 - box[1]), "CYT", font=f, fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    imgs = {n: render(n) for n in SIZES}
    ico = ROOT / "app" / "icon.ico"
    imgs[256].save(ico, format="ICO", sizes=[(n, n) for n in SIZES],
                   append_images=[imgs[n] for n in SIZES if n != 256])
    # 預覽：大圖 + 各尺寸
    prev = Image.new("RGBA", (256 + 20 + 64 + 10 + 48 + 10 + 32 + 10 + 16 + 20, 276), (245, 245, 245, 255))
    x = 10
    for n in (256, 64, 48, 32, 16):
        prev.paste(imgs[n], (x, 10 + (256 - n) // 2), imgs[n])
        x += n + 10
    prev.save(ROOT / "app" / "icon_preview.png")
    print(f"已產生 {ico}")


if __name__ == "__main__":
    main()
