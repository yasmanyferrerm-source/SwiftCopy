"""Draws assets/icon.ico and assets/icon.png (run once; output is committed)."""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets")


def draw(size: int = 512) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # blue rounded tile with a vertical gradient
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / s
        c = (int(37 + (29 - 37) * t), int(99 + (78 - 99) * t), int(235 + (216 - 235) * t), 255)
        gd.line([(0, y), (s, y)], fill=c)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    # back page
    def page(x, y, w, h, fill, outline):
        fold = int(w * 0.28)
        pts = [(x, y), (x + w - fold, y), (x + w, y + fold), (x + w, y + h), (x, y + h)]
        d.polygon(pts, fill=fill)
        d.polygon([(x + w - fold, y), (x + w - fold, y + fold), (x + w, y + fold)], fill=outline)

    page(int(s * .18), int(s * .16), int(s * .40), int(s * .52), (191, 219, 254, 255), (147, 197, 253, 255))
    page(int(s * .38), int(s * .30), int(s * .42), int(s * .54), (255, 255, 255, 255), (203, 213, 225, 255))
    # green arrow on the front page
    cx, cy = int(s * .59), int(s * .60)
    a = int(s * .10)
    d.rectangle([cx - a, cy - int(a * .35), cx + int(a * .2), cy + int(a * .35)], fill=(22, 163, 74, 255))
    d.polygon([(cx + int(a * .1), cy - int(a * .85)), (cx + int(a * 1.05), cy),
               (cx + int(a * .1), cy + int(a * .85))], fill=(22, 163, 74, 255))
    return img


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    big = draw(512)
    big.save(os.path.join(OUT, "icon.png"))
    big.save(os.path.join(OUT, "icon.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    # Microsoft Store (MSIX) logos
    msix = os.path.join(HERE, "..", "packaging", "msix", "Assets")
    os.makedirs(msix, exist_ok=True)

    def square(px, name):
        draw(512).resize((px, px), Image.LANCZOS).save(os.path.join(msix, name))

    square(44, "Square44x44Logo.png")
    square(88, "Square44x44Logo.scale-200.png")
    for ts in (16, 24, 32, 48, 256):
        square(ts, f"Square44x44Logo.targetsize-{ts}.png")
        square(ts, f"Square44x44Logo.targetsize-{ts}_altform-unplated.png")
    square(150, "Square150x150Logo.png")
    square(300, "Square150x150Logo.scale-200.png")
    square(50, "StoreLogo.png")
    square(100, "StoreLogo.scale-200.png")
    for w, h, name in ((310, 150, "Wide310x150Logo.png"), (620, 300, "Wide310x150Logo.scale-200.png")):
        wide = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        tile = draw(512).resize((h, h), Image.LANCZOS)
        wide.paste(tile, ((w - h) // 2, 0), tile)
        wide.save(os.path.join(msix, name))
    print("icon written")
