"""Эльдорадо (eldorado.ru): search, product card and reviews. Read only.

Its React Router pages are rendered on the server for the user's city (from the cookies) and carry their data in
window.__reactRouterContext.state.loaderData, keyed by route. We read the page route's own entry, never "root",
which holds the user's profile and basket. Product ids, photos and reviews are М.Видео's (one company), so the
shared helpers come from mvideo.py. Next pages of search and reviews load only on scroll, by a signed cursor.
"""
import json
import re
import urllib.parse

from cdp import tab_for
from mvideo import CITY, description, price_line, product_id, review_rows, reviews_head, tail
from shoplog import log

HOME = "https://www.eldorado.ru"
PAGE = 60
REVIEWS_PAGE = 18
SORTS = ("popular", "price_asc", "price_desc")          # its URL takes just these (listingFeed.request.dto)
REVIEW_SORTS = {"useful": None, "new": "new", "old": "old", "high": "rating-desc", "low": "rating-asc"}
DELIVERY = {"COURIER": "курьер", "PICKUP": "самовывоз"}
BLOCKED = "⚠️ Эльдорадо не отдало данные страницы (нет такого товара или проверка на бота?): shop-chrome show, открыть сайт, повторить."
SEARCH_PICK = "{total: d.initialListingChunk?.total, items: d.initialListingChunk?.items}"
ITEM_PICK = ("{product: (({name, sku_id, customer_price, base_price, rating, reviews_count, description, properties}) =>"
             " ({name, sku_id, customer_price, base_price, rating, reviews_count, description, properties}))(d.product || {}),"
             " delivery: d.deliveryMethods, summary: d.summary, seller: d.seller?.name, gallery: (d.gallery || []).map(g => g.src)}")
REVIEWS_PICK = "{chunk: d.initialReviewsChunk, rating: d.reviewsMeta?.averageRating}"


def _load(url, route, pick):
    """pick (a JS expression over d) of the route's loader data after a fresh load of url, or None."""
    loader = f"window.__reactRouterContext?.state?.loaderData?.[{json.dumps(route)}]"
    tab = tab_for("eldorado.ru")
    try:
        tab.js("window.__shopStale = true")     # a new document drops it, so the previous page's data is never read
        # the client fills loaderData once it decodes the stream: then a route missing from it means "no such page"
        tab.goto(url, "eldorado", wait_js="!window.__shopStale && !!window.__reactRouterContext?.state?.loaderData")
        return tab.js(f"(d => d ? {pick} : null)({loader})")
    finally:
        tab.close()


def search(query, price_min=None, price_max=None, sort="popular", page=1, limit=PAGE):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    if page != 1:
        return (f"Эльдорадо отдаёт дальше первой страницы только при прокрутке: здесь только страница 1 (до {PAGE} товаров). "
                "Уточни запрос или задай price_min/price_max.")
    qs = {"q": query, **({"sort": sort} if sort != "popular" else {}),
          **({"price_min": int(price_min)} if price_min else {}), **({"price_max": int(price_max)} if price_max else {})}
    url = HOME + "/search?" + urllib.parse.urlencode(qs)
    d = _load(url, "ui/pages/Search/Search", SEARCH_PICK)
    if not d:
        log.warning("eldorado search %s: no loader data", url)
        return BLOCKED
    items = d.get("items") or []
    head = (f"Эльдорадо · {d.get('total', len(items))} найдено · страница 1 (по {PAGE}) · {url}\n"
            f"ссылки относительно {HOME}; цены и сроки доставки — {CITY}\n"
            "#\tартикул\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tдоставка\tссылка")
    rows = [_search_row(i + 1, p) for i, p in enumerate(items[:limit])]
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _search_row(n, p):
    old = re.sub(r"\D", "", p.get("priceOldLabel") or "") if p.get("discountPercent") else ""
    cells = (n, p.get("skuId"), p.get("customerPrice"), old, p.get("title"), p.get("rating") or "", p.get("reviewsCount") or "",
             p.get("minEtaLabel"), f"/products/{p.get('skuId')}")
    return "\t".join("" if c is None else str(c) for c in cells)


def item(url_or_id, full=False):
    pid = product_id(url_or_id)
    if not pid:
        return f"нужен артикул или ссылка на товар Эльдорадо: {HOME}/products/<артикул>"
    url = f"{HOME}/products/{pid}"
    d = _load(url, "ui/pages/ProductPage/ProductPage", ITEM_PICK)
    if not d:
        log.warning("eldorado item %s: no loader data", url)
        return BLOCKED
    return _card(d, pid, url, full)


def _card(d, pid, url, full):
    p = d.get("product") or {}
    lines = [p.get("name") or "", url, f"артикул: {p.get('sku_id') or pid}", price_line(p.get("customer_price"), p.get("base_price"))]
    lines += _stock(d.get("summary") or {}) + _rating(p) + _delivery(d.get("delivery")) + _seller(d.get("seller"))
    specs = [f"{x.get('name')}: {x.get('value')}" for g in p.get("properties") or [] for x in g.get("properties") or []]
    return "\n".join(lines + tail(specs, d.get("gallery"), "eldorado_reviews")) + "\n\n" + description(p.get("description"), full)


def _seller(name):
    return [f"продавец: {name}"] if name else []


def _stock(summary):
    if summary.get("isOutOfStock"):
        return ["нет в наличии"]
    return [f"в наличии: {summary['leftoversQuantity']} шт."] if summary.get("leftoversQuantity") else []


def _rating(p):
    return [f"рейтинг: {p.get('rating')}, отзывов {p['reviews_count']}"] if p.get("reviews_count") else []


def _delivery(methods):
    got = [f"{DELIVERY.get(m.get('methodId'), m.get('methodId'))} — {m.get('etaLabel')}" for m in methods or []]
    return [f"доставка ({CITY}): " + "; ".join(got)] if got else []


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=REVIEWS_PAGE):
    pid = product_id(id_or_url)
    if not pid:
        return "нужен артикул или ссылка на товар Эльдорадо"
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    if page != 1:
        return (f"Эльдорадо отдаёт страницей только первые {REVIEWS_PAGE} отзывов, дальше — при прокрутке. "
                "Другие отзывы: смени sort или with_media, или возьми mvideo_reviews: отзывы у М.Видео и Эльдорадо общие.")
    url = _reviews_url(pid, sort, with_media)
    d = _load(url, "ui/pages/ProductReviewsPage/ProductReviewsPage", REVIEWS_PICK)
    if not d:
        log.warning("eldorado reviews %s: no loader data", url)
        return BLOCKED
    c = d.get("chunk") or {}
    return (reviews_head("Эльдорадо", pid, d.get("rating"), c.get("total"), c.get("ratingsStats"))
            + f"страница 1 (по {REVIEWS_PAGE}), сортировка {sort}{', только с фото' if with_media else ''}; "
            f"фото с отзывов всего: {c.get('photosCount') or 0}\n" + review_rows(c.get("items"), limit))


def _reviews_url(pid, sort, with_media):
    qs = {**({"sort": REVIEW_SORTS[sort]} if REVIEW_SORTS[sort] else {}), **({"photos": 1} if with_media else {})}
    return f"{HOME}/products/{pid}/reviews" + ("?" + urllib.parse.urlencode(qs) if qs else "")
