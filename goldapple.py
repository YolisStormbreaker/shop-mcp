"""Gold Apple (goldapple.ru): search, product card and cart (view, add, remove). Never checks out.

The site posts the user's city and delivery zones with every catalog call, so its own page makes
the request and we take the JSON it got (capture.py). Prices and stock are for the user's city.
"""
import html
import re
import urllib.parse

from capture import capture
from cdp import page_json, site_tab, tab_for
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
        # a query the site knows as a category (шампунь) moves the page there: its cards-list has the products
        d = capture(tab, "goldapple", url, {"s": ["re:/front/api/catalog/(search-products|cards-list)"]}).get("s")
    finally:
        tab.close()
    if d is None:
        log.warning("goldapple search %s: no search-products response", url)
        return BLOCKED
    return _search_table(d, url, page, limit)


def _search_table(d, url, page, limit):
    products, found, note = _found(d.get("data") or {})
    rows = [_search_row(i + 1, p) for i, p in enumerate(products[:limit])]
    head = (f"Золотое яблоко · {found or len(rows)} найдено · страница {page} (по {PAGE}) · {url}\n" + note
            + "ссылки относительно https://goldapple.ru; цены и наличие — для города из профиля\n"
            "#\tартикул\tцена ₽\tбез скидки\tбренд\tназвание\tтип\tобъём\tрейтинг\tотзывов\tналичие\tссылка")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _found(data):
    """(products, their count as the site gives it or "", a note line): a search answer caps its count at 2000;
    a category the site moved the search to (cards-list) counts exactly and holds products among other cards."""
    if "cards" in data:
        return _category(data)
    count = data.get("count") or 0
    return data.get("products") or [], f"{count}+" if count >= 2000 else str(count or ""), ""


def _category(data):
    note = f"сайт перенёс поиск в категорию https://goldapple.ru{data['url']}\n" if data.get("url") else ""
    return [c["product"] for c in data["cards"] or [] if c.get("cardType") == "product"], str(data.get("productCount") or ""), note


def _search_row(n, p):
    actual, old = _rub(p.get("price"), "actual"), _rub(p.get("price"), "old")
    rv = p.get("reviews") or {}
    return (f"{n}\t{p.get('itemId')}\t{actual}\t{old if old and old != actual else ''}\t{p.get('brand', '')}\t"
            f"{p.get('name', '')}\t{p.get('productType', '')}\t{_volume(p)}\t{rv.get('rating') or ''}\t"
            f"{rv.get('reviewsCount') or ''}\t{'' if p.get('inStock') else 'нет в наличии'}\t{p.get('url', '')}")


def _volume(p):
    units = (p.get("attributes") or {}).get("units") or {}
    volume = f"{units.get('currentUnitValue')} {units.get('name')}" if units.get("currentUnitValue") else ""
    return volume + (f" (вариантов: {units['count']})" if units.get("count", 0) > 1 else "")


def _img(o, screen="fullhd"):
    """A picture URL from the site's template: {url with ${screen}.${format}, format: [...], screen: [...]}."""
    fmt = "jpg" if "jpg" in (o.get("format") or []) else (o.get("format") or ["webp"])[0]
    return (o.get("url") or "").replace("${screen}", screen).replace("${format}", fmt)


def _delivery(d):
    return [_delivery_option(o) for o in (d or {}).get("options") or []]


def _delivery_option(o):
    cost = ((o.get("cost") or {}).get("value") or {}).get("amount")
    return (f"{o.get('name')} — {o.get('dateInfo') or (o.get('date') or '')[:10]}"
            + (f", {cost} ₽" if cost else ", бесплатно" if cost == 0 else "")
            + (f" ({o['costSpecial']})" if o.get("costSpecial") else ""))


def item(url, full=False):
    if url.startswith("/"):
        url = "https://goldapple.ru" + url
    m = re.search(r"goldapple\.ru/(\d+)-", url)  # without the name part the site shows «страница не найдена»
    if not m:
        return "нужна ссылка на товар из goldapple_search: https://goldapple.ru/<артикул>-<название>"
    tab = tab_for("goldapple.ru")
    try:
        got = capture(tab, "goldapple", url, {"c": ["/front/api/catalog/product-card/base/v3", m.group(1)],
                                              "deliv": ["/web/api/v1/delivery/calculate/item"]})
    finally:
        tab.close()
    d = got.get("c")
    if d is None:
        log.warning("goldapple item %s: no product-card response", url)
        return BLOCKED
    return _card(d.get("data") or d, m.group(1), url, got.get("deliv"), full)


def _card(x, sku, url, deliv, full):
    lines = [f"{x.get('brand', '')} {x.get('name', '')} ({x.get('productType', '')})", url.split("?")[0],
             f"артикул: {x.get('itemId')}", "варианты: " + "; ".join(_variants(x))]
    deliv = _delivery(deliv)
    if deliv:
        lines.append("доставка: " + "; ".join(deliv))
    photos = _photos(x.get("variants") or [], sku)
    if photos:
        lines.append("фото (shop_images): " + " ".join(photos[:10]))
    lines.append("отзывы: goldapple_reviews")
    text = _description(x)
    lines.append("\n" + (text if full else text[:2500]))
    return "\n".join(lines)


def _variants(x):
    attrs = x.get("attributes") or {}
    unit = (attrs.get("units") or {}).get("unit", "")
    colors = {o["value"]: o["text"] for o in (attrs.get("colors") or {}).get("options") or []}
    return [_variant(v, unit, colors) for v in x.get("variants") or []]


def _variant(v, unit, colors):
    price = v.get("price") or {}
    actual, old = _rub(price, "actual"), _rub(price, "old")
    pct = (price.get("viewOptions") or {}).get("discountPercent")
    return (f"{_label(v, unit, colors) or v.get('itemId')} — {actual} ₽" + (f" (было {old}, −{pct}%)" if old and old != actual else "")
            + ("" if v.get("inStock") else ", нет в наличии") + f", артикул {v.get('itemId')}")


def _label(v, unit, colors):
    """volume and color, e.g. '7.5 г 0.5, Porcelain'"""
    av = v.get("attributesValue") or {}
    return " ".join(s for s in (f"{av['units']} {unit}".strip() if av.get("units") else "", colors.get(av.get("colors"), "")) if s)


def _photos(variants, sku):
    photos = []
    for v in variants:
        if str(v.get("itemId")) == sku or not photos:
            photos = [_img(i) for i in v.get("imageUrls") or []]
    return photos


def _description(x):
    return "\n".join(f"{s.get('text')}: {_text(s.get('content'))}" for s in x.get("productDescription") or []
                     if s.get("type") != "Brand" and s.get("content"))


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
    rows = [_review_row(r) for r in ((data.get("listing") or {}).get("reviews") or [])[:limit]]
    return _reviews_head(data, sku, sort, with_media, page) + "\n" + ("\n".join(rows) if rows else "(отзывов нет)")


def _reviews_head(data, sku, sort, with_media, page):
    st = data.get("statistic") or {}
    stars = " ".join(f"{x['star']}★ {x['percent']}%" for x in st.get("starStatistic") or [])
    return (f"Золотое яблоко · артикул {sku}: рейтинг {st.get('rating')}, отзывов {st.get('allReviewsCount')}, "
            f"рекомендуют {st.get('recommended')}% · {stars}\n"
            f"страница {page} (по 20), сортировка {sort}{', только с фото' if with_media else ''}; "
            f"фото с отзывов всего: {(data.get('gallery') or {}).get('mediaCount', 0)}\n"
            "дата\t★\tполезно\tвариант\tавтор\tтекст\tфото (shop_images)")


def _review_row(r):
    # a color's value is its swatch picture, its name is the shade
    variant = " ".join(f"{'' if isinstance(a.get('value'), dict) else a.get('value')} {a.get('name', '')}".strip()
                       for a in (r.get("attributes") or {}).values())
    photos = " ".join(_img(i.get("original") or {}) for i in r.get("imageUrls") or [])
    return (f"{(r.get('submitDate') or '')[:10]}\t{r.get('stars')}\t{r.get('likes') or ''}\t{variant}\t"
            f"{r.get('username', '')}\t{_text(_review_text(r))}\t{photos}")


def _review_text(r):
    return " | ".join(p for p in (f"+ {r['pros']}" if r.get("pros") else "", f"− {r['cons']}" if r.get("cons") else "",
                                   r.get("comment") or "") if p)


# The cart is a plain same-origin API with the session cookie (names from the site's own code:
# getState, addItemsBySku, deleteItems), so it works from a background tab.
STATE = "/front/api/cart/v3/state?locale=ru&includeDeliveryThreshold=false"


def _ga_tab():
    return site_tab("goldapple.ru", "https://goldapple.ru/", "goldapple")


def _api(tab, method, path, body=None):
    return page_json(tab, method, path, body, "https://goldapple.ru/", "goldapple")


def _items(d):
    return (((d or {}).get("data") or {}).get("rawCart") or {}).get("items") or []


def _cart_text(d):
    items = _items(d)
    if not items:
        return "корзина Золотого яблока пуста"
    return ("корзина Золотого яблока (✓ — выбрано к оформлению; цена — за все штуки строки)\n"
            "артикул\tшт\tцена ₽\tбез скидки\t✓\tбренд\tназвание\tвариант\n" + "\n".join(map(_cart_row, items)))


def _cart_row(i):
    old = i.get("oldPriceAmountClean")
    price = i.get("specialPriceAmountClean") or old
    return (f"{i.get('productSku')}\t{i.get('qty')}\t{price}\t{old if old and old != price else ''}\t"
            f"{'✓' if i.get('isSelected') else ''}\t{i.get('brand', '')}\t{i.get('productName') or i.get('prodname', '')}\t{i.get('variant') or ''}")


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
    ok = _in_cart(d, sku)
    return f"{'добавлено' if ok else '⚠️ Золотое яблоко не подтвердило добавление'}: артикул {sku}\n" + _cart_text(d)


def _in_cart(d, sku):
    return any(str(i.get("productSku")) == sku for i in _items(d))


def remove_from_cart(id_or_url):
    sku = _sku(id_or_url)
    if not sku:
        return "нужен артикул из goldapple_cart"
    tab = _ga_tab()
    try:
        d = _api(tab, "GET", STATE)
        if d is None:
            return BLOCKED
        if not _in_cart(d, sku):
            return "такого артикула в корзине нет\n" + _cart_text(d)  # not cart(): that would wait for this very tab
        _api(tab, "DELETE", f"/front/api/cart/v3/items?locale=ru&includeDeliveryThreshold=false&itemSkus={sku}")
        d = _api(tab, "GET", STATE)
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    gone = not _in_cart(d, sku)
    return f"{'удалено' if gone else '⚠️ Золотое яблоко не подтвердило удаление'}: артикул {sku}\n" + _cart_text(d)
