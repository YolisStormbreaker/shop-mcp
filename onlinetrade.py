"""ОНЛАЙН ТРЕЙД.РУ (onlinetrade.ru): search, product card and reviews. Read only: no cart, bookmarks or login.

The site is server-rendered HTML in windows-1251, so a search query goes in the address in cp1251. Its pages fetch
no data of their own: we load the page (tab.goto) and read what it shows (tab.js). Every review of a product, and of
its other colours, is on the product page itself, so sorting and paging them is done here. Prices, stock and
delivery are for the city in the user's profile on the site. A product has two numbers: its «Код товара» (the end of
its link, which we use) and an inner id on its buttons. Links like /basket.html?add=<id> change the account: we only
ever go to addresses we build ourselves.
"""
import html
import math
import re
import urllib.parse

from cdp import tab_for
from shoplog import log

HOME = "https://www.onlinetrade.ru"
NAME = "ОНЛАЙН ТРЕЙД.РУ"
PAGE = 30
SORTS = {"popular": "views-desc", "price_asc": "price-asc", "price_desc": "price-desc", "new": "time-desc",
         "reviews": "reviews-desc"}      # ours -> its sort=; "reviews" is its «много мнений»
REVIEW_SORTS = ("useful", "new", "old", "high", "low")
BLOCKED = f"⚠️ {NAME} не отдал страницу (нет такого товара или проверка на бота?): shop-chrome show, открыть сайт, повторить."
NO_CODE = f"нужна ссылка на товар {NAME} или его код из onlinetrade_search"
NO_PRICE = f"{NAME} не фильтрует поиск по цене: повтори без price_min и price_max (sort=price_asc — от дешёвых)"
NO_MEDIA = f"{NAME} не прикрепляет фото к отзывам (фото покупателей — в галерее на странице товара): повтори без with_media"
REVIEWS_NOTE = "все отзывы — со страницы товара, сортирует и делит на страницы этот инструмент; фото к отзывам сайт не показывает"

SEARCH_JS = r"""(() => { const d = document, q = (e, s) => e.querySelector(s), t = (e, s) => (q(e, s) ? q(e, s).textContent : '').trim(),
  a = (e, s, k) => (q(e, s) ? q(e, s).getAttribute(k) : '') || '';
  return {listing: !!q(d, '#js__listingSort_ID') || /по запросу/i.test(t(d, 'h1')), count: t(d, '.paginator__count'),
    cards: [...d.querySelectorAll('.js__goods__items .indexGoods__item')].map(c => ({href: a(c, 'a.indexGoods__item__name', 'href'),
      name: t(c, '.indexGoods__item__name'), price: t(c, '.indexGoods__item__price .price'), stars: a(c, '.indexGoods__item__stars .starsSVG', 'title'),
      votes: t(c, '.indexGoods__item__stars'), marks: [...c.querySelectorAll('.marks .mark')].map(m => [m.className, m.textContent.trim()])}))} })()"""
# the card, its delivery and pickup tables (the tab «Доставка и самовывоз») and the reviews (tab «Отзывы»)
ITEM_JS = r"""(() => { const d = document, q = (e, s) => e ? e.querySelector(s) : null, t = (e, s) => (q(e, s) ? q(e, s).textContent : '').trim(),
  all = (e, s) => e ? [...e.querySelectorAll(s)] : [], a = (e, s, k) => (q(e, s) ? q(e, s).getAttribute(k) : '') || '',
  bare = x => x.textContent.replace(t(x, '.gray'), ''), pairs = (e, s) => all(e, s).map(x => [t(x, '.gray'), bare(x)]);
  return {code: String(window.itemcode || ''), name: t(d, 'h1'), url: location.href,
    price: a(d, '[itemprop=offers] [itemprop=price]', 'content'), old: t(d, '.catalog__displayedItem__oldPrice'),
    discount: t(d, '.productPage__offer .mark__discount'), avail: t(d, '.catalog__displayedItem__availabilityCount'),
    rating: a(d, '[itemprop=aggregateRating] [itemprop=ratingValue]', 'content'), votes: a(d, '[itemprop=aggregateRating] [itemprop=ratingCount]', 'content'),
    short: pairs(d, '.productPage__shortProperties .featureList__item'), specs: pairs(d, '#tabs_description .featureList__item'),
    text: (q(d, '#tabs_description .descriptionText_cover') || {}).innerHTML || '',
    photos: all(q(d, '.productPage__displayedItem__images'), 'a[href], img, meta[content]')
      .map(e => e.getAttribute('href') || e.getAttribute('data-src') || e.getAttribute('src') || e.getAttribute('content')),
    pickups: t(d, '#tabs_availability a[data-handlermode=pickup]'),
    rows: all(d, '#tabs_availability td:first-child').map(c => c.parentElement).filter(tr => tr.cells.length > 2).map(tr => [
      !!q(tr, '.pickupTable__location'), t(tr, '.pickupTable__location .semibold') || bare(tr.cells[0]), bare(tr.cells[1]), bare(tr.cells[2])]),
    tab: t(d, 'a[href="#tabs_feedbacks"] .gray'),
    reviews: all(q(d, '#tabs_feedbacks'), '.reviewlist__item').map(r => ({date: a(r, '[itemprop=datePublished]', 'content'),
      stars: a(r, '.starsSVG', 'title'), of: t(r, '.feedbacksHeader_toSimilarGoods a'), parts: pairs(r, '[itemprop=reviewBody] p'),
      plus: t(r, '.item_rating__plus'), minus: t(r, '.item_rating__minus')}))} })()"""


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _rub(s):
    return re.sub(r"\D", "", s or "")


def _stars(title):
    """The rating in a stars title: '5 звезд по 27 оценкам', 'Оценка: 3'; '' for 'Нет оценок'."""
    m = re.search(r"\d+(?:[.,]\d+)?", title or "")
    return m.group(0) if m else ""


def _code(s):
    """«Код товара» from a product link (…/<name>-<code>.html) or the bare code; None for anything else."""
    s = str(s or "").strip()
    m = re.match(r"(?:https?://)?(?:www\.)?(?:onlinetrade\.ru)?/catalogue/[^?#\s]*-(\d+)\.html(?:[?#]|$)", s) or re.fullmatch(r"(\d+)", s)
    return m.group(1) if m else None


def _photos(urls):
    """The product's pictures in their largest size (b), once each: the page has each in s, m and b."""
    big = (re.sub(r"/img/items/[sm]/", "/img/items/b/", u) for u in urls or [] if u and "/img/items/" in u)
    return list(dict.fromkeys(big))


def _load(tab, url):
    """goto url and wait for the new document: the reused tab still shows the previous page of the site."""
    old = tab.js("performance.timeOrigin")
    tab.goto(url, "onlinetrade", wait_js=f"performance.timeOrigin !== {old} && document.readyState === 'complete'")


def _read(url, js):
    tab = tab_for("onlinetrade.ru")
    try:
        _load(tab, url)
        return tab.js(js)
    finally:
        tab.close()


def search(query, price_min=None, price_max=None, sort="popular", page=1, limit=PAGE):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    if price_min or price_max:
        return NO_PRICE
    url = _search_url(query, sort, page)
    got = _read(url, SEARCH_JS)
    if not (got or {}).get("listing"):
        log.warning("onlinetrade search %s: no listing", url)
        return BLOCKED
    return _search_table(got, url, page, limit)


def _search_url(query, sort, page):
    # force_items: goods even when the query names a category (else the page lists only the categories)
    url = f"{HOME}/sitesearch.html?force_items=1&query=" + urllib.parse.quote_plus(query, encoding="cp1251", errors="replace")
    url += f"&sort={SORTS[sort]}" if sort != "popular" else ""
    return url + (f"&page={page - 1}" if page > 1 else "")     # the site counts pages from 0


def _search_table(got, url, page, limit):
    cards = got.get("cards") or []
    found = re.search(r"из\s+(\d+)", got.get("count") or "")
    rows = [_search_row(i + 1, c) for i, c in enumerate(cards[:limit])]
    head = (f"{NAME} · {found.group(1) if found else len(cards)} найдено · страница {page} (по {PAGE}) · {url}\n"
            f"ссылки относительно {HOME}; цены — для города из профиля на сайте; наличие, доставка и старая цена — в onlinetrade_item\n"
            "#\tкод\tцена ₽\tскидка\tназвание\tрейтинг\tоценок\tпометки\tссылка")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _search_row(n, c):
    href = c.get("href") or ""
    marks = c.get("marks") or []
    discount = "".join(text for cls, text in marks if "mark__discount" in cls).replace("-", "−")
    other = ", ".join(text for cls, text in marks if "mark__discount" not in cls)
    votes = (c.get("votes") or "").strip()
    return (f"{n}\t{_code(href) or ''}\t{_rub(c.get('price'))}\t{discount}\t{_text(c.get('name'))}\t{_stars(c.get('stars'))}\t"
            f"{votes if votes != '0' else ''}\t{other}\t{href}")


def _card_page(id_or_url):
    """(the code, the product page's data) — None data when the page is not that product's card."""
    code = _code(id_or_url)
    url = f"{HOME}/catalogue/x-c1/x/x-{code}.html"       # the site sends any such address to the card's own
    p = _read(url, ITEM_JS)
    if not p or p.get("code") != code:      # a block page, or the tab still holds another card
        log.warning("onlinetrade %s: no product card", url)
        return code, None
    return code, p


def item(url_or_id, full=False):
    if not _code(url_or_id):
        return NO_CODE
    code, p = _card_page(url_or_id)
    return _card(p, full) if p else BLOCKED


def _card(p, full):
    avail = _text(p.get("avail")) or "—"
    lines = [p.get("name", ""), (p.get("url") or "").split("?")[0], f"код товара: {p['code']}", _price(p), f"наличие: {avail}"]
    lines += _delivery(p.get("rows") or [], p.get("pickups"))
    lines.append(f"рейтинг {p.get('rating') or '—'}, оценок {p.get('votes') or 0}")
    text = _text(p.get("text"))
    return "\n".join(lines + _extras(p, full) + ["отзывы: onlinetrade_reviews", "\n" + (text if full else text[:2500])])


def _extras(p, full):
    """The specs line (the card's key ones, or all of them with full) and the photos line, each only when there is one."""
    specs = "; ".join(f"{_text(k).rstrip(':')}: {_text(v)}" for k, v in p.get("specs" if full else "short") or [])
    photos = _photos(p.get("photos"))
    return (["характеристики: " + specs] if specs else []) + (["фото (shop_images): " + " ".join(photos[:10])] if photos else [])


def _price(p):
    price, old = _rub(p.get("price")), _rub(p.get("old"))
    pct = (p.get("discount") or "").replace("-", "−")
    return f"цена: {price} ₽" + (f" (было {old}, {pct})" if old else "") if price else "цена: —"


def _delivery(rows, pickups):
    """'доставка: …' and 'самовывоз (N магазинов): …' lines from the card's tables; their first rows are what it shows."""
    say = lambda r: f"{_text(r[1]).rstrip(',')} — {_text(r[2])}, {_text(r[3])}"
    courier = "; ".join(say(r) for r in rows if not r[0])
    pickup = "; ".join(say(r) for r in rows if r[0])
    shops = re.search(r"\d+\s+\S+", pickups or "")
    return ([f"доставка: {courier}"] if courier else []) + ([f"самовывоз ({shops.group(0) if shops else 'пункты выдачи'}): {pickup}"] if pickup else [])


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    wrong = (not _code(id_or_url) and NO_CODE) or (sort not in REVIEW_SORTS and f"sort: одно из {', '.join(REVIEW_SORTS)}") or (with_media and NO_MEDIA)
    if wrong:
        return wrong
    code, p = _card_page(id_or_url)
    return _reviews_text(code, p, sort, page, limit) if p else BLOCKED


def _sorted(reviews, sort):
    """Every order is made here: the site's own is the top three by «+» votes, then the newest. Stable, so ties keep it."""
    keys = {"useful": lambda r: int(r.get("plus") or 0), "new": lambda r: r.get("date") or "", "old": lambda r: r.get("date") or ""}
    key = keys.get(sort, lambda r: _stars(r.get("stars")))
    return sorted(reviews, key=key, reverse=sort in ("useful", "new", "high"))


def _reviews_text(code, p, sort, page, limit):
    found = p.get("reviews") or []
    rows = [_review_row(r) for r in _sorted(found, sort)[(page - 1) * limit:page * limit]]
    count = int(_rub(p.get("tab")) or 0)
    short = f" (на странице только {len(found)})" if count > len(found) else ""
    pages = max(1, math.ceil(len(found) / limit))
    head = (f"{NAME} · товар {code}: рейтинг {p.get('rating') or '—'}, оценок {p.get('votes') or 0}, отзывов {max(count, len(found))}{short}\n"
            f"страница {page} из {pages} (по {limit}), сортировка {sort}; {REVIEWS_NOTE}\n"
            "дата\t★\tполезно\tдостоинства\tнедостатки\tтекст\tдругой вариант")
    return head + "\n" + ("\n".join(rows) if rows else "(отзывов нет)")


def _review_row(r):
    parts = {_text(k).rstrip(":"): _text(v) for k, v in r.get("parts") or []}
    plus, minus = r.get("plus") or "0", r.get("minus") or "0"
    votes = f"+{plus} −{minus}" if (plus, minus) != ("0", "0") else ""
    return (f"{r.get('date') or ''}\t{_stars(r.get('stars'))}\t{votes}\t{parts.get('Достоинства', '')}\t{parts.get('Недостатки', '')}\t"
            f"{parts.get('Комментарий', '')}\t{_text(r.get('of'))}")
