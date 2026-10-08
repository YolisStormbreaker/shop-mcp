"""Ozon: search, product card, reviews and cart via the site's own JSON API, called from the logged-in tab.

No navigation per request: fetch() runs inside an ozon.ru page, so cookies and
anti-bot tokens are the browser's own. Stops at the cart, never checks out.
"""
import json
import re
import time
import urllib.parse

from cdp import tab_for
from shoplog import dump, log

SORTS = ("score", "new", "price", "price_desc", "rating", "discount")
API = "/api/entrypoint-api.bx/page/json/v2?url="
_last_call = 0.0
DATE_RE = re.compile(r"Сегодня|Завтра|Послезавтра|\d+\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)|\d+\s*(?:час|дн)", re.I)


def _tab():
    tab = tab_for("ozon.ru")
    if "ozon.ru" not in (tab.js("location.hostname") or ""):
        tab.goto("https://www.ozon.ru/", "ozon", wait_js="document.readyState === 'complete'")
    return tab


def _fetch(tab, path, method="GET", body=None, retried=False):
    global _last_call
    gap = 1.5 - (time.time() - _last_call)
    if gap > 0:
        time.sleep(gap)
    _last_call = time.time()
    opts = {"method": method, "credentials": "include"}
    if body is not None:
        opts["headers"] = {"Content-Type": "application/json"}
        opts["body"] = json.dumps(body)
    r = tab.js(f"fetch({json.dumps(path)}, {json.dumps(opts)}).then(async r => ({{s: r.status, b: await r.text()}}))")
    try:
        return json.loads(r["b"])
    except ValueError:
        pass
    saved = dump("ozon", r["s"], r["b"])
    if retried:
        log.error("ozon %s %s: %s again after reload, body %s", method, path[:150], r["s"], saved)
        raise RuntimeError(f"Ozon ответил {r['s']} не-JSON и после перезагрузки вкладки "
                           f"(вероятно, проверка на бота: shop-chrome show). Ответ целиком: {saved}")
    # A tab left idle for hours loses its anti-bot cookie; fetch() cannot pass the JS check,
    # a real page load can. Seen 2026-09-25 after ~20 h idle.
    log.warning("ozon %s %s: %s non-JSON, body %s; reloading tab and retrying", method, path[:150], r["s"], saved)
    tab.goto("https://www.ozon.ru/", "ozon", wait_js="document.readyState === 'complete'")
    time.sleep(3)
    return _fetch(tab, path, method, body, retried=True)


def _page(tab, url):
    return _fetch(tab, API + urllib.parse.quote(url, safe=""))


def _widgets(page, prefix):
    return [json.loads(v) for k, v in page.get("widgetStates", {}).items() if k.startswith(prefix)]


def _texts(o):
    """All text/title strings under a node, in order."""
    out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("text", "title") and isinstance(v, str):
                out.append(v)
            elif k not in ("trackingInfo", "testInfo", "action", "common"):
                out += _texts(v)
    elif isinstance(o, list):
        for v in o:
            out += _texts(v)
    return out


def _tile(it):
    title = price = old = rating = reviews = ""
    for m in it.get("mainState", []):
        if m.get("id") == "name" or m.get("type") == "textDS" and not title:
            title = m.get("textDS", {}).get("text", title)
        elif m["type"] == "priceV2":
            for p in m["priceV2"]["price"]:
                if p.get("textStyle") == "PRICE":
                    price = p["text"]
                elif p.get("textStyle") == "ORIGINAL_PRICE":
                    old = p["text"]
        elif m["type"] == "labelListV2":
            txt = [x["text"]["text"] for x in m["labelListV2"]["items"] if x.get("type") == "text"]
            if any("отзыв" in x for x in txt):
                rating, reviews = txt[0], re.sub(r"\D", "", txt[-1])
    delivery = next((x for x in _texts(it.get("multiButton", {})) if DATE_RE.search(x)), "")
    link = it.get("action", {}).get("link", "").split("?")[0]
    return {"sku": it.get("sku"), "title": title, "price": re.sub(r"\D", "", price),
            "old": re.sub(r"\D", "", old), "rating": rating, "reviews": reviews,
            "delivery": delivery, "url": link}


def search(query, price_min=None, price_max=None, sort="score", limit=30):
    if sort not in SORTS:
        raise ValueError(f"sort: одно из {SORTS}")
    qs = {"text": query, "sorting": sort}
    if price_min or price_max:
        qs["currency_price"] = f"{float(price_min or 0):.3f};{float(price_max or 10**8):.3f}"
    url = "/search/?" + urllib.parse.urlencode(qs)
    tab = _tab()
    items, seen = [], set()
    try:
        for _ in range(8):  # ~8 tiles per page
            page = _page(tab, url)
            for grid in _widgets(page, "tileGrid"):
                for it in grid.get("items", []):
                    x = _tile(it)
                    if x["sku"] and x["sku"] not in seen:
                        seen.add(x["sku"])
                        items.append(x)
            nxt = [w.get("nextPage") for w in _widgets(page, "infiniteVirtualPaginator") + _widgets(page, "paginator")]
            nxt = next((n for n in nxt if n), None) or page.get("nextPage")
            if len(items) >= limit or not nxt:
                break
            url = nxt
    finally:
        tab.close()
    rows = [f"{i+1}\t{x['sku']}\t{x['price']}\t{x['old']}\t{x['title'][:110]}\t{x['rating']}\t{x['reviews']}\t{x['delivery']}"
            for i, x in enumerate(items[:limit])]
    head = ("Ozon · https://www.ozon.ru/search/?" + urllib.parse.urlencode(qs) +
            "\nтовар: https://www.ozon.ru/product/<sku>\n#\tsku\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tпривезут")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _html_text(s):
    s = re.sub(r"<br\s*/?>|</p>|</li>", "\n", s or "")
    s = re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").replace("&quot;", '"').replace("&amp;", "&")
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def _seller(tab, page):
    """Shop name and legal info from the 'О магазине' modal. A foreign seller shows a non-Russian
    company there, e.g. 'Shenzhen … Co., Ltd.', and Ozon brings the item from abroad in 2–4 weeks."""
    w = next(iter(_widgets(page, "webCurrentSeller-")), {})
    name = w.get("sellerCell", {}).get("centerBlock", {}).get("title", {}).get("text", "?")
    m = re.search(r'"sellerId":\s*"(\d+)"', json.dumps(w))
    if not m:
        return name, ""
    legal = ""
    info = _page(tab, f"/modal/shop-in-shop-info?seller_id={m.group(1)}")
    for v in info.get("widgetStates", {}).values():
        legal = next((t for t in _texts(json.loads(v)) if "<br>" in t), "")
        if legal:
            break
    return name, legal


def item(sku_or_url, full=False):
    sku = _sku(sku_or_url)
    tab = _tab()
    try:
        page = _page(tab, f"/product/{sku}/")
        # characteristics and description sit on the second screen of the product page
        nxt = next((w.get("nextPage") for w in _widgets(page, "paginator") if w.get("nextPage")),
                   f"/product/{sku}/?layout_container=pdpPage2column&layout_page_index=2")
        page2 = _page(tab, nxt)
        dates = _fetch(tab, f"/api/composer-api.bx/_action/pdpGetButtonTexts?product_id={sku}", "POST", {"pageType": "pdp"})
        shop, legal = _seller(tab, page)
        # «Стало дешевле»: the modal compares today's price with last month's average
        lower = _page(tab, f"/modal/web_pdp_lower_price?product_id={sku}") if _widgets(page, "webPriceDecreasedCompact-") else {}
    finally:
        tab.close()

    title = next(iter(_widgets(page, "webProductHeading-")), {}).get("title", "?")
    price = next(iter(_widgets(page, "webPrice-")), {})
    sale = next(iter(_widgets(page, "webSale-")), {})
    score = next(iter(_widgets(page, "webReviewProductScore-")), {})
    delivery = next((t for t in _texts(dates) if DATE_RE.search(t)), "?")
    def rub(x):
        return int(re.sub(r"\D", "", x or "") or 0)
    cur, orig = rub(price.get("price")), rub(price.get("originalPrice"))
    out = [f"{title}\nhttps://www.ozon.ru/product/{sku}/",
           f"цена: {price.get('cardPrice') or price.get('price', '?')} с картой Ozon, {price.get('price', '?')} без неё"
           + (f", без скидки {price['originalPrice']} (−{round(100 - cur * 100 / orig)}%)" if orig > cur > 0 else "")
           + (f", {price['pricePerUnit']} {price['measurePerUnit']}" if price.get("pricePerUnit") else ""),
           "в наличии: " + ("да" if sale.get("offer", {}).get("isAvailable", price.get("isAvailable")) else "⛔ нет"),
           f"привезут: {delivery}",
           f"рейтинг: {score.get('totalScore', '?')}, отзывов {score.get('reviewsCount', '?')}"]
    if legal:
        company = _html_text(legal).replace("\n", " · ")
        foreign = not re.search(r"[а-яА-ЯёЁ]", legal.split("<br>")[0])
        out.append(f"продавец: {shop} · {company}" + (" · ⚠️ из-за рубежа" if foreign else ""))
    else:
        out.append(f"продавец: {shop} (юрлицо не нашёл)")
    for w in _widgets(lower, "webPriceDecreasedFullView-"):
        parts = [" ".join(t.get("content", "") for t in x.get("textRs") or [] if t.get("type") == "text")
                 + (f" (−{x['iconText']})" if x.get("iconText") else "") for x in w.get("lines", [])]
        out.append("стало дешевле: " + "; ".join(parts) + " — Ozon сравнивает цену без банков-партнёров со средней за прошлый месяц")
    photos = [i.get("src") for g in _widgets(page, "webGallery-") for i in g.get("images", []) if i.get("src")]
    if photos:
        out.append("фото (shop_images): " + " ".join(photos[:10]))
    out.append("отзывы с фото и видео: ozon_reviews")
    chars = []
    for w in _widgets(page2, "webCharacteristics-"):
        for group in w.get("characteristics", []):
            for lst in group.values():
                for c in lst if isinstance(lst, list) else []:
                    if c.get("key") != "Sku":
                        chars.append(f"  {c.get('name')}: {', '.join(v.get('text', '') for v in c.get('values', []))}")
    out.append("характеристики:\n" + ("\n".join(chars) if chars else "  (нет)"))
    desc = _html_text(next(iter(_widgets(page2, "webDescription-")), {}).get("richAnnotation", ""))
    if desc:
        out.append("описание:\n" + (desc if full else desc[:2500]))
    return "\n".join(out)


REVIEW_SORTS = {"useful": "usefulness_desc", "high": "score_desc", "low": "score_asc"}


def _list_reviews(page):
    return next(iter(_widgets(page, "webListReviews-")), {})


def reviews(sku_or_url, sort="useful", with_media=False, page=1, this_variant=False):
    """Ozon's own reviews page: 30 per page. Page N needs the page_key Ozon puts into page 1's links.
    No server-side filter for photos was found (with_media, withMedia, photo params are ignored),
    so with_media filters the page that was fetched."""
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)} (сортировки по дате на Ozon нет: useful — «новые и полезные»)"
    sku = _sku(sku_or_url)
    base = f"/product/{sku}/reviews/?sort={REVIEW_SORTS[sort]}&reviewsVariantMode={1 if this_variant else 2}"
    tab = _tab()
    try:
        first = _page(tab, base)
        lr = _list_reviews(first)
        if page > 1:
            m = re.search(r"page_key=([^&]+)", json.dumps(lr.get("paging") or {}))
            lr = _list_reviews(_page(tab, f"{base}&page={page}&page_key={m.group(1)}")) if m else {}
    finally:
        tab.close()
    score = next(iter(_widgets(first, "webReviewProductScore-")), {})
    total = (lr.get("paging") or {}).get("total") or score.get("reviewsCount") or 0
    stars = " ".join(f"{x.get('title')}: {x.get('value')}" for x in score.get("score") or [])
    head = (f"Ozon · sku {sku}: рейтинг {score.get('totalScore', '?')}, отзывов {score.get('reviewsCount', '?')} · {stars}\n"
            f"{'только этот вариант' if this_variant else 'все варианты товара'}: {total} отзывов, страница {page} из {max(1, -(-total // 30))} (по 30), "
            f"сортировка {sort}{'; только с фото или видео — из этой страницы' if with_media else ''}\n"
            "дата\t★\tполезно +/−\tвариант\tавтор\tтекст\tфото (shop_images), видео")
    products = lr.get("products") or {}
    rows = []
    for r in lr.get("reviews") or []:
        c = r.get("content") or {}
        if with_media and not (c.get("photos") or c.get("videos")):
            continue
        variant = ", ".join(v.get("value", "") for v in (products.get(str(r.get("itemId"))) or {}).get("variants") or [])
        text = " | ".join(x for x in (f"+ {c['positive']}" if c.get("positive") else "", f"− {c['negative']}" if c.get("negative") else "",
                                      c.get("comment") or "") if x)
        media = [ph["url"] for ph in c.get("photos") or [] if ph.get("url")]
        media += [f"видео {v.get('duration', '')}: {v['url']} превью {v.get('previewUrl', '')}" for v in c.get("videos") or [] if v.get("url")]
        u = r.get("usefulness") or {}
        date = time.strftime("%Y-%m-%d", time.localtime(r.get("createdAt") or r.get("publishedAt") or 0))
        rows.append(f"{date}\t{c.get('score', '')}\t+{u.get('useful', 0)}/−{u.get('unuseful', 0)}\t{variant}\t"
                    f"{(r.get('author') or {}).get('firstName', '')}\t{' '.join(text.split())}\t{' '.join(media)}")
    return head + "\n" + ("\n".join(rows) if rows else "(отзывов нет)")


def _sku(sku_or_url):
    s = str(sku_or_url).strip()
    if s.isdigit():
        return int(s)
    m = re.search(r"(\d{5,})/?(?:\?|$)", s) or re.search(r"-(\d{5,})", s)
    if not m:
        raise ValueError(f"не нашёл sku в {s!r}")
    return int(m.group(1))


def add_to_cart(sku_or_url, quantity=1):
    sku = _sku(sku_or_url)
    tab = _tab()
    try:
        r = _fetch(tab, "/api/composer-api.bx/_action/addToCart", "POST", [{"id": sku, "quantity": int(quantity)}])
    finally:
        tab.close()
    if not r.get("success"):
        return f"Ozon не добавил {sku}: {json.dumps(r, ensure_ascii=False)[:300]}"
    got = {i["id"]: i["qty"] for i in r.get("cart", {}).get("cartItems", [])}
    return f"добавлено: sku {sku}, в корзине этого товара {got.get(sku, '?')} шт."


def _cart_sku(it):
    try:
        post = it["controls"]["deleteButton"]["common"]["action"]["params"]["postBody"]
        return json.loads(json.loads(post)["params"])["items"][0]
    except (KeyError, ValueError, IndexError):
        return ""


def _cart_text(page):
    if _widgets(page, "emptyCart"):
        return "корзина Ozon пуста"
    rows = []
    for split in _widgets(page, "cartSplit"):
        group = _texts(split.get("header", {}))
        for it in split.get("cartItems", []):
            p = it.get("product", {})
            title = next((t for t in _texts(p.get("titleColumn", [])) if len(t) > 15), "")
            price = next((t for t in _texts(p.get("priceColumn", [])) if "₽" in t), "")
            qty = it.get("controls", {}).get("quantity", {}).get("current", "")
            sku = _cart_sku(it)
            rows.append(f"{sku}\t{qty}\t{re.sub(r'\s', ' ', price)}\t{title[:110]}\t{group[0] if group else ''}")
    total = next(iter(_widgets(page, "total")), {}).get("summary", {})
    foot = total.get("footer", {})
    head = total.get("header", {}).get("info", "")
    total_text = foot.get("price") or "не посчитан: ни один товар не отмечен к оформлению"
    return (f"корзина Ozon: {head}, итого {total_text}\nsku\tшт\tцена\tназвание\tгруппа\n" + "\n".join(rows))


def cart():
    tab = _tab()
    try:
        return _cart_text(_page(tab, "/cart"))
    finally:
        tab.close()


def remove_from_cart(sku_or_url):
    sku = str(_sku(sku_or_url))
    body = {"name": "deleteItems", "params": json.dumps({"items": [sku]})}
    tab = _tab()
    try:
        return "удалено. " + _cart_text(_fetch(tab, API + "%2Fcart", "POST", body))
    finally:
        tab.close()
