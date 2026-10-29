"""dock_icon: Chrome's colours repainted into the autumn palette, the rest of the icon kept, and the result
set as this Chrome's Dock tile.  No sips, no Chrome: both are faked.  Run: .venv/bin/python -B -m unittest -v test_dock_icon"""
import base64
import colorsys
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

import dock_icon


def chrome(deg, s=0.7, v=0.85, a=255):
    """A pixel of Chrome's own icon colour at hue deg."""
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(deg / 360, s, v)) + (a,)


def rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def pixels(im):
    return [im.getpixel((x, y)) for y in range(im.height) for x in range(im.width)]


def repaint(*colours):
    img = Image.new("RGBA", (len(colours), 1))
    img.putdata(colours)
    return pixels(dock_icon.repaint(img))


class RepaintTests(unittest.TestCase):
    def assertColour(self, got, want, alpha=255):
        self.assertEqual(got[3], alpha)
        for g, w in zip(got[:3], want):
            self.assertAlmostEqual(g, w, delta=1, msg=f"{got} != {want}")

    def test_each_chrome_colour_becomes_its_palette_colour(self):
        got = repaint(chrome(0), chrome(45), chrome(130), chrome(215))
        for pixel, deg in zip(got, (0, 45, 130, 215)):
            with self.subTest(deg):
                self.assertColour(pixel, rgb(dock_icon.PALETTE[deg]))

    def test_nearest_hue_wraps_around_red(self):
        self.assertColour(repaint(chrome(350))[0], rgb(dock_icon.PALETTE[0]))   # 10° from red, 135° from blue

    def test_hues_between_go_to_the_nearer_one(self):
        self.assertColour(repaint(chrome(100))[0], rgb(dock_icon.PALETTE[130]))
        self.assertColour(repaint(chrome(170))[0], rgb(dock_icon.PALETTE[130]))
        self.assertColour(repaint(chrome(175))[0], rgb(dock_icon.PALETTE[215]))

    def test_shading_is_kept(self):
        dark, = repaint(chrome(215, v=0.425))
        th, ts, tv = colorsys.rgb_to_hsv(*(c / 255 for c in rgb(dock_icon.PALETTE[215])))
        h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in dark[:3]))
        self.assertAlmostEqual(v, tv / 2, delta=0.01)
        self.assertAlmostEqual(h, th, delta=0.01)
        pale, = repaint(chrome(215, s=0.35))
        self.assertAlmostEqual(colorsys.rgb_to_hsv(*(c / 255 for c in pale[:3]))[1], ts / 2, delta=0.02)

    def test_ring_plate_and_shadows_stay(self):
        kept = [(0, 0, 0, 0), (200, 30, 30, 0), (255, 255, 255, 255), (120, 120, 120, 255),
                (200, 170, 170, 255),                   # greyish, s 0.15 < 0.25
                (200, 190, 190, 128)]                   # faint glow, s 0.05 < 0.08
        self.assertEqual(repaint(*kept), kept)

    def test_tinted_soft_glow_is_repainted_with_its_alpha(self):
        glow, = repaint((200, 170, 170, 128))            # s 0.15: kept when opaque, repainted when translucent
        self.assertNotEqual(glow[:3], (200, 170, 170))
        self.assertEqual(glow[3], 128)
        th = colorsys.rgb_to_hsv(*(c / 255 for c in rgb(dock_icon.PALETTE[0])))[0]
        self.assertAlmostEqual(colorsys.rgb_to_hsv(*(c / 255 for c in glow[:3]))[0], th, delta=0.02)


class MainTests(unittest.TestCase):
    SOURCE = [chrome(0), (255, 255, 255, 255), chrome(215), (0, 0, 0, 0)]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def sips(self, argv, **kw):
        icon = Image.new("RGBA", (4, 1))
        icon.putdata(self.SOURCE)
        icon.save(argv[argv.index("--out") + 1])

    def main(self, *argv, browser=None):
        browser = browser or MagicMock()
        with patch.object(dock_icon.subprocess, "run", side_effect=self.sips) as run, \
                patch.object(dock_icon, "_http", return_value={"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/B"}) as http, \
                patch.object(dock_icon, "Tab", return_value=browser) as tab, patch.object(dock_icon.sys, "argv", ["dock_icon.py", *argv]):
            dock_icon.main()
        self.run_args = run.call_args
        http.assert_called_once_with("/json/version")
        tab.assert_called_once_with("ws://127.0.0.1:9222/devtools/browser/B")
        return browser

    def tile(self, browser):
        (method,), kw = browser.call.call_args
        self.assertEqual(method, "Browser.setDockTile")
        return Image.open(io.BytesIO(base64.b64decode(kw["image"])))

    def test_repainted_icon_is_set_on_the_browser_and_the_connection_closed(self):
        browser = self.main()
        with self.tile(browser) as im:
            self.assertEqual(im.format, "PNG")
            self.assertEqual(pixels(im.convert("RGBA")), repaint(*self.SOURCE))
        browser.close.assert_called_once_with()
        argv = self.run_args.args[0]
        self.assertEqual(argv[:5], ["sips", "-s", "format", "png", "-Z"])
        self.assertEqual(argv[5:7], ["512", dock_icon.ICNS])
        self.assertEqual(self.run_args.kwargs, {"check": True, "capture_output": True})

    def test_save_writes_the_same_picture(self):
        out = self.dir / "icon.png"
        browser = self.main("--save", str(out))
        with Image.open(out) as saved, self.tile(browser) as tile:
            self.assertEqual(pixels(saved), pixels(tile))

    def test_connection_is_closed_when_chrome_refuses_the_tile(self):
        browser = MagicMock()
        browser.call.side_effect = RuntimeError("Browser.setDockTile: {'code': -32601}")
        with self.assertRaisesRegex(RuntimeError, "Browser.setDockTile"):
            self.main(browser=browser)
        browser.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
