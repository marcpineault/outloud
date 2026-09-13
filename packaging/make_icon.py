"""Draw the app icon with Pillow and write icon.png, icon.ico and (on macOS) icon.icns."""
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))


def draw(size=1024):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = size * 0.06
    d.rounded_rectangle((m, m, size - m, size - m), radius=size * 0.22, fill=(20, 70, 160, 255))
    # speaker body
    cx, cy = size * 0.40, size * 0.5
    d.rectangle((size * 0.20, cy - size * 0.11, size * 0.30, cy + size * 0.11), fill="white")
    d.polygon([(size * 0.30, cy - size * 0.11), (size * 0.46, cy - size * 0.24), (size * 0.46, cy + size * 0.24), (size * 0.30, cy + size * 0.11)], fill="white")
    # sound waves
    w = int(size * 0.045)
    for r in (0.16, 0.26, 0.36):
        box = (cx - r * size, cy - r * size, cx + r * size, cy + r * size)
        d.arc(box, start=-40, end=40, fill="white", width=w)
    return img


def main():
    icon = draw()
    icon.save(os.path.join(HERE, "icon.png"))
    icon.save(os.path.join(HERE, "icon.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = os.path.join(HERE, "icon.iconset")
        os.makedirs(iconset, exist_ok=True)
        for px in (16, 32, 128, 256, 512):
            icon.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, f"icon_{px}x{px}.png"))
            icon.resize((px * 2, px * 2), Image.LANCZOS).save(os.path.join(iconset, f"icon_{px}x{px}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(HERE, "icon.icns")], check=True)
        shutil.rmtree(iconset)
    print("icons written to", HERE)


if __name__ == "__main__":
    main()
