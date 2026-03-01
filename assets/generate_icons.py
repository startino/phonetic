"""Generate platform icon assets from the source icon.png."""

import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw


def _add_recording_dot(icon: Image.Image) -> Image.Image:
    """Overlay a red recording dot on the bottom-right of the icon."""
    img = icon.copy()
    size = img.width
    draw = ImageDraw.Draw(img)

    dot_r = size // 6
    margin = size // 16
    cx = size - margin - dot_r
    cy = size - margin - dot_r

    # White outline for visibility
    outline = dot_r // 6 or 1
    draw.ellipse(
        [cx - dot_r - outline, cy - dot_r - outline, cx + dot_r + outline, cy + dot_r + outline],
        fill="white",
    )
    draw.ellipse(
        [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
        fill="#ff2222",
    )
    return img


def generate_recording_icon(source: Image.Image, out_path: str) -> None:
    """Generate the recording variant with a red dot overlay."""
    recording = _add_recording_dot(source)
    recording.save(out_path)
    print(f"  -> {os.path.basename(out_path)}")


def generate_ico(source: Image.Image, out_path: str) -> None:
    """Generate a Windows .ico with multiple sizes."""
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    source.save(out_path, format="ICO", sizes=sizes)
    print(f"  -> {os.path.basename(out_path)}")


def generate_icns(source: Image.Image, out_path: str) -> None:
    """Generate a macOS .icns via iconutil (macOS only, skips elsewhere)."""
    if sys.platform != "darwin":
        print("  -> icon.icns skipped (not macOS)")
        return

    iconset_sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        iconset_dir = os.path.join(tmpdir, "icon.iconset")
        os.makedirs(iconset_dir)

        for name, size in iconset_sizes.items():
            resized = source.resize((size, size), Image.LANCZOS)
            resized.save(os.path.join(iconset_dir, name))

        try:
            subprocess.run(
                ["iconutil", "-c", "icns", iconset_dir, "-o", out_path],
                check=True,
                capture_output=True,
            )
            print(f"  -> {os.path.basename(out_path)}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"  -> icon.icns failed: {e}")


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_path = os.path.join(script_dir, "icon.png")

    if not os.path.exists(source_path):
        print(f"Error: {source_path} not found", file=sys.stderr)
        sys.exit(1)

    source = Image.open(source_path).convert("RGBA")
    print(f"Source: {source.width}x{source.height} icon.png")

    generate_recording_icon(source, os.path.join(script_dir, "icon_recording.png"))
    generate_ico(source, os.path.join(script_dir, "icon.ico"))
    generate_icns(source, os.path.join(script_dir, "icon.icns"))

    # Tray icon variants (transparent background)
    tray_path = os.path.join(script_dir, "icon_tray.png")
    if os.path.exists(tray_path):
        tray_source = Image.open(tray_path).convert("RGBA")
        print(f"Source: {tray_source.width}x{tray_source.height} icon_tray.png")
        generate_recording_icon(tray_source, os.path.join(script_dir, "icon_tray_recording.png"))

    print("Done.")
