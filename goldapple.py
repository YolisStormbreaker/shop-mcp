"""Gold Apple (goldapple.ru): search and product card, read-only.

The site posts the user's city and delivery zones with every catalog call, so its own page makes
the request and we take the JSON it got (capture.py). Prices and stock are for the user's city.
"""
import html
import re
import urllib.parse

from capture import capture
from cdp import tab_for
from shoplog import log

SORTS = ("relevance", "priceAsc", "priceDesc", "discountAmount", "byRating", "byNewest")  # the site's own ids
PAGE = 24
BLOCKED = "⚠️ Золотое яблоко не отдало данные (проверка на бота?): shop-chrome show, открыть сайт, повторить."


def _rub(price, key):
    return ((price or {}).get(key) or {}).get("amount")


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def search(query, price_min=None, price_max=None, sort="relevance", page=1, limit=PAGE):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    qs = {"q": query}
    if sort != "relevance":
        qs["sort"] = sort
    if price_min or price_max:
        qs["calculatedprices"] = f"{int(price_min or 0)}-{int(price_max or 10_000_000)}"  # only this form applies
    if page > 1:
        qs["p"] = page
    url = "https://goldapple.ru/catalogsearch/result?" + urllib.parse.urlencode(qs)
    tab = tab_for("goldapple.ru")
    try:
        d = capture(tab, "goldapple", url, {"s": ["/front/api/catalog/search-products"]}).get("s")
    finally:
        tab.close()
    if d is None:
        log.warning("goldapple search %s: no search-products response", url)
        return BLOCKED
    data = d.get("data") or {}
    rows = []
    for i, p in enumerate((data.get("products") or [])[:limit]):
        actual, old = _rub(p.get("price"), "actual"), _rub(p.get("price"), "old")
        units = (p.get("attributes") or {}).get("units") or {}
        volume = f"{units.get('currentUnitValue')} {units.get('name')}" if units.get("currentUnitValue") else ""
        if units.get("count", 0) > 1:
            volume += f" (вариантов: {units['count']})"
        rv = p.get("reviews") or {}
        rows.append(f"{i+1}\t{p.get('itemId')}\t{actual}\t{old if old and old != actual else ''}\t{p.get('brand', '')}\t"
                    f"{p.get('name', '')}\t{p.get('productType', '')}\t{volume}\t{rv.get('rating') or ''}\t"
                    f"{rv.get('reviewsCount') or ''}\t{'' if p.get('inStock') else 'нет в наличии'}\t{p.get('url', '')}")
    count = data.get("count") or len(rows)
    found = f"{count}+" if count >= 2000 else str(count)  # the site caps the count at 2000
    head = (f"Золотое яблоко · {found} найдено · страница {page} (по {PAGE}) · {url}\n"
            "ссылки относительно https://goldapple.ru; цены и наличие — для города из профиля\n"
            "#\tартикул\tцена ₽\tбез скидки\tбренд\tназвание\tтип\tобъём\tрейтинг\tотзывов\tналичие\tссылка")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def item(url):
    if url.startswith("/"):
        url = "https://goldapple.ru" + url
    m = re.search(r"goldapple\.ru/(\d+)-", url)
    if not m:
        return "нужна ссылка на товар из goldapple_search: https://goldapple.ru/<артикул>-<название>"
    tab = tab_for("goldapple.ru")
    try:
        d = capture(tab, "goldapple", url, {"c": ["/front/api/catalog/product-card/base/v3", m.group(1)]}).get("c")
    finally:
        tab.close()
    if d is None:
        log.warning("goldapple item %s: no product-card response", url)
        return BLOCKED
    x = d.get("data") or d
    attrs = x.get("attributes") or {}
    unit = (attrs.get("units") or {}).get("unit", "")
    colors = {o["value"]: o["text"] for o in (attrs.get("colors") or {}).get("options") or []}
    variants = []
    for v in x.get("variants") or []:
        av = v.get("attributesValue") or {}
        label = " ".join(s for s in (f"{av['units']} {unit}".strip() if av.get("units") else "", colors.get(av.get("colors"), "")) if s)
        actual, old = _rub(v.get("price"), "actual"), _rub(v.get("price"), "old")
        variants.append(f"{label or v.get('itemId')} — {actual} ₽" + (f" (было {old})" if old and old != actual else "")
                        + ("" if v.get("inStock") else ", нет в наличии"))
    lines = [f"{x.get('brand', '')} {x.get('name', '')} ({x.get('productType', '')})", url.split("?")[0],
             f"артикул: {x.get('itemId')}", "варианты: " + "; ".join(variants)]
    text = "\n".join(f"{s.get('text')}: {_text(s.get('content'))}" for s in x.get("productDescription") or []
                     if s.get("type") != "Brand" and s.get("content"))
    lines.append("\n" + text[:2500])
    return "\n".join(lines)
