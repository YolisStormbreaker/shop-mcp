"""Самокат (samokat.ru): data the page itself fetched (capture.py), like Wildberries.

The API (api-web.samokat.ru) wants a bearer token and device headers that only the site's code adds, so we
read the responses its own pages get. Samokat's bot check (ServicePipe, /xpvnsulc/) starts after about ten
full page loads in a few minutes (2026-10-13), so once the tab is on the site we move with the site's own
Next.js router — the page fetches the next screen's data without a page load. Prices are in kopecks and
for the user's address (one dark store, «showcase»). No reviews, ratings or favorites on the web site.
"""
import json
import re
import urllib.parse

from capture import capture
from cdp import tab_for
from shoplog import log

SITE = "https://samokat.ru"
CHECK = "/xpvnsulc/"
BLOCKED = ("⚠️ Самокат показал проверку на бота: попроси пользователя выполнить shop-chrome show, пройти её "
           "во вкладке samokat.ru, потом shop-chrome hide. Самокат включает её после ~10 загрузок страниц подряд.")
# Diet tags are categories of «ЗОЖ и веганство» (slugs seen 2026-10-13), not search filters
DIET = {"без лактозы": "bez-laktozy-9", "без глютена": "bez-glyutena-8", "растительное и без глютена": "rastitelnoe-i-bez-glyutena",
        "веган": "rastitelnoe-i-bez-glyutena", "чистый состав": "chistyy-sostav-1", "с протеином": "s-proteinom-1",
        "без белого сахара": "bez-belogo-sakhara-1", "без сахара": "bez-belogo-sakhara-1", "без мяса": "bez-myasa-1",
        "без молока": "bez-moloka-2"}


def _tab():
    tab = tab_for("samokat.ru")
    href = tab.js("location.href") or ""
    if CHECK in href:
        tab.close()
        return None
    return tab


def _open(tab, path, patterns, timeout=15):
    """The page's responses for path: via the site's router when the app is already open, else a page load."""
    here = tab.js("location.hostname.endsWith('samokat.ru') && !!(window.next && window.next.router) ? location.pathname + location.search : ''")
    got = {}
    if here and here != path:
        got = capture(tab, "samokat", None, patterns, timeout=timeout, js=f"window.next.router.push({json.dumps(path)})")
    if len(got) < len(patterns):
        got.update(capture(tab, "samokat", SITE + path, {k: v for k, v in patterns.items() if k not in got}, timeout=20))
    if CHECK in (tab.js("location.href") or ""):
        return None
    return got


def _rub(k):
    return round(k / 100, 2) if isinstance(k, (int, float)) else None


def _nut(a):
    out = {}
    for src, k in (("kilocalories", "kcal"), ("protein", "protein"), ("fats", "fat"), ("carbohydrates", "carbs")):
        try:
            out[k] = float((a or {})[src])
        except (KeyError, TypeError, ValueError):
            pass
    return out


def _listed(p):
    pr = p.get("prices") or {}
    return {"id": p.get("slug") or p.get("id"), "name": p.get("name", ""), "brand": "", "size": "",
            "price": _rub(pr.get("current")), "old": _rub(pr.get("old")), "available": (p.get("quantity") or 0) > 0,
            "url": f"{SITE}/product/{p.get('slug') or p.get('id')}", "rating": None, "reviews": None, "ean": None,
            "nutrition": _nut(p.get("attributes"))}


def search(query, tag=None, sort="popular", page=1, limit=30):
    tab = _tab()
    if tab is None:
        return BLOCKED
    note = ""
    try:
        slug = next((v for k, v in DIET.items() if tag and tag.lower() in k), None) if tag else None
        if tag and not slug:
            note = f"тега «{tag}» у Самоката нет — искал «{query} {tag}» текстом"
            query = f"{query} {tag}".strip()
        if slug:
            got = _open(tab, f"/category/{slug}", {"c": [f"/categories/{slug}"]})
            items = ((got or {}).get("c") or {}).get("products") or []
            words = [w[:5].lower() for w in (query or "").split()]
            items = [p for p in items if all(w in (p.get("name") or "").lower() for w in words)]
            note = f"раздел Самоката «{next(k for k, v in DIET.items() if v == slug)}» (первые 40 товаров раздела)" + (f", названия со словами «{query}»" if words else "")
        else:
            got = _open(tab, "/search?value=" + urllib.parse.quote(query), {"s": ["/search/products"]})
            items = [x for r in ((got or {}).get("s") or {}).get("result") or [] for x in r.get("items") or [] if x.get("type") == "PRODUCT"]
    finally:
        tab.close()
    if got is None:
        return BLOCKED
    rows = [_listed(p) for p in items]
    if sort != "popular":
        key = {"price": lambda x: x["price"] or 1e9, "price_desc": lambda x: -(x["price"] or 0),
               "discount": lambda x: (x["price"] or 0) / (x["old"] or x["price"] or 1), "rating": lambda x: 0}[sort]
        rows.sort(key=key)
        note += ("\n" if note else "") + "Самокат не сортирует: отсортированы полученные товары"
    start = (page - 1) * limit
    return {"items": rows[start:start + limit], "total": len(rows), "note": note.strip(), "facets": list(DIET),
            "url": SITE + "/search?value=" + urllib.parse.quote(query)}


def _slug(id_or_url):
    s = str(id_or_url).strip()
    m = re.search(r"/product/([\w-]+)", s)
    return m.group(1) if m else s


def product(id_or_url):
    slug = _slug(id_or_url)
    tab = _tab()
    if tab is None:
        return BLOCKED
    try:
        got = _open(tab, f"/product/{slug}", {"p": ["/products/", slug]})
    finally:
        tab.close()
    if got is None:
        return BLOCKED
    c = got.get("p")
    if not c:
        log.warning("samokat product %s: no card response", slug)
        return f"Самокат: карточка {slug} не пришла (неверная ссылка или товара нет на витрине для адреса пользователя)"
    attrs = {a.get("displayName"): (f"{a.get('value')} {a.get('unit') or ''}".strip(), a.get("type")) for a in c.get("detailsAttributes") or []}
    comp = (attrs.get("Состав") or ("", ""))[0]
    size = next((v for k, (v, _) in attrs.items() if k in ("Объём", "Вес", "Масса", "Количество в упаковке")), "")
    skip = {"Состав", "Бренд", "Примечание", "Документы качества"}
    info = [f"{k}: {'да' if v == 'TRUE' else 'нет' if v == 'FALSE' else v}" for k, (v, t) in attrs.items()
            if k not in skip and "на весь продукт" not in k]
    p = _listed(c)
    pr = c.get("prices") or {}
    extra = ["доставка: ~15 мин из ближайшего склада, заказ от 200 ₽ (условия сайта для адреса пользователя)"]
    if pr.get("pickup") and pr.get("pickup") != pr.get("current"):
        extra.append(f"самовывоз: {_rub(pr['pickup'])} ₽")
    extra.append(f"в наличии {c.get('quantity', 0)} шт" if c.get("quantity") else "")
    extra.append("характеристики: " + "; ".join(info))
    p.update(id=c.get("slug") or slug, brand=(attrs.get("Бренд") or ("", ""))[0], size=size,
             photos=[m["url"].split("?")[0] for m in c.get("media") or [] if m.get("url")],
             description=re.sub(r"<[^>]+>", " ", c.get("description") or "").strip(), composition=comp,
             composition_extra="; ".join(x for x in info if re.search(r"жирн|какао|мяс|сок|без ", x, re.I)), extra=[x for x in extra if x])
    return p
