"""
Dynamic icon generator for DropFile system tray.
Generates clean, high-resolution icons using Pillow with badges for:
- idle: blue cloud with green checkmark
- syncing: blue cloud with sync arrows
- error: blue cloud with red exclamation
- paused: blue cloud with yellow pause symbol
"""

from PIL import Image, ImageDraw


def create_tray_icon(state: str = "idle", size: int = 64) -> Image.Image:
    """
    Creates an RGBA PIL Image representing the tray icon for a given state.
    state: "idle" | "syncing" | "error" | "paused"
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Base: Stylized Dropbox-like cloud/box
    # Cloud base coordinates
    # Primary color: Modern deep sky blue #1A73E8
    cloud_color = (26, 115, 232, 255)
    cloud_shadow = (20, 90, 180, 255)

    # Draw cloud puffs
    # Left puff
    draw.ellipse((8, 22, 30, 44), fill=cloud_color)
    # Center-top puff (larger)
    draw.ellipse((18, 12, 46, 40), fill=cloud_color)
    # Right puff
    draw.ellipse((34, 22, 56, 44), fill=cloud_color)
    # Bottom connector
    draw.rectangle((19, 26, 45, 44), fill=cloud_color)

    # Inner soft highlight
    draw.ellipse((22, 16, 42, 34), fill=(66, 145, 245, 255))

    # Badge in bottom-right corner (coords: 34, 34 to 62, 62)
    badge_bg = (34, 34, 62, 62)

    if state == "idle":
        # Green circle with white checkmark
        draw.ellipse(badge_bg, fill=(40, 167, 69, 255), outline=(255, 255, 255, 255), width=2)
        # Checkmark
        draw.line((40, 48, 46, 54), fill=(255, 255, 255, 255), width=3)
        draw.line((46, 54, 56, 40), fill=(255, 255, 255, 255), width=3)

    elif state == "syncing":
        # Cyan/Blue circle with sync arrows
        draw.ellipse(badge_bg, fill=(0, 123, 255, 255), outline=(255, 255, 255, 255), width=2)
        # Top arc
        draw.arc((39, 39, 57, 57), start=30, end=190, fill=(255, 255, 255, 255), width=3)
        # Bottom arc
        draw.arc((39, 39, 57, 57), start=210, end=370, fill=(255, 255, 255, 255), width=3)
        # Arrow heads
        draw.polygon([(46, 37), (49, 41), (43, 42)], fill=(255, 255, 255, 255))
        draw.polygon([(50, 59), (47, 55), (53, 54)], fill=(255, 255, 255, 255))

    elif state == "error":
        # Red circle with white exclamation mark
        draw.ellipse(badge_bg, fill=(220, 53, 69, 255), outline=(255, 255, 255, 255), width=2)
        # Exclamation line
        draw.line((48, 39, 48, 49), fill=(255, 255, 255, 255), width=3)
        # Exclamation dot
        draw.ellipse((46, 52, 50, 56), fill=(255, 255, 255, 255))

    elif state == "paused":
        # Amber/Yellow circle with pause bars
        draw.ellipse(badge_bg, fill=(255, 193, 7, 255), outline=(255, 255, 255, 255), width=2)
        # Two vertical bars
        draw.rectangle((43, 40, 46, 56), fill=(40, 40, 40, 255))
        draw.rectangle((50, 40, 53, 56), fill=(40, 40, 40, 255))

    return img


if __name__ == "__main__":
    for s in ["idle", "syncing", "error", "paused"]:
        icon = create_tray_icon(s)
        icon.save(f"icon_{s}.png")
    print("Icons generated.")
