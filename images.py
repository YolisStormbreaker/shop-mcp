"""Pictures for the model to look at: product photos (*_item «фото:») and review photos (*_reviews).

Shop CDNs serve images without cookies or referer checks (checked 2026-10-08: wbbasket, ir.ozone.ru,
ae-pic, avatars/storage.mds.yandex, a.lmcdn.ru, cdn-01.goldapple.ru, img.avito.st), so a plain HTTP
fetch is enough — no browser tab, no site lock. Every picture is re-encoded as JPEG no larger than
max_side and also saved to cache/images, so a client that prefers files gets a path.
"""
import hashlib
import io
import ipaddress
import socket
import urllib.parse
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import Image
from PIL import Image as PILImage

DIR = Path(__file__).parent / "cache" / "images"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
MAX_IMAGES = 6           # pictures per call: each costs the model context
MAX_BYTES = 20_000_000


def _public(url):
    """Only http(s) to public addresses: the URLs come from review text and other site content,
    and must not reach this machine or the local network (127.0.0.1:9222 drives the browser)."""
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        addrs = {a[4][0] for a in socket.getaddrinfo(u.hostname, u.port or 443)}
    except OSError:
        return False
    return all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)


class _Redirect(urllib.request.HTTPRedirectHandler):
    """A public host may redirect to a local one: check every hop, not just the first URL."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _public(newurl):
            raise ValueError(f"редирект на непубличный адрес: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_open = urllib.request.build_opener(_Redirect).open


def fetch(url, max_side=1024):
    """(jpeg bytes, saved path, (w, h)) of the picture at url, scaled to fit max_side."""
    if not _public(url):
        raise ValueError("только http(s)-ссылки на публичные адреса")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
    with _open(req, timeout=20) as r:
        raw = r.read(MAX_BYTES)
    im = PILImage.open(io.BytesIO(raw))
    im.load()
    if im.mode in ("RGBA", "LA", "P"):  # transparent PNG/WebP: put it on white, as the site shows it
        im = im.convert("RGBA")
        bg = PILImage.new("RGB", im.size, "white")
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    data = buf.getvalue()
    DIR.mkdir(parents=True, exist_ok=True)
    path = DIR / f"{hashlib.sha1(url.encode()).hexdigest()[:12]}.jpg"
    path.write_bytes(data)
    return data, path, im.size


def images(urls, max_side=1024):
    """[text with paths, Image, Image, …] for up to MAX_IMAGES urls."""
    urls = [u.strip() for u in urls if u and u.strip()]
    pics, lines = [], []
    for u in urls[:MAX_IMAGES]:
        try:
            data, path, (w, h) = fetch(u, max_side)
            pics.append(Image(data=data, format="jpeg"))
            lines.append(f"{path}\t{w}x{h}\t{u}")
        except Exception as e:
            lines.append(f"не скачалось: {str(e)[:120]}\t{u}")
    head = f"картинок: {len(pics)} из {min(len(urls), MAX_IMAGES)} (файл\tразмер\tссылка)"
    if len(urls) > MAX_IMAGES:
        head += f"; ещё {len(urls) - MAX_IMAGES} не загружено — вызови ещё раз с ними"
    return ["\n".join([head] + lines)] + pics


if __name__ == "__main__":
    for bad in ("http://127.0.0.1:9222/json", "http://localhost/", "file:///etc/passwd", "http://192.168.1.1/a.jpg", "ftp://x.ru/a"):
        assert not _public(bad), bad
    assert _public("https://a.lmcdn.ru/")
    print("ok")
