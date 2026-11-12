"""М.Видео (mvideo.ru): search, product card and reviews. Read only.

The site's Angular page asks its own /bff API, the user's city riding in its cookies, so we take the JSON the
page got (capture.py); a request the page makes for page 1 is rewritten when we want another page.
Эльдорадо is the same company on another front-end with the same product ids, photos and reviews:
eldorado.py reuses the helpers here that have no leading underscore.
"""
import html
import json
import re
import urllib.parse

from capture import capture
from cdp import tab_for
from shoplog import log

HOME = "https://www.mvideo.ru"
PAGE = 60
REVIEWS_PAGE = 10
SORTS = {"popular": ("popularity", "desc"), "price_asc": ("price", "asc"), "price_desc": ("price", "desc")}  # -> its sortBy, sortDirection
REVIEW_SORTS = {"useful": "useful:desc", "new": "created_at:desc", "old": "created_at:asc", "high": "rating:desc", "low": "rating:asc"}
HANDOVER = {"pickup": "самовывоз из магазина", "pickup-partner": "пункт выдачи партнёра", "eta-delivery": "экспресс-доставка",
            "interval-delivery": "курьер к интервалу"}
BLOCKED = "⚠️ М.Видео не отдало данные (проверка на бота?): shop-chrome show, открыть сайт, повторить."
CITY = "для города из профиля на сайте"


def product_id(s):
    """The numeric id from an id or a product link (/products/<id>, /products/<slug>-<id>) of М.Видео or Эльдорадо."""
    m = re.search(r"/products/(?:[^/?#]*-)?(\d{5,13})(?:[/?#]|$)", str(s)) or re.fullmatch(r"\s*(\d{5,13})\s*", str(s))
    return m.group(1) if m else None


def photo(path):
    """A picture URL: the API gives paths relative to the image CDN, absolute or protocol-relative URLs."""
    if path.startswith("//"):
        return "https:" + path
    return path if path.startswith("http") else "https://img.mvideo.ru/" + path.lstrip("/")


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def price_line(price, old):
    if price is None:
        return "цена: —"
    if not old or old == price:
        return f"цена: {price} ₽"
    return f"цена: {price} ₽ (было {old}, −{round((old - price) * 100 / old)}%)"


def search(query, price_min=None, price_max=None, sort="popular", page=1, limit=PAGE):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    price = f"{int(price_min) if price_min else ''}-{int(price_max) if price_max else ''}" if price_min or price_max else None
    url = _search_url(query, price, sort)
    body = json.dumps(_search_body(query, price, sort, page), ensure_ascii=False)
    # the page asks for page 1 only (more come on scroll): the same request with the cursor of page N
    rewrite = ("*/bff/products", lambda u: (u, body)) if page > 1 else None
    tab = tab_for("mvideo.ru")
    try:
        d = capture(tab, "mvideo", url, {"s": ["re:/bff/products$"]}, rewrite=rewrite).get("s")
    finally:
        tab.close()
    if not (d or {}).get("body"):
        log.warning("mvideo search %s: no /bff/products answer", url)
        return BLOCKED
    return _search_table(d["body"], url, page, limit)


def _search_url(query, price, sort):
    qs = {"q": query}
    if sort != "popular":
        qs["sort"] = sort
    if price:
        qs["f_price"] = price
    return HOME + "/search?" + urllib.parse.urlencode(qs)


def _search_body(query, price, sort, page):
    """The body the site's own search page posts (recorded 2026-11), its cursor being the offset."""
    by, direction = SORTS[sort]
    return {"limit": PAGE, "cursorId": str((page - 1) * PAGE), "enrich": True,
            "filters": [{"id": "price", "valuesId": [price]}] if price else [], "sortBy": by, "sortDirection": direction,
            "isGettingBonusRoubles": True, "query": query}


def _search_table(body, url, page, limit):
    items = body.get("items") or []
    ads = sum(1 for p in items if p.get("adType"))
    rows = [_search_row(i + 1, p) for i, p in enumerate(items[:limit])]
    head = (f"М.Видео · {body.get('total', len(items))} найдено · страница {page} (по {PAGE}) · "
            f"реклама: {ads} из {len(items)} на странице · {url}\n"
            f"ссылки относительно {HOME}; цены и наличие — {CITY}\n"
            "#\tартикул\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tналичие\tреклама\tссылка")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _search_row(n, p):
    price, rating = p.get("price") or {}, p.get("rating") or {}
    sale, base = price.get("salePrice"), price.get("basePrice")
    cells = (n, p.get("productId"), sale, base if base != sale else None, p.get("name"), rating.get("star"), rating.get("count"),
             _stock(p), "реклама" if p.get("adType") else None, p.get("slug"))
    return "\t".join("" if c is None else str(c) for c in cells)


def _stock(p):
    if p.get("soldOut"):
        return "нет в наличии"
    return ("предзаказ, " if p.get("isPreorder") else "") + (f"с {p['availabilityDate']}" if p.get("availabilityDate") else "")


def item(url_or_id, full=False):
    pid = product_id(url_or_id)
    if not pid:
        return f"нужен артикул или ссылка на товар М.Видео: {HOME}/products/<артикул>"
    url = f"{HOME}/products/{pid}"
    tab = tab_for("mvideo.ru")
    try:
        got = capture(tab, "mvideo", url, {"p": ["/bff/pdp/info", pid], "r": ["/bff/reviews/list", pid],
                                           "sum": ["/bff/handover-options/v2/summary"], "st": ["/bff/product/stores"],
                                           "h": ["/bff/handover-options/batch-list"]}, optional=("h",))
    finally:
        tab.close()
    info = (got.get("p") or {}).get("body")
    if not info:
        log.warning("mvideo item %s: no pdp/info answer", url)
        return BLOCKED
    return _card(info, got, pid, url, full)


def _card(info, got, pid, url, full):
    pd, price = info.get("productDetails") or {}, (info.get("productPrices") or {}).get("price") or {}
    lines = [pd.get("name") or "", url, f"артикул: {pid}", price_line(price.get("salePrice"), price.get("basePrice"))]
    lines += (["нет в наличии"] if pd.get("soldOut") else []) + _rating(got.get("r")) + _summary(got.get("sum")) + _handover(got.get("h"), pid) + _stores(got.get("st"))
    return "\n".join(lines + tail(_specs(pd), pd.get("images"), "mvideo_reviews")) + "\n\n" + description(pd.get("description"), full)


def _rating(d):
    rv = (d or {}).get("body")
    return [f"рейтинг: {rv.get('totalRating') or '—'}, отзывов {rv.get('total') or 0}"] if rv else []


def _specs(pd):
    return [f"{p.get('name')}: {p.get('value')}" + (f" {p['measure']}" if p.get("measure") else "")
            for g in (pd.get("properties") or {}).get("key") or [] for p in g.get("properties") or []]


def tail(specs, images, reviews_tool):
    """The card's last lines: specs, up to 10 photos, where the reviews are."""
    return ((["характеристики: " + "; ".join(specs)] if specs else [])
            + (["фото (shop_images): " + " ".join(photo(p) for p in images[:10])] if images else []) + [f"отзывы: {reviews_tool}"])


def description(markup, full):
    desc = text(markup)
    return desc if full else desc[:2500]


def _summary(d):
    s = (d or {}).get("body") or {}
    if not s.get("deliveryDate"):
        return []
    return [f"получить можно с {s['deliveryDate']}" + (", есть экспресс-доставка" if s.get("hasExpressDelivery") else "")]


def _handover(d, pid):
    """Ways and dates per offer; the page asks for them only when other sellers offer the same goods."""
    batch = ((d or {}).get("body") or {}).get("handoverBatchList") or []
    options = next((b.get("handoverOption") or [] for b in batch if str(b.get("productId")) == pid), [])
    return [f"получение ({CITY}): " + "; ".join(map(_option, options))] if options else []


def _option(o):
    cost = o.get("minPrice")
    return (f"{HANDOVER.get(o.get('handoverOption'), o.get('handoverOption'))} — с {o.get('availabilityDate')}"
            + (", бесплатно" if cost == 0 else f", от {cost} ₽" if cost else ""))


def _stores(d):
    stores = ((d or {}).get("body") or {}).get("stores") or []
    dates = sorted(s["availabilityDate"] for s in stores if s.get("availabilityDate"))
    return [f"самовывоз: в {len(stores)} магазинах" + (f", раньше всего {dates[0]}" if dates else "")] if stores else []


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=REVIEWS_PAGE):
    pid = product_id(id_or_url)
    if not pid:
        return "нужен артикул или ссылка на товар М.Видео"
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    offset, only = (page - 1) * REVIEWS_PAGE, "photos_count:gt:0" if with_media else ""
    api = HOME + "/bff/reviews/list?" + urllib.parse.urlencode(
        {"origin": "mvideo", "limit": REVIEWS_PAGE, "offset": offset, "filter": only, "sort": REVIEW_SORTS[sort], "productId": pid})
    tab = tab_for("mvideo.ru")
    try:
        # the reviews page asks for the first useful ones itself: the same request with our sort, filter and offset
        d = capture(tab, "mvideo", f"{HOME}/products/{pid}/reviews", {"r": ["/bff/reviews/list", pid]},
                    rewrite=("*/bff/reviews/list*", lambda u: api)).get("r")
    finally:
        tab.close()
    body = (d or {}).get("body")
    if body is None:
        log.warning("mvideo reviews %s: no reviews/list answer", pid)
        return BLOCKED
    head = reviews_head("М.Видео", pid, body.get("totalRating"), body.get("total"), body.get("ratingsStats"))
    return (head + f"страница {page} (по {REVIEWS_PAGE}), сортировка {sort}{', только с фото' if with_media else ''}; "
            f"фото с отзывов всего: {body.get('photosCount') or 0}\n" + review_rows(body.get("reviews"), limit))


def reviews_head(shop, pid, rating, total, stats):
    stars = " ".join(f"{n}★ {(stats or {}).get(f'rating{n}', 0)}" for n in range(5, 0, -1)) if stats else ""
    return f"{shop} · артикул {pid}: рейтинг {rating or '—'}, отзывов {total or 0}" + (f" · {stars}" if stars else "") + "\n"


def review_rows(reviews, limit):
    """The table of reviews, the same records on М.Видео and Эльдорадо."""
    rows = [_review_row(r) for r in (reviews or [])[:limit]]
    return "дата\t★\tполезно\tавтор\tтекст\tфото (shop_images)\n" + ("\n".join(rows) if rows else "(отзывов нет)")


def _review_row(r):
    pros, cons = f"+ {r['advantages']}" if r.get("advantages") else "", f"− {r['disadvantages']}" if r.get("disadvantages") else ""
    said, photos = " | ".join(p for p in (pros, cons, r.get("comment")) if p), " ".join(photo(p) for p in r.get("photoUrls") or [])
    day, likes, author = (r.get("createdAt") or "")[:10], r.get("likesCount") or "", r.get("authorName") or ""
    return f"{day}\t{r.get('rating')}\t{likes}\t{author}\t{text(said)}\t{photos}"
