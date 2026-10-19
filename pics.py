"""Product pictures for the *_item_images tools: download from the shop CDN, hand back as MCP images.

Sellers often put the kit contents, sizes and specs on pictures, not in the text (2026-10-19:
the Ozon Multifix card listed its holders only on picture #1).  The CDNs are public, so no tab
is needed for the download.  They also resize on request, which keeps a picture near 1000 px
(about 1.3k tokens) without an image library here.
"""
from concurrent.futures import ThreadPoolExecutor
import urllib.request

from mcp.server.fastmcp import Image

from shoplog import log

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")
FORMATS = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
MAX_BYTES = 3 * 1024 * 1024


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/webp,image/jpeg,image/png,*/*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        ctype = r.headers.get_content_type()
        data = r.read(MAX_BYTES + 1)
    if ctype not in FORMATS:
        raise ValueError(f"не картинка: {ctype}")
    if len(data) > MAX_BYTES:
        raise ValueError(f"больше {MAX_BYTES // 1024 // 1024} МБ")
    return Image(data=data, format=FORMATS[ctype])


def fetch(head, pics, limit):
    """[head text, image, image, …] for MCP.  pics: [(label, url)].  A picture that fails
    becomes a text line, so the numbering still matches the card."""
    pics = pics[:max(0, limit)]
    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(lambda p: _try(p[1]), pics))
    out = [head]
    for (label, url), res in zip(pics, results):
        if isinstance(res, Image):
            out += [label, res]
        else:
            log.warning("picture %s: %s", url, res)
            out.append(f"{label}: не скачалась ({res}) {url}")
    return out


def _try(url):
    try:
        return _get(url)
    except Exception as e:
        return str(e)[:120]
