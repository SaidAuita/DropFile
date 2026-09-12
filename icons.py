"""
Dynamic icon generator for DropFile system tray and Windows .ico executable icon.
Generates clean, scalable, high-resolution icons using Pillow with badges for:
- idle: blue cloud with green checkmark
- syncing: blue cloud with sync arrows
- error: blue cloud with red exclamation
- paused: blue cloud with yellow pause symbol
"""

from pathlib import Path
from PIL import Image, ImageDraw


def create_tray_icon(state: str = "idle", size: int = 64) -> Image.Image:
    """
    Creates an RGBA PIL Image representing the tray icon for a given state and pixel size.
    state: "idle" | "syncing" | "error" | "paused"
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    scale = size / 64.0

    def s(val: float) -> int:
        return int(round(val * scale))

    def sc(coords):
        return tuple(s(x) for x in coords)

    cloud_color = (26, 115, 232, 255)

    # Draw cloud puffs
    # Left puff
    draw.ellipse(sc((8, 22, 30, 44)), fill=cloud_color)
    # Center-top puff (larger)
    draw.ellipse(sc((18, 12, 46, 40)), fill=cloud_color)
    # Right puff
    draw.ellipse(sc((34, 22, 56, 44)), fill=cloud_color)
    # Bottom connector
    draw.rectangle(sc((19, 26, 45, 44)), fill=cloud_color)

    # Inner soft highlight
    draw.ellipse(sc((22, 16, 42, 34)), fill=(66, 145, 245, 255))

    # Badge in bottom-right corner
    badge_bg = sc((34, 34, 62, 62))
    w2 = max(1, s(2))
    w3 = max(1, s(3))

    if state == "idle":
        # Green circle with white checkmark
        draw.ellipse(badge_bg, fill=(40, 167, 69, 255), outline=(255, 255, 255, 255), width=w2)
        draw.line(sc((40, 48, 46, 54)), fill=(255, 255, 255, 255), width=w3)
        draw.line(sc((46, 54, 56, 40)), fill=(255, 255, 255, 255), width=w3)

    elif state == "syncing":
        # Cyan/Blue circle with sync arrows
        draw.ellipse(badge_bg, fill=(0, 123, 255, 255), outline=(255, 255, 255, 255), width=w2)
        draw.arc(sc((39, 39, 57, 57)), start=30, end=190, fill=(255, 255, 255, 255), width=w3)
        draw.arc(sc((39, 39, 57, 57)), start=210, end=370, fill=(255, 255, 255, 255), width=w3)
        draw.polygon([sc((46, 37)), sc((49, 41)), sc((43, 42))], fill=(255, 255, 255, 255))
        draw.polygon([sc((50, 59)), sc((47, 55)), sc((53, 54))], fill=(255, 255, 255, 255))

    elif state == "error":
        # Red circle with white exclamation mark
        draw.ellipse(badge_bg, fill=(220, 53, 69, 255), outline=(255, 255, 255, 255), width=w2)
        draw.line(sc((48, 39, 48, 49)), fill=(255, 255, 255, 255), width=w3)
        draw.ellipse(sc((46, 52, 50, 56)), fill=(255, 255, 255, 255))

    elif state == "paused":
        # Amber/Yellow circle with pause bars
        draw.ellipse(badge_bg, fill=(255, 193, 7, 255), outline=(255, 255, 255, 255), width=w2)
        draw.rectangle(sc((43, 40, 46, 56)), fill=(40, 40, 40, 255))
        draw.rectangle(sc((50, 40, 53, 56)), fill=(40, 40, 40, 255))

    return img


def create_app_icon_ico(filepath: str | Path = "icon.ico") -> Path:
    """Renders a multi-resolution Windows .ico icon file (16, 24, 32, 48, 64, 128, 256 px)."""
    p = Path(filepath)
    img256 = create_tray_icon("idle", size=256)
    img256.save(
        str(p),
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return p


if __name__ == "__main__":
    create_app_icon_ico("icon.ico")
    print("Generated icon.ico successfully.")
