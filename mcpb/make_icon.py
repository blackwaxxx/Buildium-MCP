"""Draw the extension icon. Run once; the PNG is committed.

A flat glyph rather than a logo: Buildium's marks are theirs (see NOTICE), so
this is a generic building silhouette on a plain background.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 512
OUT = Path(__file__).with_name("icon.png")


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Background: rounded square.
    d.rounded_rectangle((16, 16, SIZE - 16, SIZE - 16), radius=96, fill=(31, 78, 121, 255))
    # A building: tall block with a lower wing, windows in a grid, a door.
    d.rectangle((136, 128, 296, 416), fill=(245, 247, 250, 255))
    d.rectangle((296, 224, 392, 416), fill=(214, 222, 232, 255))
    for row in range(5):
        y = 156 + row * 50
        for col in range(3):
            x = 160 + col * 44
            d.rectangle((x, y, x + 24, y + 28), fill=(31, 78, 121, 255))
    for row in range(3):
        y = 252 + row * 50
        d.rectangle((320, y, 344 + 24, y + 28), fill=(31, 78, 121, 255))
    d.rectangle((200, 368, 232, 416), fill=(31, 78, 121, 255))  # door
    d.rectangle((96, 416, 424, 432), fill=(245, 247, 250, 255))  # ground line
    img.save(OUT, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
