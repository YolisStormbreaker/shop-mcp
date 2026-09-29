"""Wildberries: search, product card and cart (view, add, remove). Never checks out.

WB signs its API calls with a bearer token and device headers, so the site's own page makes
the request and we take the JSON it got (capture.py).
Region (dest) and prices are the user's, as the page sees them.
"""
import datetime
import json
import re
import time
import urllib.parse

from capture import capture
from cdp import tab_for
from shoplog import log

SORTS = ("popular", "rate", "priceup", "pricedown", "newly", "benefit")
MONTHS = "янв фев мар апр мая июн июл авг сен окт ноя дек".split()
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
    qs = {"search": query, "sort": sort}
    if price_min or price_max:
        qs["priceU"] = f"{int(price_min or 0) * 100};{int(price_max or 10_000_000) * 100}"
    url = "https://www.wildberries.ru/catalog/0/search.aspx?" + urllib.parse.urlencode(qs)
    # The site loads page N (100 items each) only while the list is scrolled, which a background tab
    # never does; a page=N link still asks for page 1. So its own page-1 request is sent as page N.
    rewrite = None
    if page > 1:
        def rewrite_url(u):
            return re.sub(r"([?&])page=\d+", rf"\g<1>page={page}", u) if re.search(r"[?&]page=", u) else f"{u}&page={page}"
        rewrite = ("*__internal/search/exactmatch*resultset=catalog*", rewrite_url)
    tab = tab_for("wildberries.ru")
    try:
        d = capture(tab, "wb", url, {"s": ["/exactmatch/", "resultset=catalog"]}, rewrite=rewrite).get("s")
    finally:
        tab.close()
    if d is None:
        log.warning("wb search %s: no catalog response", url)
        return BLOCKED
    products = d.get("products") or []
    if sort in ("priceup", "pricedown"):
        # WB lifts promoted items to the top even when sorting by price (seen 2026-09-30); order them ourselves.
        products.sort(key=lambda p: _price(p)[0], reverse=sort == "pricedown")
    rows = []
    for i, p in enumerate(products[:limit]):
        price, basic = _price(p)
        stock = "" if p.get("totalQuantity") else "нет в наличии"
        rows.append(f"{i+1}\t{p['id']}\t{price}\t{basic}\t{p.get('name', '')}\t{p.get('brand', '')}\t"
                    f"{p.get('reviewRating') or ''}\t{p.get('feedbacks') or ''}\t{p.get('supplier', '')}\t{stock or _eta(p)}")
    total = d.get("total") or len(rows)
    head = (f"Wildberries · {total} найдено · страница {page} из {max(1, -(-total // 100))} (по 100) · {url}\n"
            "товар: https://www.wildberries.ru/catalog/<id>/detail.aspx; «привезут» — оценка по сроку доставки на адрес из профиля\n"
            "цена без скидки WB Кошелька: сайт показывает цену с ней, она на несколько процентов ниже\n"
            "#\tid\tцена ₽\tбез скидки\tназвание\tбренд\tрейтинг\tотзывов\tпродавец\tпривезут")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _nm(id_or_url):
    m = re.search(r"catalog/(\d+)", str(id_or_url)) or re.fullmatch(r"\s*(\d+)\s*", str(id_or_url))
    return m.group(1) if m else None


def item(id_or_url):
    nm = _nm(id_or_url)
    if not nm:
        return "нужен артикул WB или ссылка вида https://www.wildberries.ru/catalog/<id>/detail.aspx"
    url = f"https://www.wildberries.ru/catalog/{nm}/detail.aspx"
    tab = tab_for("wildberries.ru")
    try:
        d = capture(tab, "wb", url, {"detail": ["/cards/v4/detail", f"nm={nm}"],
                                "card": [f"/{nm}/info/ru/card.json"],
                                "seller": ["/api/v1/suppliers/"]})
    finally:
        tab.close()
    p = next((x for x in (d.get("detail") or {}).get("products", []) if str(x.get("id")) == nm), None)
    if not p:
        log.warning("wb item %s: no detail response, got %s", nm, list(d))
        return BLOCKED
    card, seller = d.get("card") or {}, d.get("seller") or {}
    price, basic = _price(p)
    lines = [f"{p.get('name', '')} — {price} ₽ без WB Кошелька (с ним на сайте на несколько % ниже)"
             + (f", до скидок {basic} ₽" if basic > price else ""), url]
    stock = f"в наличии: {p['totalQuantity']} шт" if p.get("totalQuantity") else "нет в наличии"
    lines.append(f"бренд: {p.get('brand') or '—'} · рейтинг {p.get('reviewRating') or '—'} ({p.get('feedbacks', 0)} отзывов) · {stock}")
    if p.get("totalQuantity") and _eta(p):
        lines.append(f"привезут {_eta(p)} (оценка по сроку доставки)")
    s = f"продавец: {p.get('supplier', '')}, рейтинг {seller.get('valuation') or p.get('supplierRating') or '—'}"
    if seller.get("saleItemQuantity"):
        s += f", продаж {seller['saleItemQuantity']}"
    if seller.get("registrationDate"):
        s += f", на WB с {seller['registrationDate'][:4]}"
    lines.append(s)
    specs = [f"{o['name']}: {o['value']}" for g in card.get("grouped_options") or [] for o in g.get("options", [])]
    if specs:
        lines.append("характеристики: " + "; ".join(specs))
    lines.append("\n" + (card.get("description") or "")[:2500])
    return "\n".join(lines)


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
    if ops:
        body = json.dumps(ops)
        r = capture(tab, "wb", CART, {"sync": ["basket/sync"]}, rewrite=(SYNC, _once(lambda u: (u, body)))).get("sync")
        if not r or r.get("state") != 0:
            log.warning("wb cart sync %s: %s", ops, r)
            return None
    ts0 = _once(lambda u: re.sub(r"([?&])ts=\d+", r"\g<1>ts=0", u))
    d = capture(tab, "wb", CART, {"cart": ["basket/data_v2"]}, rewrite=(SYNC, ts0)).get("cart")
    if d is None:
        return None
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
        d = capture(tab, "wb", f"https://www.wildberries.ru/catalog/{nm}/detail.aspx", {"detail": ["/cards/v4/detail", f"nm={nm}"]})
        p = next((x for x in (d.get("detail") or {}).get("products", []) if str(x.get("id")) == nm), None)
        if not p:
            return BLOCKED
        sizes = p.get("sizes") or []
        names = [str(x.get("origName") or x.get("name")) for x in sizes]
        if size is None and len(sizes) > 1:
            return "у товара несколько размеров, укажи size: " + ", ".join(names)
        s = sizes[0] if size is None else next((x for x in sizes if str(size).strip().lower() in
                                                (str(x.get("name")).lower(), str(x.get("origName")).lower())), None)
        if not s:
            return f"нет размера «{size}»; есть: " + ", ".join(names)
        chrt = s["optionId"]
        items = _cart(tab)
        if items is None:
            return BLOCKED
        if any(i.get("id") == chrt for i in items):
            return "уже в корзине, ничего не менял\n" + _cart_text(items)
        items = _cart(tab, [{"chrt_id": chrt, "quantity": int(quantity), "cod_1s": int(nm), "client_ts": int(time.time()),
                             "op_type": 1, "target_url": "", "meta_json": None, "analytics_json": None}])
    finally:
        tab.close()
    if items is None:
        return BLOCKED
    ok = any(i.get("id") == chrt for i in items)
    return (f"{'добавлено' if ok else '⚠️ Wildberries не подтвердил добавление'}: {p.get('name', '')}, {quantity} шт\n"
            + _cart_text(items))


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
        hits = [i for i in items if key in (str(i.get("cod1S")), str(i.get("id")))]
        if not hits:
            return "такого товара в корзине нет\n" + _cart_text(items)
        if len(hits) > 1:
            return "в корзине несколько размеров этого товара, укажи chrt\n" + _cart_text(hits)
        it = hits[0]
        if not tab.js(f"{REMOVE_JS}({int(it['id'])}, {int(it['quantity'])})"):
            return "⚠️ не нашёл корзину Wildberries в браузере, ничего не удалил"
        items = _cart(tab)  # the page syncs the queued removal on this load
    finally:
        tab.close()
    if items is None:
        return BLOCKED
    gone = not any(i.get("id") == it["id"] for i in items)
    return (f"{'удалено' if gone else '⚠️ Wildberries не подтвердил удаление'}: {it.get('goodsName', '')}\n"
            + _cart_text(items))
