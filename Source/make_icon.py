# -*- coding: utf-8 -*-
"""Generates icon.ico for the app (red rounded square + play triangle)."""
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow not installed - skipping icon generation.")
    sys.exit(0)

SIZE = 256

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# red rounded square
d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=48, fill=(255, 0, 0, 255))

# white play triangle
cx = SIZE // 2
d.polygon(
    [(cx - 38, SIZE // 2 - 60), (cx - 38, SIZE // 2 + 60), (cx + 66, SIZE // 2)],
    fill=(255, 255, 255, 255),
)

sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save("icon.ico", sizes=sizes)
print("icon.ico created.")
