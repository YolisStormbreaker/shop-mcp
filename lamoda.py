"""Lamoda: search, product card, reviews and cart (view, add, remove). Never checks out.

Pages are server-rendered with the data in window.__NUXT__ (products, prices with every discount
applied, sizes in stock), so we read that state instead of the markup.
"""
import json
import re
import urllib.parse

from cdp import page_json, site_tab, tab_for
from shoplog import dump, log

SORTS = ("default", "new", "price_asc", "price_desc", "new_sale", "discount")
STATE = "window.__NUXT__?.payload?.state?.payload"
BLOCKED = "⚠️ Lamoda не отдала данные страницы (проверка на бота?): shop-chrome show, открыть сайт, повторить."

SEARCH_JS = f"(() => {{ const P = {STATE}; return P?.products ? {{pagination: P.pagination || {{}}, products: P.products}} : null }})()"


ITEM_JS = f"{STATE}?.product || null"


def search(query, price_min=None, price_max=None, sort="default", page=1, limit=30):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    url = _search_url(query, price_min, price_max, sort, page)
    tab = tab_for("lamoda.ru")
    try:
        # the tab still holds the previous page's state until the new one loads
        old = tab.js(f"{STATE}?.catalog_request_id || ''")
        tab.goto(url, "lamoda", wait_js=f"!!{STATE}?.products && {STATE}.catalog_request_id !== {json.dumps(old)}")
        r = tab.js(SEARCH_JS)
        if r is None:
            saved = dump("lamoda", "search", tab.js("document.documentElement.outerHTML"))
            log.warning("lamoda search %s: no __NUXT__ products, page %s", url, saved)
    finally:
        tab.close()
    return BLOCKED if r is None else _search_table(r, url, limit)


def _search_url(query, price_min, price_max, sort, page):
    qs = {"q": query}
    if sort != "default":
        qs["sort"] = sort
    if price_min or price_max:
        qs["price"] = f"{int(price_min or 0)},{int(price_max or 10_000_000)}"
    if page > 1:
        qs["page"] = page
    return "https://www.lamoda.ru/catalogsearch/result/?" + urllib.parse.urlencode(qs)


def _search_table(r, url, limit):
    products = [x["product"] for x in r["products"] if x.get("type") == "product"]   # the rest are ad banners
    rows = [_search_row(i + 1, p) for i, p in enumerate(products[:limit])]
    pg = r["pagination"]
    head = (f"Lamoda · {pg.get('found', len(products))} найдено · страница {pg.get('page') or 1} из {pg.get('pages') or 1} · {url}\n"
            "ссылки относительно https://www.lamoda.ru; цена — со всеми скидками, включая вашу скидку лояльности; "
            "«до» — когда кончается акционная цена; размеры в наличии — в системе бренда\n"
            "#\tsku\tцена ₽\tбез скидок\tакция до\tбренд\tназвание\tрейтинг\tотзывов\tразмеры в наличии\tпометки\tссылка")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _rub(price):
    return int(re.sub(r"\D", "", str(price.get("price", ""))) or 0)     # "1 040" -> 1040


def _offers(prices):
    """(the final price, the highest, when the final one ends) from {"original": {"price": "1 040"},
    "action": {"price": "728", "discount": {"active_to": …}}, …}"""
    offers = [x for x in (prices or {}).values() if _rub(x)]
    final = min(offers, key=_rub, default={})
    return _rub(final), max(map(_rub, offers), default=0), ((final.get("discount") or {}).get("active_to") or "")[:10]


def _search_row(n, p):
    price, base, until = _offers(p.get("prices"))
    sizes = " ".join(s["brand_title"] for s in p.get("sizes") or [] if s.get("stock_quantity"))
    return "\t".join(map(str, [
        n, p["sku"], price, base if base > price else "", until,
        (p.get("brand") or {}).get("title", ""), p.get("title", ""), f"{p['average_rating']:.1f}" if p.get("average_rating") else "",
        (p.get("counters") or {}).get("reviews") or "", sizes, "реклама" if p.get("ad_params") else "",
        f"/p/{p['sku'].lower()}/{p.get('seo_tail', '')}/"]))


def item(sku_or_url, full=False):
    url = _item_url(sku_or_url)
    m = re.search(r"/p/([a-z0-9]+)", url, re.I)
    ready = f"{STATE}?.product?.sku?.toLowerCase() === {json.dumps(m.group(1).lower())}" if m else f"!!{STATE}?.product"
    tab = tab_for("lamoda.ru")
    try:
        tab.goto(url, "lamoda", wait_js=ready)
        p = tab.js(ITEM_JS)
        if p is None:
            saved = dump("lamoda", "item", tab.js("document.documentElement.outerHTML"))
            log.warning("lamoda item %s: no __NUXT__ product, page %s", url, saved)
    finally:
        tab.close()
    return BLOCKED if p is None else _card(p, url, full)


def _item_url(sku_or_url):
    s = sku_or_url.strip()
    if s.startswith("/"):
        s = "https://www.lamoda.ru" + s
    return s if "lamoda.ru" in s else f"https://www.lamoda.ru/p/{s.lower()}/"


def _card(p, url, full):
    description = p.get("description") or ""
    return "\n".join(x for x in [
        _item_head(p), url.split("?")[0], _seller(p), _item_sizes(p),
        _joined("цены: ", _item_prices(p)),
        _joined("доставка: ", _item_delivery(p)),
        f"рейтинг {p.get('average_rating') or '—'}, отзывов на этот цвет {(p.get('counters') or {}).get('reviews') or 0} (все цвета — lamoda_reviews)",
        _joined("фото (shop_images): ", ["https://a.lmcdn.ru/product" + x for x in p.get("gallery") or []][:10], " "),
        _joined("характеристики: ", [f"{a.get('title')}: {a.get('value')}" for a in p.get("attributes") or []]),
        "\n" + (description if full else description[:2500])] if x)


def _joined(label, values, sep="; "):
    return label + sep.join(values) if values else ""


def _item_head(p):
    brand = p.get("brand") or {}
    title = " ".join(x for x in (brand.get("title") or brand.get("name"), p.get("model_title") or p.get("title")) if x)
    price, base, _ = _offers(p.get("prices"))
    return f"{title} ({p.get('title')})" + (f" — {price} ₽" if price else "") + (f", без скидок {base} ₽" if base > price else "")


def _seller(p):
    return f"sku: {p.get('sku')} · продавец: {_seller_name(p)} · " + ("можно вернуть" if p.get("is_returnable") else "⚠️ без возврата")


def _seller_name(p):
    """A partner's seller.title is the link text «подробнее»; its shop and legal names are in product.owner."""
    o = p.get("owner") or {}
    names = [x for x in (o.get("shop_name"), o.get("company_name")) if x]
    if not names:
        return (p.get("seller") or {}).get("title") or ""
    return names[0] + "".join(f" ({x})" for x in names[1:])


def _item_sizes(p):
    return _joined("размеры: ", [_size(s) for s in p.get("sizes") or []]) or ("в наличии" if p.get("is_in_stock") else "нет в наличии")


def _size(s):
    brand = f" ({s.get('brand_size_system')} {s['brand_title']})" if s.get("brand_title") and s["brand_title"] != s.get("title") else ""
    return f"{s.get('title')}{brand}: " + (f"{s['stock_quantity']} шт" if s.get("stock_quantity") else "нет")


def _item_prices(p):
    """every price the site knows: original, and each discount under its kind (loyalty, action, promocode)"""
    return [f"{k} {x.get('price')} ₽" + _discount(x.get("discount")) for k, x in (p.get("prices") or {}).items()]


def _discount(d):
    if not d:
        return ""
    return f" (−{d.get('percent')}%" + (f", промокод {d['promocode']}" if d.get("promocode") else "") + ")"


def _item_delivery(p):
    best = (p.get("delivery") or {}).get("best_delivery_info") or {}
    ways = [((d.get(d.get("type")) or {}).get("info") or {}).get("title") for d in best.get("delivery_data") or []]
    return [x for x in (best.get("description"), *ways) if x]


# The product page's own review client (productReviewsV2 in its code). only_with_photos was found by trying
# names: with_photos and filters=["photo"] are ignored. with_related adds the other colors of the model.
REVIEW_SORTS = {"useful": ("ranking_score", "desc"), "new": ("date", "desc"), "high": ("rating", "desc"), "low": ("rating", "asc")}


def reviews(sku_or_url, sort="useful", with_media=False, page=1, this_color=False, limit=20):
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    sku = _review_sku(sku_or_url)
    if not sku:
        return "нужен sku Lamoda или ссылка https://www.lamoda.ru/p/<sku>/..."
    by, direction = REVIEW_SORTS[sort]
    body = {"limit": limit, "offset": (page - 1) * limit, "sku": sku, "with_related": not this_color,
            "sort": by, "sort_direction": direction}
    if with_media:
        body["only_with_photos"] = True
    tab = _lm_tab()
    try:
        d = _api(tab, "POST", "/api/v1/product/reviews_v2", body)
        info = _api(tab, "GET", f"/api/v1/product/reviews_info?sku={sku}&with_related={json.dumps(not this_color)}") or {}
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    rows = "\n".join(map(_review_row, d.get("reviews") or [])) or "(отзывов нет)"
    return (_reviews_rating(sku, d, info) + "\n" + _reviews_scope(d.get("total") or 0, sort, with_media, page, this_color, limit) + "\n"
            "дата\t★\tполезно +/−\tкуплено (размер, цвет)\tавтор\tтекст\tфото (shop_images)\n" + rows)


def _review_sku(sku_or_url):
    m = re.search(r"/p/([a-z0-9]+)", sku_or_url, re.I) or re.fullmatch(r"\s*([a-z0-9]{10,})\s*", sku_or_url, re.I)
    return m and m.group(1).upper()


def _reviews_rating(sku, d, info):
    fit = "; ".join(v["title"] for v in (info.get("average_fittings") or {}).values() if isinstance(v, dict) and v.get("title"))
    return (f"Lamoda · {sku}: рейтинг {info.get('average_rating') or '—'}, отзывов {info.get('total_review_count', d.get('total') or 0)}, "
            f"фото в отзывах {info.get('total_photos_count', d.get('total_photos', 0))}" + (f" · по отзывам: {fit}" if fit else ""))


def _reviews_scope(total, sort, with_media, page, this_color, limit):
    return (f"{'только этот цвет' if this_color else 'все цвета модели'}: {total}{' с фото' if with_media else ''}, "
            f"страница {page} из {max(1, -(-total // limit))} по {limit}, сортировка {sort}")


def _review_row(x):
    sn = x.get("snippet") or {}
    photos = " ".join(p["url"] for p in x.get("photos") or [] if p.get("url"))
    return (f"{(x.get('created_time') or '')[:10]}\t{x.get('rating', '')}\t+{x.get('like_count', 0)}/−{x.get('dislike_count', 0)}\t"
            f"{_bought(sn.get('purchase') or {})}\t{(sn.get('header') or {}).get('author', '')}\t{_review_text(x, sn)}\t{photos}")


def _bought(purchase):
    """the size, then the color and the rest"""
    return ", ".join(v for v in [purchase.get("value", ""), *((purchase.get("combines") or {}).values())] if v)


def _review_text(x, sn):
    params = "; ".join(p["title"] for p in sn.get("item_params") or [] if p.get("title"))
    return " ".join(((x.get("text") or "") + (f" | {params}" if params else "")).split())


# Cart: the site's own API client (cartGet / cartAdd / cartRemove in its code) — same-origin JSON with
# the session cookie, so it works from a background tab. geo is the delivery region the site keeps in
# the gd_aoid cookie; the tab must be on lamoda.ru for relative URLs and that cookie.
def _lm_tab():
    return site_tab("lamoda.ru", "https://www.lamoda.ru/", "lamoda")


def _api(tab, method, path, body=None):
    return page_json(tab, method, path, body, "https://www.lamoda.ru/", "lamoda")


def _geo(tab):
    aoid = tab.js("decodeURIComponent((document.cookie.match(/(?:^|; )gd_aoid=([^;]+)/) || [])[1] || '')")
    return {"aoid": aoid} if aoid else None


def _lines(d):
    return [i for p in (d or {}).get("packages") or [] for i in p.get("items") or []]


def _cart_text(d):
    items = _lines(d)
    if not items:
        return "корзина Lamoda пуста"
    return (f"корзина Lamoda: {d.get('total_quantity')} шт, итого {d.get('total_price')} ₽ (со всеми скидками)\n"
            "sku размера\tшт\tсумма ₽\tбез скидок\tбренд\tназвание\tразмер\n" + "\n".join(map(_cart_row, items)))


def _cart_row(i):
    product, total, original = i.get("product") or {}, i.get("total_price"), i.get("original_price")
    return "\t".join(map(str, [i["size"].get("sku"), i.get("quantity"), total, original if original != total else "",
                               product.get("brand", {}).get("title", ""), product.get("title", ""), i["size"].get("title", "")]))


def cart():
    tab = _lm_tab()
    try:
        d = _api(tab, "GET", "/api/v1/cart/get")
    finally:
        tab.close()
    return BLOCKED if d is None else _cart_text(d)


SIZES_JS = f"({STATE}?.product?.sizes || []).map(s => ({{sku: s.sku, title: s.title, brand: s.brand_title || '', stock: s.stock_quantity || 0}}))"


def add_to_cart(sku_or_url, size=None):
    sku = _product_sku(sku_or_url)
    if not sku:
        return "нужен sku товара (из lamoda_search) или ссылка на товар"
    tab = _lm_tab()
    try:
        tab.goto(f"https://www.lamoda.ru/p/{sku.lower()}/", "lamoda", wait_js=f"{STATE}?.product?.sku === {json.dumps(sku)}")
        pick = _pick_size(tab.js(SIZES_JS), size)
        if isinstance(pick, str):
            return pick
        geo = _geo(tab)
        if not geo:
            return "⚠️ не нашёл регион доставки Lamoda (cookie gd_aoid): открой сайт и выбери город"
        _api(tab, "POST", "/api/v1/cart/add", {"sku": pick["sku"], "geo": geo})
        d = _api(tab, "GET", "/api/v1/cart/get")
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    ok = _has(d, pick["sku"])
    return f"{'добавлено' if ok else '⚠️ Lamoda не подтвердила добавление'}: {pick['sku']}, размер {pick['title']}\n" + _cart_text(d)


def _product_sku(sku_or_url):
    s = sku_or_url.strip()
    m = re.search(r"/p/([a-z0-9]+)", s, re.I) or re.fullmatch(r"([a-z0-9]{12})", s, re.I)
    return m and m.group(1).upper()


def _pick_size(sizes, size):
    """The size to put in the cart from the page's [{sku, title, brand, stock}], or the answer why there is none."""
    if not sizes:
        return BLOCKED
    names = ", ".join(map(_size_name, sizes))
    if size is None and len(sizes) > 1:
        return "у товара несколько размеров, укажи size: " + names
    pick = sizes[0] if size is None else _find_size(sizes, size)
    if not pick:
        return f"нет размера «{size}»; есть: " + names
    if not pick["stock"]:
        return f"размер {pick['title']} закончился; есть: " + names
    return pick


def _size_name(x):
    brand = f" ({x['brand']})" if x["brand"] and x["brand"] != x["title"] else ""
    return f"{x['title']}{brand}: {x['stock']} шт"


def _find_size(sizes, size):
    """by its Russian title, its brand title or its sku, in any case"""
    want = str(size).strip().lower()
    return next((x for x in sizes if want in (x["title"].lower(), x["brand"].lower(), x["sku"].lower())), None)


def _has(d, size_sku):
    return any(i["size"].get("sku") == size_sku for i in _lines(d))


def remove_from_cart(size_sku):
    size_sku = size_sku.strip().upper()
    tab = _lm_tab()
    try:
        d = _api(tab, "GET", "/api/v1/cart/get")
        if d is None:
            return BLOCKED
        if not any(i["size"].get("sku") == size_sku for i in _lines(d)):
            return "такого sku размера в корзине нет\n" + _cart_text(d)
        _api(tab, "POST", "/api/v1/cart/remove", {"skus": [size_sku], "geo": _geo(tab)})
        d = _api(tab, "GET", "/api/v1/cart/get")
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    gone = not any(i["size"].get("sku") == size_sku for i in _lines(d))
    return f"{'удалено' if gone else '⚠️ Lamoda не подтвердила удаление'}: {size_sku}\n" + _cart_text(d)
