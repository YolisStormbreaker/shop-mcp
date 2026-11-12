"""Технопарк (technopark.ru): search, product card and reviews. Read only.

A Nuxt site behind Qrator. Search results are rendered on the server into window.__NUXT__.data; the card is there
too, but its delivery terms and its reviews come by GraphQL POSTs to one address (/graphql/), so capture() takes
many names on that address and we pick the answers by what they hold. A product opens only by its address (slug),
not by its code. The next pages and the other sort of reviews have no address of their own: the page's own reviews
block loads them, by one GraphQL call that capture() catches. Prices, stock and delivery are for the city in the
user's profile on the site. Every tab.js picks named fields: __NUXT__ also holds the visitor's profile and location.
"""
import html
import math
import re
import urllib.parse

from capture import capture
from cdp import tab_for
from shoplog import log

HOME = "https://www.technopark.ru"
PAGE = 24
REVIEW_PAGE = 10    # the reviews block's own page size
# ours -> the site's ?order=<field>&dir=<direction>; no order means its default, by popularity
SORTS = {"relevance": None, "price_asc": ("price", "asc"), "price_desc": ("price", "desc"), "rating": ("rating", "desc")}
REVIEW_SORTS = {"useful": "POPULARITY", "new": "DATE"}
BLOCKED = ("⚠️ Технопарк не отдал данные страницы (нет такого товара, ссылка не на товар или проверка на бота?): "
           "проверь ссылку; если она верна — shop-chrome show, открыть сайт, повторить.")
NO_SLUG = ("нужна ссылка на товар Технопарка из technopark_search (или её часть вида naushniki-...): "
           "по одному коду сайт товар не открывает")
NO_OTHER_PAGE = ("⚠️ страница отзывов Технопарка не загрузила другую страницу или сортировку (сайт изменился?): "
                 "доступна страница 1 с sort=useful")
GQL = 12            # more names than the 9-10 GraphQL answers a card page gets
FRESH = "!window.__shopStale && !!window.__NUXT__?.data"
SEARCH_JS = ("(d => d ? {query: d.query, currentPage: d.currentPage, total: d.pagination?.total, products: d.products} : null)"
             "((window.__NUXT__?.data || []).find(d => d && 'products' in d))")
ITEM_JS = """(() => { const data = window.__NUXT__?.data || [], p = data.find(d => d?.product)?.product;
  return p ? {id: p.id, slug: p.slug, name: p.name?.full, price: p.price, status: p.status?.name, rating: p.rating?.average,
    reviews: p.reviews?.total, short: p.specifications?.short, gallery: (p.media?.gallery || []).map(g => (g.large || g.medium)?.src),
    description: data.find(d => d && 'description' in d)?.description} : null })()"""
# the reviews block is a <script setup> component: its state and loadReviews(page, append) are in _setupState
REVIEWS_JS = ("(() => {{ const find = vm => vm._setupState?.loadReviews ? vm._setupState : vm.$children.reduce((f, c) => f || find(c), null);"
              " const s = find(window.$nuxt.$root); s.selectedSortOption.value = {{field: \"{field}\", order: \"DESC\"}};"
              " s.loadReviews({page}, false) }})()")


def _graphql(tab, url, need, total=GQL, js=None):
    """data of every /graphql/ answer the page got while loading url (or after js). capture fills the last names first:
    the first `need` answers are waited for, the rest get a few seconds more."""
    names = {f"g{i}": ["/graphql/"] for i in range(total)}
    got = capture(tab, "technopark", url, names, timeout=20, js=js, optional=list(names)[:total - need])
    return [d["data"] for d in got.values() if isinstance(d, dict) and isinstance(d.get("data"), dict)]


def _text(s):
    s = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _slug(id_or_url):
    """The product's address (its only key on the site): from a link to it or one of its tabs, or the address itself."""
    m = re.fullmatch(r"\s*(?:(?:https?://)?(?:www\.)?technopark\.ru)?/?([a-z0-9]+(?:-[a-z0-9]+)+)(?:[/?#].*)?\s*", str(id_or_url))
    return m.group(1) if m else None


def _prices(price):
    """(price, crossed-out price or None) as the page shows them."""
    price = price or {}
    now = price.get("marketing") or price.get("default") or price.get("old")
    before = price.get("old") or price.get("default")
    return now, (before if before != now else None)


def search(query, price_min=None, price_max=None, sort="relevance", page=1, limit=PAGE):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    url = _search_url(query, price_min, price_max, sort, page)
    tab = tab_for("technopark.ru")
    try:
        tab.js("window.__shopStale = true")     # a new document drops it, so the previous page's data is never read
        tab.goto(url, "technopark", wait_js=FRESH)
        d = tab.js(SEARCH_JS)
    finally:
        tab.close()
    if not d or d.get("query") != query or d.get("currentPage") != page:
        log.warning("technopark search %s: no search data", url)
        return BLOCKED
    return _search_table(d, url, page, limit)


def _search_url(query, price_min, price_max, sort, page):
    qs = {"q": query}
    if SORTS[sort]:
        qs["order"], qs["dir"] = SORTS[sort]
    if price_min or price_max:      # both bounds: the site's own links always carry both
        qs["filter_Цена_min"] = int(price_min or 0)
        qs["filter_Цена_max"] = int(price_max or 10_000_000)
    if page > 1:
        qs["p"] = page
    return f"{HOME}/search/?" + urllib.parse.urlencode(qs)


def _search_table(d, url, page, limit):
    products = d.get("products") or []
    rows = [_search_row(i + 1, p) for i, p in enumerate(products[:limit])]
    head = (f"Технопарк · {d.get('total') or len(products)} найдено · страница {page} (по {PAGE}) · {url}\n"
            f"ссылки относительно {HOME}; цены и наличие — для города из профиля на сайте; "
            "technopark_item и technopark_reviews берут ссылку, не код\n"
            "#\tкод\tцена ₽\tбез скидки\tназвание\tрейтинг\tналичие\tссылка")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _search_row(n, p):
    now, before = _prices(p.get("price"))
    return (f"{n}\t{p.get('id')}\t{now or ''}\t{before or ''}\t{(p.get('name') or {}).get('full', '')}\t"
            f"{(p.get('rating') or {}).get('average') or ''}\t{(p.get('status') or {}).get('name', '')}\t/{p.get('slug')}/")


def item(url_or_id, full=False):
    slug = _slug(url_or_id)
    if not slug:
        return NO_SLUG
    url = f"{HOME}/{slug}/"
    tab = tab_for("technopark.ru")
    try:
        answers = _graphql(tab, url, 6)
        p = tab.js(ITEM_JS)
    finally:
        tab.close()
    if not p or p.get("slug") != slug:       # the tab may still hold the previous card
        log.warning("technopark item %s: no product card", url)
        return BLOCKED
    return _card(p, _logistics(answers), full)


def _logistics(answers):
    """The delivery answer's terms ({} when it has none), or None when that answer was not caught."""
    return next(((a["productV2"]["logistics"] or {}) for a in answers if "logistics" in (a.get("productV2") or {})), None)


def _card(p, logistics, full):
    status = p.get("status") or "—"
    lines = [p.get("name", ""), f"{HOME}/{p.get('slug')}/", f"код товара: {p.get('id')}", _price(p.get("price")), f"наличие: {status}"]
    lines += _delivery(logistics)
    lines.append(f"рейтинг {p.get('rating') or '—'}, отзывов {p.get('reviews') or 0}")
    text = _text(p.get("description"))
    return "\n".join(lines + _specs_and_photos(p) + ["отзывы: technopark_reviews", "\n" + (text if full else text[:2500])])


def _specs_and_photos(p):
    specs = "; ".join(f"{x.get('name')}: {x.get('value')}" for x in p.get("short") or [])
    photos = [u for u in p.get("gallery") or [] if u]
    return (["характеристики: " + specs] if specs else []) + (["фото (shop_images): " + " ".join(photos[:10])] if photos else [])


def _price(price):
    now, before = _prices(price)
    if not now:
        return "цена: не указана"
    return f"цена: {now} ₽" + (f" (было {before}, −{round((before - now) * 100 / before)}%)" if before else "")


def _delivery(logistics):
    if logistics is None:
        return ["получение: сроки не пришли, повтори позже"]
    ways = (("доставка", logistics.get("delivery")), ("самовывоз", logistics.get("pickup")))
    return [f"{label}: " + "; ".join(map(_way, items)) for label, items in ways if items]


def _way(w):
    return f"{w.get('name')} — {(w.get('date') or '')[:10]}, " + (f"{w['price']} ₽" if w.get("price") else "бесплатно")


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    slug = _slug(id_or_url)
    wrong = _reviews_wrong(slug, sort, with_media)
    if wrong:
        return wrong
    url = f"{HOME}/{slug}/otzyvy/"
    tab = tab_for("technopark.ru")
    try:
        got = _listing(_graphql(tab, url, 6))
        other = bool(got) and (page > 1 or sort != "useful")
        if other:   # Apollo answers page 1 / useful from its cache: only another page or sort goes to the site
            got = _listing(_graphql(tab, None, 1, total=3, js=_reviews_js(sort, page)))
    finally:
        tab.close()
    if not got:
        return _reviews_failed(url, other, page, sort)
    return _reviews_text(got, sort, page, limit)


def _reviews_failed(url, other, page, sort):
    if other:
        log.warning("technopark reviews %s: no answer to page %s, sort %s", url, page, sort)
        return NO_OTHER_PAGE
    log.warning("technopark reviews %s: no reviews answer", url)
    return BLOCKED


def _reviews_wrong(slug, sort, with_media):
    if not slug:
        return NO_SLUG
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    if with_media:
        return "Технопарк не отбирает отзывы с фото и не отдаёт их фото: повтори без with_media"
    return None


def _reviews_js(sort, page):
    return REVIEWS_JS.format(field=REVIEW_SORTS[sort], page=int(page))


def _listing(answers):
    """The productV2 of the answer with a page of reviews (another answer has the same counts and no list)."""
    return next((a["productV2"] for a in answers if "list" in ((a.get("productV2") or {}).get("reviews") or {})), None)


def _reviews_text(p, sort, page, limit):
    rows = [_review_row(r, p.get("id")) for r in (p["reviews"]["list"] or {}).get("data") or []][:limit]
    return _reviews_head(p, sort, page) + "\n" + ("\n".join(rows) if rows else "(отзывов нет)")


def _reviews_head(p, sort, page):
    rating = p.get("rating") or {}
    counts = rating.get("total") or {}
    total = p["reviews"].get("total") or 0
    liked = p["reviews"].get("totalRecommendations")
    stars = ", ".join(f"{n}★ {counts[f'value{n}']}" for n in range(5, 0, -1) if counts.get(f"value{n}"))
    return (f"Технопарк · товар {p.get('id')}: рейтинг {rating.get('average') or '—'}, отзывов {total}"
            + (f", рекомендуют {liked}" if liked else "") + (f" · {stars}" if stars else "") + "\n"
            f"страница {page} из {max(1, math.ceil(total / REVIEW_PAGE))} (по {REVIEW_PAGE}), сортировка {sort}; "
            "фото в отзывах сайт не отдаёт; счёт и список — по всем вариантам товара (столбец «другой вариант»)\n"
            "дата\t★\tполезно\tавтор\tтекст\tпометки\tдругой вариант")


def _review_row(r, pid):
    product = r.get("product") or {}
    return (f"{(r.get('date') or '')[:10]}\t{r.get('rating')}\t{r.get('likes') or ''}\t{(r.get('userName') or '').strip()}\t"
            f"{_review_text(r)}\t{_marks(r)}\t{product.get('slug', '') if product.get('id') != pid else ''}")


def _review_text(r):
    parts = (f"+ {r['pros']}" if r.get("pros") else "", f"− {r['cons']}" if r.get("cons") else "", r.get("comment") or "")
    return _text(" | ".join(s for s in parts if s))


def _marks(r):
    marks = [("куплен в Технопарке", r.get("wasBoughtInTechnopark")), ("рекомендует", r.get("isRecommendation")),
             ("отзыв партнёра", r.get("isPartnerReview")), (f"срок использования: {r.get('period')}", r.get("period"))]
    return ", ".join(m for m, on in marks if on)
