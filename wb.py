"""Wildberries: search, product card, reviews and cart (view, add, remove). Never checks out.

WB signs its API calls with a bearer token and device headers, so the site's own page makes
the request and we take the JSON it got (capture.py).
Region (dest) and prices are the user's, as the page sees them.
"""
import datetime
import gzip
import json
import re
import time
import urllib.parse
import urllib.request

from capture import capture
from cdp import tab_for
from shoplog import log

SORTS = ("popular", "rate", "priceup", "pricedown", "newly", "benefit")
MONTHS = "янв фев мар апр мая июн июл авг сен окт ноя дек".split()
NEED_ID = "нужен артикул WB или ссылка вида https://www.wildberries.ru/catalog/<id>/detail.aspx"
BLOCKED = ("⚠️ Wildberries не отдал данные: вероятно, проверка на бота. "
           "Открыть браузер: shop-chrome show, пройти проверку, повторить.")


def _eta(p):
    """time1 + time2 are hours from now to delivery at the user's address."""
    hours = (p.get("time1") or 0) + (p.get("time2") or 0)
    if not hours:
        return ""
    d = datetime.date.today() + datetime.timedelta(hours=hours)
    return f"≈{d.day} {MONTHS[d.month - 1]}"


def _price(p):
    """(current, before discount) in roubles from the first size."""
    pr = ((p.get("sizes") or [{}])[0]).get("price") or {}
    return pr.get("product", 0) // 100, pr.get("basic", 0) // 100


def search(query, price_min=None, price_max=None, sort="popular", page=1, limit=30):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    url = _search_url(query, price_min, price_max, sort)
    tab = tab_for("wildberries.ru")
    try:
        d = capture(tab, "wb", url, {"s": ["/exactmatch/", "resultset=catalog"]}, rewrite=_pager(page)).get("s")
    finally:
        tab.close()
    if d is None:
        log.warning("wb search %s: no catalog response", url)
        return BLOCKED
    return _search_text(d, url, sort, page, limit)


def _search_url(query, price_min, price_max, sort):
    qs = {"search": query, "sort": sort}
    if price_min or price_max:
        qs["priceU"] = f"{int(price_min or 0) * 100};{int(price_max or 10_000_000) * 100}"
    return "https://www.wildberries.ru/catalog/0/search.aspx?" + urllib.parse.urlencode(qs)


def _pager(page):
    """The site loads page N (100 items each) only while the list is scrolled, which a background tab
    never does; a page=N link still asks for page 1. So its own page-1 request is sent as page N."""
    return ("*/exactmatch/*resultset=catalog*", lambda u: _paged(u, page)) if page > 1 else None


def _paged(u, page):
    return re.sub(r"([?&])page=\d+", rf"\g<1>page={page}", u) if re.search(r"[?&]page=", u) else f"{u}&page={page}"


def _search_text(d, url, sort, page, limit):
    products = d.get("products") or []
    if sort in ("priceup", "pricedown"):
        # WB lifts promoted items to the top even when sorting by price (seen 2026-09-30); order them ourselves.
        products.sort(key=lambda p: _price(p)[0], reverse=sort == "pricedown")
    rows = [_row(i, p) for i, p in enumerate(products[:limit], 1)]
    total = d.get("total") or len(rows)
    head = (f"Wildberries · {total} найдено · страница {page} из {max(1, -(-total // 100))} (по 100) · {url}\n"
            "товар: https://www.wildberries.ru/catalog/<id>/detail.aspx; «привезут» — оценка по сроку доставки на адрес из профиля\n"
            "цена без скидки WB Кошелька: сайт показывает цену с ней, она на несколько процентов ниже\n"
            "#\tid\tцена ₽\tбез скидки\tназвание\tбренд\tрейтинг\tотзывов\tпродавец\tпривезут")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _row(i, p):
    price, basic = _price(p)
    stock = "" if p.get("totalQuantity") else "нет в наличии"
    return (f"{i}\t{p['id']}\t{price}\t{basic}\t{p.get('name', '')}\t{p.get('brand', '')}\t"
            f"{p.get('reviewRating') or ''}\t{p.get('feedbacks') or ''}\t{p.get('supplier', '')}\t{stock or _eta(p)}")


def _nm(id_or_url):
    m = re.search(r"catalog/(\d+)", str(id_or_url)) or re.fullmatch(r"\s*(\d+)\s*", str(id_or_url))
    return m.group(1) if m else None


def _get(url):
    """Public WB JSON (CDN, feedbacks): no token needed. Feedbacks come gzipped even unasked."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Chrome/154", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=20) as r:
        b = r.read()
    return json.loads(gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b)


_imt: dict[str, int] = {}   # nm → imt (the card that groups colors; reviews are per imt)


def _open(nm, patterns):
    """(captured JSON, product from detail, CDN folder of the product) from its page.
    The CDN host comes from a route map the page fetches at runtime (basket-NN from the bundle's
    table gave 404 on 2026-10-08), so it is taken from a photo or card.json the page loaded."""
    tab = tab_for("wildberries.ru")
    try:
        d = capture(tab, "wb", f"https://www.wildberries.ru/catalog/{nm}/detail.aspx",
                    {"detail": ["/cards/v4/detail", f"nm={nm}"], **patterns}, optional=tuple(patterns))
        base = tab.js("(performance.getEntriesByType('resource').map(e => e.name)"
                      f".find(n => /\\/vol\\d+\\/part\\d+\\/{nm}\\//.test(n)) || '').split('/{nm}/')[0]")
    finally:
        tab.close()
    p = _product(d, nm)
    if p and p.get("root"):
        _imt[nm] = p["root"]
    return d, p, f"{base}/{nm}" if base else ""


def _product(d, nm):
    """Product nm from the detail answer the page got; None if it is not there."""
    return next((x for x in (d.get("detail") or {}).get("products", []) if str(x.get("id")) == nm), None)


def _day(ts):
    d = datetime.date.fromtimestamp(ts)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year % 100:02d}"


def _history(base):
    """Weekly price, kopecks; 404 for some products."""
    try:
        h = [(x["dt"], x["price"]["RUB"] // 100) for x in _get(f"{base}/info/price-history.json")]
    except Exception:
        return ""
    if not h:
        return ""
    lo, hi = min(h, key=lambda x: x[1]), max(h, key=lambda x: x[1])
    return (f"история цены, ₽ по неделям: мин {lo[1]} ({_day(lo[0])}), макс {hi[1]} ({_day(hi[0])}); последние: "
            + ", ".join(f"{_day(t)} {v}" for t, v in h[-8:]))


def item(id_or_url, full=False):
    nm = _nm(id_or_url)
    if not nm:
        return NEED_ID
    d, p, base = _open(nm, {"seller": ["/api/v1/suppliers/"]})
    if not p:
        log.warning("wb item %s: no detail response, got %s", nm, list(d))
        return BLOCKED
    card, hist = (_card(nm, base), _history(base)) if base else ({}, "")
    return "\n".join([_head(p), f"https://www.wildberries.ru/catalog/{nm}/detail.aspx", *_stock(p), _seller(p, d.get("seller") or {}),
                      *_cdn(base, p, hist), "отзывы: wb_reviews", *_about(card, full)])


def _card(nm, base):
    try:
        return _get(f"{base}/info/ru/card.json")   # the page loads it not for every product
    except Exception as e:
        log.warning("wb item %s: card.json: %s", nm, e)
        return {}


def _head(p):
    price, basic = _price(p)
    if not price:
        return f"{p.get('name', '')} — цены нет: товара нет в наличии (последние цены — в истории ниже)"
    return (f"{p.get('name', '')} — {price} ₽ без WB Кошелька (с ним на сайте на несколько % ниже)"
            + (f", до скидок {basic} ₽ (−{round(100 - price * 100 / basic)}%)" if basic > price else ""))


def _stock(p):
    stock = f"в наличии: {p['totalQuantity']} шт" if p.get("totalQuantity") else "нет в наличии"
    lines = [f"бренд: {p.get('brand') or '—'} · рейтинг {p.get('reviewRating') or '—'} ({p.get('feedbacks', 0)} отзывов) · {stock}"]
    if p.get("totalQuantity") and _eta(p):
        lines.append(f"привезут {_eta(p)} (оценка по сроку доставки на адрес из профиля)")
    return lines


def _seller(p, seller):
    s = f"продавец: {p.get('supplier', '')}, рейтинг {seller.get('valuation') or p.get('supplierRating') or '—'}"
    if seller.get("saleItemQuantity"):
        s += f", продаж {seller['saleItemQuantity']}"
    if seller.get("registrationDate"):
        s += f", на WB с {seller['registrationDate'][:4]}"
    return s


def _cdn(base, p, hist):
    """Price history and photos: known only with the product's CDN folder."""
    if not base:
        return []
    photos = " ".join(f"{base}/images/big/{i}.webp" for i in range(1, min(p.get("pics") or 0, 10) + 1))
    return ([hist] if hist else []) + ["фото (shop_images): " + photos]


def _about(card, full):
    specs = [f"{o['name']}: {o['value']}" for g in card.get("grouped_options") or [] for o in g.get("options", [])]
    desc = card.get("description") or ""
    return (["характеристики: " + "; ".join(specs)] if specs else []) + ["\n" + (desc if full else desc[:2500])]


def _votes(f):
    """(pluses, minuses): how many found the review useful and not"""
    v = f.get("votes") or {}
    return v.get("pluses", 0), v.get("minuses", 0)


REVIEW_SORTS = {"useful": lambda f: (_votes(f)[0] - _votes(f)[1], f.get("createdDate", "")),
                "new": lambda f: f.get("createdDate", ""),
                "high": lambda f: (f.get("productValuation", 0), f.get("createdDate", "")),
                "low": lambda f: (-f.get("productValuation", 0), f.get("createdDate", ""))}


def _media(f):
    """Photo and video URLs of a review, as the site builds them (volFeedbackPhotoUuidHost and
    volFeedbackVideoHost in its bundle): key "5/<uuid>" → feedback-05.wbbasket.ru/<uuid>/fs.webp.
    Video: preview.webp and an HLS index.m3u8 (there is no .mp4 for these)."""
    out = []
    for ph in f.get("photos") or []:
        if "/" in str(ph.get("key") or ""):
            n, u = ph["key"].split("/", 1)
            out.append(f"https://feedback-{int(n):02d}.wbbasket.ru/{u}/fs.webp")
    v = f.get("video") or {}
    if "/" in str(v.get("id") or ""):
        n, u = v["id"].split("/", 1)
        host = f"https://videofeedback{int(n):02d}.wbbasket.ru/{u}"
        out.append(f"видео {v.get('durationSec', '?')} с: {host}/index.m3u8 превью {host}/preview.webp")
    return out


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    nm = _nm(id_or_url)
    if not nm:
        return NEED_ID
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    if nm not in _imt:
        _open(nm, {})      # imt (root) is only in the token-signed detail the page itself requests
    if not _imt.get(nm):
        return BLOCKED
    imt = _imt[nm]
    host = _get(f"https://feedback-bt.wildberries.ru/feedback/api/v2/host?imt={imt}")[0]
    return _reviews_text(nm, imt, _get(f"{host}/feedbacks/v2/{imt}"), sort, with_media, page, limit)


def _reviews_text(nm, imt, d, sort, with_media, page, limit):
    fb = sorted((f for f in d.get("feedbacks") or [] if not with_media or f.get("photos") or f.get("video")),
                key=REVIEW_SORTS[sort], reverse=True)
    rows = [_review(f) for f in fb[(page - 1) * limit: page * limit]]
    return (_reviews_head(nm, imt, d) + "\n"
            f"WB отдаёт до ~1000 отзывов с текстом, сортировка и страницы — по ним: {len(fb)}{' с фото или видео' if with_media else ''}, "
            f"страница {page} из {max(1, -(-len(fb) // limit))} по {limit}, сортировка {sort}. Отзывы на все цвета и размеры карточки.\n"
            "дата\t★\tполезно +/−\tцвет, размер\tавтор\tтекст\tфото (shop_images), видео\n"
            + ("\n".join(rows) if rows else "(отзывов нет)"))


def _reviews_head(nm, imt, d):
    dist = d.get("valuationDistributionPercent") or {}
    return (f"Wildberries · артикул {nm} (карточка {imt}): рейтинг {d.get('valuation') or '—'}, отзывов {d.get('feedbackCount', 0)} "
            f"(с текстом {d.get('feedbackCountWithText', 0)}, с фото {d.get('feedbackCountWithPhoto', 0)}, с видео {d.get('feedbackCountWithVideo', 0)}) · "
            + " ".join(f"{k}★ {dist[k]}%" for k in sorted(dist, reverse=True)))


def _review(f):
    pluses, minuses = _votes(f)
    variant = ", ".join(x for x in (f.get("color"), f.get("size")) if x and x != "0")
    return (f"{(f.get('createdDate') or '')[:10]}\t{f.get('productValuation')}\t+{pluses}/−{minuses}\t"
            f"{variant}\t{(f.get('wbUserDetails') or {}).get('name', '')}\t{' '.join(_review_text(f).split())}\t{' '.join(_media(f))}")


def _review_text(f):
    """+ pros | − cons | text | the seller's answer"""
    return " | ".join(x for x in (f"+ {f['pros']}" if f.get("pros") else "", f"− {f['cons']}" if f.get("cons") else "",
                                  f.get("text") or "", f"ответ продавца: {f['answer'].get('text', '')[:300]}" if f.get("answer") else "") if x)


CART = "https://www.wildberries.ru/lk/basket"
SYNC = "*cart-storage-api/api/basket/sync*"


def _once(fn):
    """Rewrite only the first matching request: a page may sync more than once per load."""
    done = []

    def wrap(u):
        if done:
            return u
        done.append(1)
        return fn(u)
    return wrap


def _cart(tab, ops=None):
    """Cart items as the server has them, after sending ops first; None if WB answered nothing.

    WB keeps the cart in the browser and syncs operations (op_type 1 add, 3 remove) to its server
    with a signed request. Our operations ride in the body of the page's own sync on load; a second
    load with ts=0 makes the page pull the whole server cart, so the listing includes our change.
    """
    if ops and not _synced(tab, ops):
        return None
    ts0 = _once(lambda u: re.sub(r"([?&])ts=\d+", r"\g<1>ts=0", u))
    d = capture(tab, "wb", CART, {"cart": ["basket/data_v2"]}, rewrite=(SYNC, ts0)).get("cart")
    return None if d is None else _basket_items(d)


def _synced(tab, ops):
    """Send ops in the body of the page's own sync; whether WB accepted them (state 0)."""
    body = json.dumps(ops)
    r = capture(tab, "wb", CART, {"sync": ["basket/sync"]}, rewrite=(SYNC, _once(lambda u: (u, body)))).get("sync")
    if r and r.get("state") == 0:
        return True
    log.warning("wb cart sync %s: %s", ops, r)
    return False


def _basket_items(d):
    return (((d.get("value") or {}).get("data") or {}).get("basket") or {}).get("basketItems") or []


def _cart_text(items):
    if not items:
        return "корзина Wildberries пуста"
    rows = [f"{i.get('cod1S')}\t{i.get('id')}\t{i.get('quantity')}\t{i.get('priceWithCouponAndSpp') or i.get('price')}\t"
            f"{'✓' if i.get('includeInOrder') else ''}\t{i.get('brandName', '')}\t{i.get('goodsName', '')}\t"
            f"{'' if str(i.get('sizeName')) in ('', '0') else i.get('sizeName')}\t{'' if i.get('canBeOrdered', True) else 'нельзя заказать'}"
            for i in items]
    return ("корзина Wildberries (✓ — выбрано к оформлению; цена за штуку без WB Кошелька)\n"
            "артикул\tchrt\tшт\tцена ₽\t✓\tбренд\tназвание\tразмер\tзаметки\n" + "\n".join(rows))


def cart():
    tab = tab_for("wildberries.ru")
    try:
        items = _cart(tab)
    finally:
        tab.close()
    return BLOCKED if items is None else _cart_text(items)


def add_to_cart(id_or_url, size=None, quantity=1):
    nm = _nm(id_or_url)
    if not nm:
        return "нужен артикул WB или ссылка на товар"
    tab = tab_for("wildberries.ru")
    try:
        p = _product(capture(tab, "wb", f"https://www.wildberries.ru/catalog/{nm}/detail.aspx",
                             {"detail": ["/cards/v4/detail", f"nm={nm}"]}), nm)
        if not p:
            return BLOCKED
        s, why = _size(p.get("sizes") or [], size)
        if why:
            return why
        chrt = s["optionId"]
        items = _cart(tab)
        if items is None:
            return BLOCKED
        if _has(items, chrt):
            return "уже в корзине, ничего не менял\n" + _cart_text(items)
        items = _cart(tab, [_add_op(nm, chrt, quantity)])
    finally:
        tab.close()
    if items is None:
        return BLOCKED
    return (f"{'добавлено' if _has(items, chrt) else '⚠️ Wildberries не подтвердил добавление'}: {p.get('name', '')}, {quantity} шт\n"
            + _cart_text(items))


def _size(sizes, size):
    """(the size to add, None) or (None, why not): with no size asked for, the only one; else the one of that name or original name."""
    if not sizes:
        return None, "у товара нет размеров, которые можно заказать: в корзину не положить"
    names = ", ".join(str(x.get("origName") or x.get("name")) for x in sizes)
    if size is None:
        return (None, "у товара несколько размеров, укажи size: " + names) if len(sizes) > 1 else (sizes[0], None)
    want = str(size).strip().lower()
    s = next((x for x in sizes if want in (str(x.get("name")).lower(), str(x.get("origName")).lower())), None)
    return (s, None) if s else (None, f"нет размера «{size}»; есть: " + names)


def _has(items, chrt):
    return any(i.get("id") == chrt for i in items)


def _add_op(nm, chrt, quantity):
    """The sync operation that puts quantity of size chrt of product nm in the cart (op_type 1)."""
    return {"chrt_id": chrt, "quantity": int(quantity), "cod_1s": int(nm), "client_ts": int(time.time()),
            "op_type": 1, "target_url": "", "meta_json": None, "analytics_json": None}


# Removing is done the way the site does it: drop the line from the browser's cart and queue a
# remove operation; the page sends the queue with its own signed sync on the next load. Sending
# op_type 3 ourselves deletes it on the server only, and the page keeps showing the stale line.
REMOVE_JS = """((chrt, qty) => {
  const b = Object.keys(localStorage).find(k => k.startsWith('wb_basket_'));
  const q = Object.keys(localStorage).find(k => k.startsWith('wb___basketStorage_'));
  if (!b || !q) return false;
  const basket = JSON.parse(localStorage.getItem(b)), queue = JSON.parse(localStorage.getItem(q));
  basket.basketItems = (basket.basketItems || []).filter(i => i.id !== chrt);
  basket.totalQuantity = basket.basketItems.reduce((n, i) => n + (i.quantity || 0), 0);
  queue.operations = (queue.operations || []).concat([{chrt_id: chrt, quantity: qty, client_ts: Math.floor(Date.now() / 1000), op_type: 3}]);
  localStorage.setItem(b, JSON.stringify(basket));
  localStorage.setItem(q, JSON.stringify(queue));
  return true;
})"""


def remove_from_cart(id_or_url_or_chrt):
    key = _nm(id_or_url_or_chrt)
    if not key:
        return "нужен артикул WB, chrt из wb_cart или ссылка на товар"
    tab = tab_for("wildberries.ru")
    try:
        items = _cart(tab)
        if items is None:
            return BLOCKED
        it, why = _line(items, key)
        if why:
            return why
        if not tab.js(f"{REMOVE_JS}({int(it['id'])}, {int(it['quantity'])})"):
            return "⚠️ не нашёл корзину Wildberries в браузере, ничего не удалил"
        items = _cart(tab)  # the page syncs the queued removal on this load
    finally:
        tab.close()
    if items is None:
        return BLOCKED
    return (f"{'⚠️ Wildberries не подтвердил удаление' if _has(items, it['id']) else 'удалено'}: {it.get('goodsName', '')}\n"
            + _cart_text(items))


def _line(items, key):
    """(the one cart line of article or chrt key, None) or (None, why not)."""
    hits = [i for i in items if key in (str(i.get("cod1S")), str(i.get("id")))]
    if not hits:
        return None, "такого товара в корзине нет\n" + _cart_text(items)
    if len(hits) > 1:
        return None, "в корзине несколько размеров этого товара, укажи chrt\n" + _cart_text(hits)
    return hits[0], None
