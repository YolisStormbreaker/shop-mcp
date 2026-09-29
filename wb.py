"""Wildberries: search and product card, read-only.

WB signs its API calls with a bearer token and device headers, so the site's own page makes
the request and we take the JSON it got (capture.py).
Region (dest) and prices are the user's, as the page sees them.
"""
import datetime
import re
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


def item(id_or_url):
    m = re.search(r"catalog/(\d+)", str(id_or_url)) or re.fullmatch(r"\s*(\d+)\s*", str(id_or_url))
    if not m:
        return "нужен артикул WB или ссылка вида https://www.wildberries.ru/catalog/<id>/detail.aspx"
    nm = m.group(1)
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
