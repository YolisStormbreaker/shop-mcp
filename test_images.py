"""shop_images: which links may be fetched (public http(s) only, every redirect hop too), how a picture is
re-encoded and saved, and the text that goes with the pictures.
No network: DNS answers and HTTP bodies are scripted; files go to a temp dir, never cache/images.
Run: .venv/bin/python -B -m unittest -v test_images"""
import hashlib
import io
import ipaddress
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

import images

DNS = {"a.lmcdn.ru": ["185.65.148.7"], "ir.ozone.ru": ["2a02:6b8::1", "95.163.33.4"], "localhost": ["127.0.0.1", "::1"],
       "router.lan": ["192.168.1.1"], "cdn.mixed.test": ["8.8.8.8", "10.0.0.5"], "v6local.test": ["fe80::1%en0"]}


def getaddrinfo(host, port):
    try:
        ipaddress.ip_address(host.split("%")[0])
        addrs = [host]                                  # a literal address resolves to itself
    except ValueError:
        if host not in DNS:
            raise socket.gaierror(8, "nodename nor servname provided, or not known") from None
        addrs = DNS[host]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addrs]


def png(size, mode="RGB", color="red"):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


class PublicTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(images.socket, "getaddrinfo", side_effect=getaddrinfo)
        self.lookup = p.start()
        self.addCleanup(p.stop)

    def test_public_hosts_pass(self):
        for url in ("https://a.lmcdn.ru/img600x866/R/T/RTLAB.jpg", "http://ir.ozone.ru/s3/x.jpg", "https://95.163.33.4/x.jpg"):
            with self.subTest(url):
                self.assertTrue(images._public(url))

    def test_this_machine_and_the_local_network_do_not(self):
        for url in ("http://localhost:9222/json", "http://127.0.0.1:9222/json", "http://router.lan/a.jpg",
                    "http://[fe80::1%25en0]/a.jpg", "http://v6local.test/a.jpg", "http://[::1]/a.jpg"):
            with self.subTest(url):
                self.assertFalse(images._public(url))

    def test_one_private_address_among_public_ones_is_enough_to_refuse(self):
        self.assertFalse(images._public("https://cdn.mixed.test/a.jpg"))

    def test_other_schemes_and_hostless_links_are_refused_without_a_lookup(self):
        for url in ("file:///etc/passwd", "ftp://a.lmcdn.ru/a.jpg", "data:image/png;base64,AAAA", "https:///a.jpg", "a.lmcdn.ru/a.jpg"):
            with self.subTest(url):
                self.assertFalse(images._public(url))
        self.lookup.assert_not_called()

    def test_unknown_host_is_refused(self):
        self.assertFalse(images._public("https://no-such-host.test/a.jpg"))

    def test_lookup_uses_the_links_port(self):
        images._public("http://a.lmcdn.ru:8080/a.jpg")
        images._public("http://a.lmcdn.ru/a.jpg")
        self.assertEqual([c.args for c in self.lookup.call_args_list], [("a.lmcdn.ru", 8080), ("a.lmcdn.ru", 443)])

    def test_redirect_to_a_public_host_is_followed(self):
        req = urllib.request.Request("https://a.lmcdn.ru/a.jpg")
        new = images._Redirect().redirect_request(req, None, 302, "Found", {}, "https://ir.ozone.ru/b.jpg")
        self.assertEqual(new.full_url, "https://ir.ozone.ru/b.jpg")

    def test_redirect_to_this_machine_is_refused(self):
        req = urllib.request.Request("https://a.lmcdn.ru/a.jpg")
        with self.assertRaisesRegex(ValueError, "^редирект на непубличный адрес: http://127.0.0.1:9222/json$"):
            images._Redirect().redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:9222/json")

    def test_downloads_check_every_redirect_hop(self):
        self.assertTrue(any(isinstance(h, images._Redirect) for h in images._open.__self__.handlers))


class FetchTests(unittest.TestCase):
    URL = "https://a.lmcdn.ru/img600x866/R/T/RTLAB.jpg"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "images"           # made on first save
        for p in (patch.object(images, "DIR", self.dir), patch.object(images.socket, "getaddrinfo", side_effect=getaddrinfo)):
            self.addCleanup(p.stop)
            p.start()

    def fetch(self, body, url=URL, **kw):
        answer = MagicMock()
        answer.__enter__.return_value.read.return_value = body
        self.read = answer.__enter__.return_value.read
        with patch.object(images, "_open", return_value=answer) as self.opened:
            return images.fetch(url, **kw)

    def test_picture_is_jpeg_scaled_to_max_side_and_saved_by_its_link(self):
        data, path, size = self.fetch(png((2000, 1000)))
        self.assertEqual(size, (1024, 512))
        self.assertEqual(path, self.dir / f"{hashlib.sha1(self.URL.encode()).hexdigest()[:12]}.jpg")
        self.assertEqual(path.read_bytes(), data)
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual((im.format, im.size, im.mode), ("JPEG", (1024, 512), "RGB"))

    def test_request_looks_like_the_browser_and_is_bounded(self):
        self.fetch(png((10, 10)))
        req, = self.opened.call_args.args
        self.assertEqual(req.full_url, self.URL)
        self.assertEqual(req.get_header("User-agent"), images.UA)
        self.assertTrue(req.get_header("Accept").startswith("image/avif,image/webp,image/*"))
        self.assertEqual(self.opened.call_args.kwargs, {"timeout": 20})
        self.read.assert_called_once_with(images.MAX_BYTES)

    def test_smaller_max_side(self):
        self.assertEqual(self.fetch(png((900, 1200)), max_side=300)[2], (225, 300))

    def test_small_picture_is_not_enlarged(self):
        self.assertEqual(self.fetch(png((120, 80)))[2], (120, 80))

    def test_transparency_is_put_on_white_as_the_site_shows_it(self):
        im = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
        im.paste((200, 0, 0, 255), (20, 0, 40, 20))     # right half opaque red, left half transparent
        for mode in ("RGBA", "LA", "P"):
            with self.subTest(mode):
                buf = io.BytesIO()
                (im if mode == "RGBA" else im.convert(mode)).save(buf, "PNG")
                data = self.fetch(buf.getvalue())[0]
                with Image.open(io.BytesIO(data)) as out:
                    self.assertTrue(all(c > 245 for c in out.getpixel((5, 10))), out.getpixel((5, 10)))
                    self.assertLess(out.getpixel((35, 10))[1], 120)   # the opaque half keeps its colour

    def test_link_to_this_machine_is_not_fetched(self):
        with self.assertRaisesRegex(ValueError, "^только http\\(s\\)-ссылки на публичные адреса$"):
            self.fetch(png((10, 10)), url="http://127.0.0.1:9222/json/list")
        self.opened.assert_not_called()
        self.assertFalse(self.dir.exists())

    def test_page_instead_of_a_picture_is_an_error_and_nothing_is_saved(self):
        with self.assertRaises(Exception):
            self.fetch(b"<html>403 Forbidden</html>")
        self.assertFalse(self.dir.exists())


class ImagesTests(unittest.TestCase):
    def images(self, urls, max_side=1024):
        def fetch(url, side):
            if "bad" in url:
                raise OSError("HTTP Error 404: Not Found " + "x" * 200)
            return f"jpeg {url}".encode(), Path(f"/cache/images/{url[-5]}.jpg"), (side, side // 2)
        with patch.object(images, "fetch", side_effect=fetch) as fetched:
            out = images.images(urls, max_side)
        self.fetched = [c.args for c in fetched.call_args_list]
        return out

    def test_text_lists_the_files_and_the_pictures_follow(self):
        out = self.images(["https://a.test/1.jpg", "https://a.test/2.jpg"], max_side=512)
        self.assertEqual(out[0], "картинок: 2 из 2 (файл\tразмер\tссылка)\n"
                                 "/cache/images/1.jpg\t512x256\thttps://a.test/1.jpg\n"
                                 "/cache/images/2.jpg\t512x256\thttps://a.test/2.jpg")
        self.assertEqual([(p.data, p.to_image_content().mimeType) for p in out[1:]],
                         [(b"jpeg https://a.test/1.jpg", "image/jpeg"), (b"jpeg https://a.test/2.jpg", "image/jpeg")])
        self.assertEqual(self.fetched, [("https://a.test/1.jpg", 512), ("https://a.test/2.jpg", 512)])

    def test_blank_links_are_dropped_and_others_trimmed(self):
        out = self.images(["", "  ", None, " https://a.test/1.jpg\n"])
        self.assertEqual(self.fetched, [("https://a.test/1.jpg", 1024)])
        self.assertTrue(out[0].startswith("картинок: 1 из 1 "))

    def test_a_failed_picture_is_named_and_the_rest_still_come(self):
        out = self.images(["https://a.test/bad.jpg", "https://a.test/2.jpg"])
        lines = out[0].split("\n")
        self.assertEqual(lines[0], "картинок: 1 из 2 (файл\tразмер\tссылка)")
        self.assertEqual(lines[1], "не скачалось: " + ("HTTP Error 404: Not Found " + "x" * 200)[:120] + "\thttps://a.test/bad.jpg")
        self.assertEqual(len(out), 2)

    def test_more_than_six_links_ask_for_another_call(self):
        urls = [f"https://a.test/{i}.jpg" for i in range(1, 9)]
        out = self.images(urls)
        self.assertEqual([u for u, _ in self.fetched], urls[:6])
        self.assertEqual(out[0].split("\n")[0], "картинок: 6 из 6 (файл\tразмер\tссылка); ещё 2 не загружено — вызови ещё раз с ними")
        self.assertEqual(len(out), 7)

    def test_no_links(self):
        self.assertEqual(self.images([]), ["картинок: 0 из 0 (файл\tразмер\tссылка)"])


if __name__ == "__main__":
    unittest.main()
