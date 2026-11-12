"""Ситилинк (citilink.ru): search, product card and reviews. Read only.

The page fetches its data by GraphQL POSTs to one address (/graphql/), so capture() gets many names on that
address and we pick the answers by what they hold. The card itself is in the page's __NEXT_DATA__.
Prices, stock and delivery are for the city in the user's profile on the site.
"""
import html
import re
import urllib.parse

from capture import capture
from cdp import tab_for
from shoplog import log

HOME = "https://www.citilink.ru"
PAGE = 36
# ours -> the site's ?sorting=<slug>_<direction>; its "opinions" are отзывы, its "reviews" обзоры
SORTS = {"relevance": "", "price_asc": "price_asc", "price_desc": "price_desc", "discount": "discount_desc",
         "rating": "rating_desc", "reviews": "opinions_desc"}
REVIEW_SORTS = {"useful": "HELPFUL", "new": "NEW", "old": "OLD", "high": "BEST", "low": "WORST"}
REVIEW_PAGE = 5     # the site's own page size, not settable from the address
BLOCKED = "⚠️ Ситилинк не отдал данные (проверка на бота?): shop-chrome show, открыть сайт, повторить."
NO_SLUG = "нужна ссылка на товар Ситилинка или его код из citilink_search"
GQL = 16            # more names than the 10-12 GraphQL answers a page gets
CARD_JS = "window.__NEXT_DATA__?.props?.initialState?.productPage?.productHeader?.payload?.productBase || null"


def _graphql(tab, url, need):
    """data of every /graphql/ answer the page got while loading url. capture fills the last names first: the
    first `need` answers are waited for, the rest get a few seconds more."""
    names = {f"g{i}": ["/graphql/"] for i in range(GQL)}
    got = capture(tab, "citilink", url, names, timeout=20, optional=list(names)[:GQL - need])
    return [d["data"] for d in got.values() if isinstance(d, dict) and isinstance(d.get("data"), dict)]


def _rub(s):
    return "" if not s or str(s) == "0" else str(s)       # the site writes no price as "" or "0"


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _slug(id_or_url):
    """The product's address part (<name>-<code>, or the bare code: the site reads the code off its end)."""
    s = str(id_or_url)
    m = re.match(r"\s*(?:https?://)?(?:www\.)?(?:citilink\.ru)?/product/([^/?#\s]+)", s) or re.fullmatch(r"\s*([A-Za-z]*\d[A-Za-z0-9]*)\s*", s)
    return m.group(1) if m else None


def _code(slug):
    return re.search(r"[A-Za-z0-9]+$", slug).group(0)


def _photos(images):
    """Each picture's largest size (sources go from the smallest). The card gives a list, search {"citilink": list}."""
    images = images.get("citilink") if isinstance(images, dict) else images
    return [i["sources"][-1]["url"] for i in images or [] if i.get("sources")]


def _pickup(delivery):
    days = sorted(d["deliveryTime"][:10] for d in ((delivery or {}).get("self") or {}).get("availabilityByDays") or [])
    return f"самовывоз с {days[0]}" if days else ""


def search(query, price_min=None, price_max=None, sort="relevance", page=1, limit=PAGE):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    url = _search_url(query, price_min, price_max, sort, page)
    tab = tab_for("citilink.ru")
    try:
        records = _records(_graphql(tab, url, 10))
    finally:
        tab.close()
    if not records:
        log.warning("citilink search %s: no fullSearchFilter answer", url)
        return BLOCKED
    return _search_table(records, url, page, limit)


def _search_url(query, price_min, price_max, sort, page):
    qs = {"text": query}
    if SORTS[sort]:
        qs["sorting"] = SORTS[sort]
    if price_min or price_max:
        qs["r"] = f"price_filter_group_id:{int(price_min or 0)}-{int(price_max or 10_000_000)}"
    if page > 1:
        qs["p"] = page
    return f"{HOME}/search/?" + urllib.parse.urlencode(qs)


def _records(answers):
    """The page's search answers in page order: it asks for the first 12 cards, then for the other 24."""
    records = [a["fullSearchFilter"]["record"] for a in answers if (a.get("fullSearchFilter") or {}).get("record")]
    return sorted(records, key=lambda r: (r.get("partialPageInfo") or {}).get("offset") or 0)


def _search_table(records, url, page, limit):
    products = [p for r in records for p in r.get("products") or [] if p]
    found = (records[0].get("pageInfo") or {}).get("totalItems") or 0
    rows = [_search_row(i + 1, p) for i, p in enumerate(products[:limit])]
    head = (f"Ситилинк · {found} найдено · страница {page} (по {PAGE}) · {url}\n" + _partial(records, products, found, page) +
            f"ссылки относительно {HOME}; цены и наличие — для города из профиля на сайте\n"
            "#\tкод\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tналичие\tпометки\tссылка")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _partial(records, products, found, page):
    """A note when the page's second answer (cards 13-36) was not caught: else the table is silently short."""
    short = len(records) < 2 and (page - 1) * PAGE + len(products) < found
    return f"⚠️ пришла не вся страница: {len(products)} карточек из {PAGE}, повтори позже\n" if short else ""


def _search_row(n, p):
    price = p.get("price") or {}
    now, old = _rub(price.get("current")), _rub(price.get("old"))
    rating = p.get("rating") if float(p.get("rating") or 0) else ""
    return (f"{n}\t{p.get('id')}\t{now}\t{old if old != now else ''}\t{p.get('name', '')}\t{rating}\t"
            f"{(p.get('counters') or {}).get('opinions') or ''}\t{_stock(p)}\t{_marks(p)}\t/product/{p.get('slug')}-{p.get('id')}/")


def _stock(p):
    if not p.get("isAvailable"):
        return "нет в наличии"
    stores = _rub((p.get("stock") or {}).get("countInStores"))
    return ", ".join(s for s in (f"в магазинах сегодня: {stores}" if stores else "", _pickup(p.get("delivery"))) if s)


def _marks(p):
    club = _rub((p.get("price") or {}).get("club"))
    marks = [x.get("title") for x in p.get("labels") or [] if x.get("type") != "INSTALLMENT"]
    return ", ".join(marks + ([f"клубная цена {club}"] if club else []) + (["из-за рубежа"] if p.get("isCrossBorder") else []))


def item(url_or_id, full=False):
    slug = _slug(url_or_id)
    if not slug:
        return NO_SLUG
    url = f"{HOME}/product/{slug}/"
    tab = tab_for("citilink.ru")
    try:
        answers = _graphql(tab, url, 8)
        p = tab.js(CARD_JS)
    finally:
        tab.close()
    if not p or str(p.get("id")) != _code(slug):       # the tab may still hold the previous card
        log.warning("citilink item %s: no product card", url)
        return BLOCKED
    return _card(p, _delivery(answers), full)


def _delivery(answers):
    d = next((a["product"]["delivery"] for a in answers if (a.get("product") or {}).get("delivery")), {})
    courier = [_courier(v) for v in (d.get("courier") or {}).get("variants") or []]
    pickup = _pickup(d).replace("самовывоз с", "самовывоз — с")
    return ([pickup] if pickup else []) + courier


def _courier(v):
    return f"курьер — {v.get('deliveryTime', '')[:10]}, " + (f"{v['price']} ₽" if _rub(v.get("price")) else "бесплатно")


def _card(p, delivery, full):
    lines = [p.get("name", ""), f"{HOME}/product/{p.get('slug')}-{p.get('id')}/", f"код товара: {p.get('id')}", _price(p.get("price") or {}),
             _availability(p)]
    lines += ["получение: " + "; ".join(delivery)] if delivery else []
    lines.append(f"рейтинг {p.get('rating') or '—'}, отзывов {(p.get('counters') or {}).get('opinions') or 0}")
    lines += _specs(p.get("properties")) + [_variants(g) for g in p.get("variants") or []]
    photos = _photos(p.get("images"))
    lines += ["фото (shop_images): " + " ".join(photos[:10])] if photos else []
    text = _text(p.get("description"))
    return "\n".join(lines + ["отзывы: citilink_reviews", "\n" + (text if full else text[:2500])])


def _specs(properties):
    """The card's key specs (the full list is on its «Характеристики» tab) as one line, or none."""
    specs = "; ".join(f"{x.get('name')}: {x.get('value')} {x.get('measure') or ''}".strip() for x in properties or [])
    return ["характеристики: " + specs] if specs else []


def _price(price):
    old = _rub(price.get("old"))
    club = _rub(price.get("club"))
    pct = (price.get("discount") or {}).get("percent")
    return (f"цена: {price.get('current')} ₽" + (f" (было {old}, −{pct}%)" if old else "")
            + (f", клубная {club} ₽" if club else ""))


def _availability(p):
    stock = _rub(p.get("maxCountInStock"))
    return "наличие: " + (("есть" + (f", на складе {stock}" if stock else "")) if p.get("isAvailable") else "нет в наличии")


def _variants(group):
    """e.g. 'Цвет: белый (код 100); чёрный (код 101, нет в наличии)'"""
    return f"{group.get('name')}: " + "; ".join(
        f"{v.get('label')} (код {(v.get('product') or {}).get('id')}" + ("" if (v.get("product") or {}).get("isAvailable") else ", нет в наличии") + ")"
        for v in group.get("variants") or [])


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    slug = _slug(id_or_url)
    wrong = _reviews_wrong(slug, sort, with_media)
    if wrong:
        return wrong
    url = _reviews_url(slug, sort, page)
    tab = tab_for("citilink.ru")
    try:
        found = [a["product"]["opinions"] for a in _graphql(tab, url, 10) if (a.get("product") or {}).get("opinions")]
    finally:
        tab.close()
    if not found:
        log.warning("citilink reviews %s: no opinions answer", url)
        return BLOCKED
    return _reviews_text(found, _code(slug), sort, page, limit)


def _reviews_wrong(slug, sort, with_media):
    if not slug:
        return NO_SLUG
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    if with_media:
        return "Ситилинк не отбирает отзывы с фото и не отдаёт их фото: повтори без with_media"
    return None


def _reviews_url(slug, sort, page):
    qs = ({"sort": REVIEW_SORTS[sort]} if sort != "useful" else {}) | ({"page": page} if page > 1 else {})
    return f"{HOME}/product/{slug}/otzyvy/" + ("?" + urllib.parse.urlencode(qs) if qs else "")


def _reviews_text(found, code, sort, page, limit):
    """found: the page's two answers, the summary (rating, stars) and the page of reviews, in either order."""
    summary = next((o["payload"]["summary"] for o in found if (o.get("payload") or {}).get("summary")), {})
    listing = next((o for o in found if "items" in (o.get("payload") or {})), {"payload": {}})
    rows = [_review_row(r, code) for r in (listing["payload"].get("items") or [])[:limit]]
    return _reviews_head(summary, listing, code, sort, page) + "\n" + ("\n".join(rows) if rows else "(отзывов нет)")


def _reviews_head(summary, listing, code, sort, page):
    info = listing.get("pageInfo") or {}
    count = _review_count(listing["payload"].get("totalOpinionsForProduct"), info.get("totalItems") or 0)
    stars = " ".join(f"{x['rating']}★ {x['percentage']}%" for x in summary.get("ratingCounters") or [] if x.get("percentage"))
    return (f"Ситилинк · товар {code}: рейтинг {summary.get('rating') or '—'}, отзывов {count}" + (f" · {stars}" if stars else "") + "\n"
            f"страница {page} из {info.get('totalPages') or 1} (по {REVIEW_PAGE}), сортировка {sort}; фото в отзывах сайт не отдаёт\n"
            "дата\t★\tполезно\tавтор\tтекст\tисточник\tдругой вариант")


def _review_count(own, total):
    """The pages hold the reviews of every variant of the product; the site counts this variant's own apart."""
    return f"{total or own or 0}" + (f" (этого варианта {own})" if total and own is not None and own != total else "")


def _review_row(r, code):
    return (f"{(r.get('displayedDate') or '')[:10]}\t{r.get('rating')}\t{_likes(r)}\t{r.get('authorNickname') or ''}\t"
            f"{_text(_review_text(r))}\t{(r.get('source') or {}).get('description') or ''}\t{_other_variant(r, code)}")


def _likes(r):
    return (((r.get("voteInfo") or {}).get("info") or {}).get("counters") or {}).get("likes") or ""


def _review_text(r):
    return " | ".join(s for s in (f"+ {r['pros']}" if r.get("pros") else "", f"− {r['cons']}" if r.get("cons") else "", r.get("text") or "") if s)


def _other_variant(r, code):
    """Reviews of the product's other colors and sizes come too («Все отзывы» on the site): their name."""
    product = r.get("product") or {}
    return product.get("shortName", "") if str(product.get("id")) != code else ""
