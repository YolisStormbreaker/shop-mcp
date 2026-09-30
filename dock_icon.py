# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets>=13", "pillow"]
# ///
"""Give the shop Chrome its own Dock and ⌘Tab icon, so it is not mistaken for the everyday Chrome.

The installed Chrome icon is repainted in the muted colours of a Karelian lake shore in autumn and
set for this Chrome process only (CDP Browser.setDockTile); the main Chrome keeps its icon. The tile
lives as long as the process, so the LaunchAgent runs this at every start: shop-chrome icon.
--save PATH also writes the PNG.
"""
import base64
import colorsys
import io
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from cdp import Tab, _http  # noqa: E402

ICNS = "/Applications/Google Chrome.app/Contents/Resources/app.icns"
# hue of each Chrome colour (degrees) → its replacement
PALETTE = {
    0: "#b8826a",    # red → rowan berries, rust
    45: "#cdb27a",   # yellow → birch leaves
    130: "#7d8f72",  # green → spruce and moss
    215: "#7f9aa8",  # blue → lake water
}


def _hsv(hex_color):
    return colorsys.rgb_to_hsv(*(int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)))


def repaint(img):
    targets = {deg: _hsv(c) for deg, c in PALETTE.items()}
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if not a:
                continue
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if s < (0.08 if a < 255 else 0.25):  # the white ring, the plate and grey shadows stay; tinted soft glow goes too
                continue
            deg = h * 360
            th, ts, tv = targets[min(targets, key=lambda k: min(abs(deg - k), 360 - abs(deg - k)))]
            # keep the icon's shading: saturation and brightness relative to Chrome's own
            nr, ng, nb = colorsys.hsv_to_rgb(th, ts * min(1, s / 0.7), min(1, tv * v / 0.85))
            px[x, y] = (round(nr * 255), round(ng * 255), round(nb * 255), a)
    return img


def main():
    with tempfile.TemporaryDirectory() as d:
        png = Path(d) / "chrome.png"
        subprocess.run(["sips", "-s", "format", "png", "-Z", "512", ICNS, "--out", str(png)], check=True, capture_output=True)
        img = repaint(Image.open(png).convert("RGBA"))
    if "--save" in sys.argv:
        img.save(sys.argv[sys.argv.index("--save") + 1])
    buf = io.BytesIO()
    img.save(buf, "PNG")
    browser = Tab(_http("/json/version")["webSocketDebuggerUrl"])
    try:
        browser.call("Browser.setDockTile", image=base64.b64encode(buf.getvalue()).decode())
    finally:
        browser.close()


if __name__ == "__main__":
    main()
