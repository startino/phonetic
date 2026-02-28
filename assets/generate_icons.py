"""Generate tray icon assets programmatically."""
from PIL import Image, ImageDraw


def make_mic_icon(color: str, bg: str = "transparent", size: int = 64) -> Image.Image:
    """Generate a microphone icon."""
    if bg == "transparent":
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    else:
        img = Image.new("RGBA", (size, size), bg)
    draw = ImageDraw.Draw(img)

    # Microphone body
    mic_w = size // 3
    mic_h = size // 2
    mic_x = (size - mic_w) // 2
    mic_y = size // 8

    # Mic head (ellipse top)
    draw.ellipse([mic_x, mic_y, mic_x + mic_w, mic_y + mic_w], fill=color)
    # Mic body (rectangle)
    draw.rectangle([mic_x, mic_y + mic_w // 2, mic_x + mic_w, mic_y + mic_h], fill=color)
    # Mic bottom (ellipse)
    draw.ellipse(
        [mic_x, mic_y + mic_h - mic_w // 2, mic_x + mic_w, mic_y + mic_h + mic_w // 2],
        fill=color,
    )
    # Stand
    stand_x = size // 2
    stand_top = mic_y + mic_h + mic_w // 4
    stand_bot = stand_top + size // 6
    draw.line([(stand_x, stand_top), (stand_x, stand_bot)], fill=color, width=max(2, size // 16))
    # Base
    base_w = size // 3
    draw.line(
        [(stand_x - base_w // 2, stand_bot), (stand_x + base_w // 2, stand_bot)],
        fill=color, width=max(2, size // 16),
    )

    return img


if __name__ == "__main__":
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Idle icon (gray/white)
    idle = make_mic_icon("#cccccc", size=64)
    idle.save(os.path.join(script_dir, "icon.png"))

    # Recording icon (red)
    recording = make_mic_icon("#ff4444", size=64)
    recording.save(os.path.join(script_dir, "icon_recording.png"))

    # Windows .ico (multi-size)
    ico_sizes = [make_mic_icon("#cccccc", size=s) for s in [16, 32, 48, 64, 128, 256]]
    ico_sizes[0].save(os.path.join(script_dir, "icon.ico"), sizes=[(s.width, s.height) for s in ico_sizes])

    print("Icons generated in", script_dir)
