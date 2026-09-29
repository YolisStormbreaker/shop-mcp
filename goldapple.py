"""Gold Apple (goldapple.ru): search, product card and cart (view, add, remove). Never checks out.

The site posts the user's city and delivery zones with every catalog call, so its own page makes
the request and we take the JSON it got (capture.py). Prices and stock are for the user's city.
"""
import html
import json
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
                        + ("" if v.get("inStock") else ", нет в наличии") + f", артикул {v.get('itemId')}")
    lines = [f"{x.get('brand', '')} {x.get('name', '')} ({x.get('productType', '')})", url.split("?")[0],
             f"артикул: {x.get('itemId')}", "варианты: " + "; ".join(variants)]
    text = "\n".join(f"{s.get('text')}: {_text(s.get('content'))}" for s in x.get("productDescription") or []
                     if s.get("type") != "Brand" and s.get("content"))
    lines.append("\n" + text[:2500])
    return "\n".join(lines)


# The cart is a plain same-origin API with the session cookie (names from the site's own code:
# getState, addItemsBySku, deleteItems), so it works from a background tab.
STATE = "/front/api/cart/v3/state?locale=ru&includeDeliveryThreshold=false"


def _ga_tab():
    tab = tab_for("goldapple.ru")
    if "goldapple.ru" not in (tab.js("location.hostname") or ""):
        tab.goto("https://goldapple.ru/", "goldapple", wait_js="document.readyState === 'complete'")
    return tab


def _api(tab, method, path, body=None, retried=False):
    opts = {"method": method, "credentials": "include"}
    if body is not None:
        opts["headers"] = {"Content-Type": "application/json"}
        opts["body"] = json.dumps(body)
    r = tab.js(f"fetch({json.dumps(path)}, {json.dumps(opts)}).then(async r => ({{s: r.status, b: await r.text()}}))")
    try:
        return json.loads(r["b"])
    except ValueError:
        pass
    log.warning("goldapple %s %s: %s non-JSON%s", method, path, r["s"], " again after reload" if retried else "")
    if retried:
        return None
    # As on Ozon: after a while fetch() gets 403 from the anti-bot; a real page load renews its cookies.
    tab.goto("https://goldapple.ru/", "goldapple", wait_js="document.readyState === 'complete'")
    return _api(tab, method, path, body, retried=True)


def _items(d):
    return (((d or {}).get("data") or {}).get("rawCart") or {}).get("items") or []


def _cart_text(d):
    items = _items(d)
    if not items:
        return "корзина Золотого яблока пуста"
    rows = []
    for i in items:
        price, old = i.get("specialPriceAmountClean"), i.get("oldPriceAmountClean")
        rows.append(f"{i.get('productSku')}\t{i.get('qty')}\t{price or old}\t{old if old and old != price else ''}\t"
                    f"{'✓' if i.get('isSelected') else ''}\t{i.get('brand', '')}\t{i.get('productName') or i.get('prodname', '')}\t{i.get('variant') or ''}")
    return ("корзина Золотого яблока (✓ — выбрано к оформлению; цена — за все штуки строки)\n"
            "артикул\tшт\tцена ₽\tбез скидки\t✓\tбренд\tназвание\tвариант\n" + "\n".join(rows))


def _sku(id_or_url):
    m = re.search(r"goldapple\.ru/(\d+)", str(id_or_url)) or re.fullmatch(r"\s*/?(\d+)(?:-.*)?\s*", str(id_or_url))
    return m.group(1) if m else None


def cart():
    tab = _ga_tab()
    try:
        d = _api(tab, "GET", STATE)
    finally:
        tab.close()
    return BLOCKED if d is None else _cart_text(d)


def add_to_cart(id_or_url, quantity=1):
    sku = _sku(id_or_url)
    if not sku:
        return "нужен артикул варианта (из goldapple_item) или ссылка на товар"
    tab = _ga_tab()
    try:
        _api(tab, "POST", "/front/api/cart/v3/items-by-sku?locale=ru",
             {"products": [{"sku": sku, "quantity": int(quantity), "analyticsDetailParams": {"itemId": sku}}],
              "meta": {"source": "pdp/product"}, "includeDeliveryThreshold": False})
        d = _api(tab, "GET", STATE)
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    ok = any(str(i.get("productSku")) == sku for i in _items(d))
    return f"{'добавлено' if ok else '⚠️ Золотое яблоко не подтвердило добавление'}: артикул {sku}\n" + _cart_text(d)


def remove_from_cart(id_or_url):
    sku = _sku(id_or_url)
    if not sku:
        return "нужен артикул из goldapple_cart"
    tab = _ga_tab()
    try:
        if not any(str(i.get("productSku")) == sku for i in _items(_api(tab, "GET", STATE))):
            return "такого артикула в корзине нет\n" + cart()
        _api(tab, "DELETE", f"/front/api/cart/v3/items?locale=ru&includeDeliveryThreshold=false&itemSkus={sku}")
        d = _api(tab, "GET", STATE)
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    gone = not any(str(i.get("productSku")) == sku for i in _items(d))
    return f"{'удалено' if gone else '⚠️ Золотое яблоко не подтвердило удаление'}: артикул {sku}\n" + _cart_text(d)
