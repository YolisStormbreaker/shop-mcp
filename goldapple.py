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


def _img(o, screen="fullhd"):
    """A picture URL from the site's template: {url with ${screen}.${format}, format: [...], screen: [...]}."""
    fmt = "jpg" if "jpg" in (o.get("format") or []) else (o.get("format") or ["webp"])[0]
    return (o.get("url") or "").replace("${screen}", screen).replace("${format}", fmt)


def _delivery(d):
    rows = []
    for o in (d or {}).get("options") or []:
        cost = ((o.get("cost") or {}).get("value") or {}).get("amount")
        rows.append(f"{o.get('name')} — {o.get('dateInfo') or (o.get('date') or '')[:10]}"
                    + (f", {cost} ₽" if cost else ", бесплатно" if cost == 0 else "")
                    + (f" ({o['costSpecial']})" if o.get("costSpecial") else ""))
    return rows


def item(url, full=False):
    if url.startswith("/"):
        url = "https://goldapple.ru" + url
    m = re.search(r"goldapple\.ru/(\d+)-", url)  # without the name part the site shows «страница не найдена»
    if not m:
        return "нужна ссылка на товар из goldapple_search: https://goldapple.ru/<артикул>-<название>"
    sku = m.group(1)
    tab = tab_for("goldapple.ru")
    try:
        got = capture(tab, "goldapple", url, {"c": ["/front/api/catalog/product-card/base/v3", sku],
                                              "deliv": ["/web/api/v1/delivery/calculate/item"]})
    finally:
        tab.close()
    d = got.get("c")
    if d is None:
        log.warning("goldapple item %s: no product-card response", url)
        return BLOCKED
    x = d.get("data") or d
    attrs = x.get("attributes") or {}
    unit = (attrs.get("units") or {}).get("unit", "")
    colors = {o["value"]: o["text"] for o in (attrs.get("colors") or {}).get("options") or []}
    variants, photos = [], []
    for v in x.get("variants") or []:
        av = v.get("attributesValue") or {}
        label = " ".join(s for s in (f"{av['units']} {unit}".strip() if av.get("units") else "", colors.get(av.get("colors"), "")) if s)
        price = v.get("price") or {}
        actual, old = _rub(price, "actual"), _rub(price, "old")
        pct = (price.get("viewOptions") or {}).get("discountPercent")
        variants.append(f"{label or v.get('itemId')} — {actual} ₽" + (f" (было {old}, −{pct}%)" if old and old != actual else "")
                        + ("" if v.get("inStock") else ", нет в наличии") + f", артикул {v.get('itemId')}")
        if str(v.get("itemId")) == sku or not photos:
            photos = [_img(i) for i in v.get("imageUrls") or []]
    lines = [f"{x.get('brand', '')} {x.get('name', '')} ({x.get('productType', '')})", url.split("?")[0],
             f"артикул: {x.get('itemId')}", "варианты: " + "; ".join(variants)]
    deliv = _delivery(got.get("deliv"))
    if deliv:
        lines.append("доставка: " + "; ".join(deliv))
    if photos:
        lines.append("фото (shop_images): " + " ".join(photos[:10]))
    lines.append("отзывы: goldapple_reviews")
    text = "\n".join(f"{s.get('text')}: {_text(s.get('content'))}" for s in x.get("productDescription") or []
                     if s.get("type") != "Brand" and s.get("content"))
    lines.append("\n" + (text if full else text[:2500]))
    return "\n".join(lines)


REVIEW_SORTS = {"useful": "ByUsefulness", "new": "ByNewest", "high": "ByHighestStars", "low": "ByLowestStars"}


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    sku = _sku(id_or_url)
    if not sku:
        return "нужен артикул или ссылка на товар Золотого яблока"
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    qs = {"locale": "ru", "itemId": sku, "pageNumber": page, "sortType": REVIEW_SORTS[sort]}
    if with_media:
        qs["hasMedia"] = "true"
    tab = _ga_tab()
    try:
        d = _api(tab, "GET", "/front/api/review/listing/v3?" + urllib.parse.urlencode(qs))
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    data = d.get("data") or {}
    st, listing = data.get("statistic") or {}, data.get("listing") or {}
    stars = " ".join(f"{x['star']}★ {x['percent']}%" for x in st.get("starStatistic") or [])
    head = (f"Золотое яблоко · артикул {sku}: рейтинг {st.get('rating')}, отзывов {st.get('allReviewsCount')}, "
            f"рекомендуют {st.get('recommended')}% · {stars}\n"
            f"страница {page} (по 20), сортировка {sort}{', только с фото' if with_media else ''}; "
            f"фото с отзывов всего: {(data.get('gallery') or {}).get('mediaCount', 0)}\n"
            "дата\t★\tполезно\tвариант\tавтор\tтекст\tфото (shop_images)")
    rows = []
    for r in (listing.get("reviews") or [])[:limit]:
        variant = " ".join(f"{a.get('value')} {a.get('name', '')}".strip() for a in (r.get("attributes") or {}).values())
        text = " | ".join(p for p in (f"+ {r['pros']}" if r.get("pros") else "", f"− {r['cons']}" if r.get("cons") else "",
                                       r.get("comment") or "") if p)
        photos = " ".join(_img(i.get("original") or {}) for i in r.get("imageUrls") or [])
        rows.append(f"{(r.get('submitDate') or '')[:10]}\t{r.get('stars')}\t{r.get('likes') or ''}\t{variant}\t"
                    f"{r.get('username', '')}\t{_text(text)}\t{photos}")
    return head + "\n" + ("\n".join(rows) if rows else "(отзывов нет)")


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
        d = _api(tab, "GET", STATE)
        if d is None:
            return BLOCKED
        if not any(str(i.get("productSku")) == sku for i in _items(d)):
            return "такого артикула в корзине нет\n" + _cart_text(d)  # not cart(): that would wait for this very tab
        _api(tab, "DELETE", f"/front/api/cart/v3/items?locale=ru&includeDeliveryThreshold=false&itemSkus={sku}")
        d = _api(tab, "GET", STATE)
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    gone = not any(str(i.get("productSku")) == sku for i in _items(d))
    return f"{'удалено' if gone else '⚠️ Золотое яблоко не подтвердило удаление'}: артикул {sku}\n" + _cart_text(d)
