"""Dr.Head (doctorhead.ru): search, product card and reviews. Read only: no cart, favorites or login.

A Bitrix site whose pages come rendered from the server: the search list, the card (its stock by shop and the
delivery dates for the city chosen on the site) and the card's reviews, 4 a page (?PAGEN_PROMO=N), are read from
the page's DOM after one load. The site has no review sort, keeps no pros and cons apart, and shows its buyers'
photos as one set for the product. Its price filter's address is made by its server (an x-filter-url header) and
plain query parameters are ignored, so search has no price filter.
"""
import json
import re
import urllib.parse

from cdp import tab_for
from shoplog import log

HOME = "https://doctorhead.ru"
SITE = "doctorhead"
PAGE = 30
REVIEW_PAGE = 4
# ours -> the site's &sort=<field>&order=<direction>; its default order is «По релевантности»
SORTS = {"relevance": None, "price_asc": ("price", "asc"), "price_desc": ("price", "desc"), "rating": ("rating", "desc"),
         "new": ("new", "desc"), "discount": ("discount_percent", "desc"), "discount_rub": ("discount", "desc")}
AVAILABILITY = {"InStock": "в наличии", "OutOfStock": "нет в наличии", "PreOrder": "на заказ"}
BLOCKED = "⚠️ Dr.Head не отдал страницу (проверка на бота?): shop-chrome show, открыть doctorhead.ru, повторить."
NO_ID = "⚠️ нужна ссылка на товар Dr.Head или его id из doctorhead_search (часть ссылки после /product/)"
NO_PRICE_FILTER = ("⚠️ фильтра по цене через адрес у Dr.Head нет (его адрес строит сервер сайта): "
                   "повтори без price_min/price_max, с sort=price_asc или price_desc")
# loaded, and the composite's late blocks (stock by shop) in: on a cached page they come by a ?bxrand request after load
READY = ("document.readyState === 'complete' && (!document.querySelector('[id^=\"bxdynamic_\"]') "
         "|| !!(window.BX && BX.frameCache && BX.frameCache.frameDataInserted))")

SEARCH_JS = r"""(() => { const q = (e, s) => e.querySelector(s), t = (e, s) => (q(e, s) || {}).textContent || '';
  const tab = q(document, '.tabs-header__item.is-active');      // «Товары 1374»; with nothing found, no number
  return {count: tab ? t(tab, 'sup') : null, cards: [...document.querySelectorAll('#catalog-list .catalog-list__item')].map(c => ({
    id: c.dataset.id, href: (q(c, 'a.product-descr__link') || {getAttribute: () => ''}).getAttribute('href'),
    name: t(c, '.product-descr__title').trim(), price: (q(c, '.js-product-price') || {dataset: {}}).dataset.price,
    old: t(c, '.js-product-price .old .val'), rating: t(c, '.product-card-rating__value'),
    reviews: t(c, '.product-card-rating__reviews'), status: t(c, '.product-status')}))} })()"""
# the product's ld+json and what only its DOM shows: old price, stock by shop, delivery, specs, colors
LD_JS = r"""[...document.querySelectorAll('script[type="application/ld+json"]')].map(s => { try { return JSON.parse(s.textContent) } catch (e) { return null } })
    .find(x => x && x['@type'] === 'Product') || null"""
ITEM_JS = r"""(() => { const q = s => document.querySelector(s), t = s => (q(s) || {}).textContent || '', all = s => [...document.querySelectorAll(s)];
  const txt = e => e ? e.textContent.replace(/\s+/g, ' ').trim() : '';
  const own = e => e ? [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ') : '';   // without its tooltip
  return {path: location.pathname, title: document.title, ld: """ + LD_JS + """, code: t('[data-product-code]'),
    price: (q('.product-price-block .js-product-price') || {dataset: {}}).dataset.price, old: t('.product-price-block .old .val'),
    sale: t('.product-price-block .old .sale'), storesHead: t('.availability-stores__text'),
    stores: all('.stock-list .stock').map(e => ({title: txt(e.querySelector('.stock__title')), status: txt(e.querySelector('.stock__subtitle')),
                                                 level: txt(e.querySelector('.stock__status-text'))})),
    delivery: all('.delivery-method').filter(e => getComputedStyle(e).display !== 'none')
      .map(e => [own(e.querySelector('.delivery-method__title')), txt(e.querySelector('.delivery-method__cost'))]),
    crumbs: all('.breadcrumbs-list__item [itemprop=name]').map(txt),
    colors: all('.product-sidebar-color input[name=color]').map(e => ({url: e.dataset.url, on: e.checked,
      name: (e.parentElement.querySelector('[title]') || {}).title || ''})),
    specs: all('.characteristic-list .characteristic').map(e => [txt(e.querySelector('dt')), txt(e.querySelector('dd'))]),
    features: all('.key-feature-list li').map(txt), description: (q('#product-description .info-block-content') || {}).innerText || ''} })()"""
REVIEWS_JS = r"""(() => { const all = (e, s) => [...e.querySelectorAll(s)], t = (e, s) => (e.querySelector(s) || {}).textContent || '';
  return {path: location.pathname, title: document.title, ld: """ + LD_JS + """,
    pages: all(document, '#product-review .pagination-list__item').map(e => e.textContent),
    photos: all(document, '.product-reviews-carousel__item img').map(e => e.dataset.src || e.getAttribute('src')),
    reviews: all(document, '.product-reviews-list__item').map(r => ({author: t(r, '.product-review-author__name'), date: t(r, '.date'),
      stars: (r.querySelector('.rating') || {dataset: {}}).dataset.value, text: (r.querySelector('.product-review-text__inner') || {}).innerText || ''}))} })()"""


def _text(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _rub(s):
    """Rubles as a whole number: '24990.0', ' 29 990 руб. ' -> 24990, 29990; nothing -> None."""
    digits = re.sub(r"\D", "", str(s or "").split(".")[0])
    return int(digits) if digits else None


def _slug(id_or_url):
    """The product's address part after /product/ (its id here), or None."""
    s = str(id_or_url).strip()
    m = re.match(r"(?:https?://(?:www\.)?doctorhead\.ru)?/product/([\w-]+)", s) or re.fullmatch(r"([a-z0-9_-]*[a-z_-][a-z0-9_-]*)", s)
    return m.group(1) if m else None


def _load(tab, url, extract):
    """goto url and read it: the reused tab still shows the previous page until the new document is in."""
    old = tab.js("performance.timeOrigin")
    tab.goto(url, SITE, wait_js=f"performance.timeOrigin !== {json.dumps(old)} && ({READY})")
    return tab.js(extract)


def _read(url, extract):
    tab = tab_for("doctorhead.ru")
    try:
        return _load(tab, url, extract)
    finally:
        tab.close()


def search(query, price_min=None, price_max=None, sort="relevance", page=1, limit=PAGE):
    if sort not in SORTS:
        return f"⚠️ sort: одно из {', '.join(SORTS)}"
    if price_min or price_max:
        return NO_PRICE_FILTER
    url = _search_url(query, sort, page)
    r = _read(url, SEARCH_JS)
    if not r or r["count"] is None:              # no «Товары N» tab: not the search page
        log.warning("doctorhead search %s: no search page", url)
        return BLOCKED
    rows = [_search_row(i + 1, c) for i, c in enumerate(r["cards"][:limit])]
    return (f"Dr.Head · {_rub(r['count']) or 0} найдено · страница {page} (по {PAGE}) · {url}\n"
            f"ссылки относительно {HOME}; цены и наличие — для города, выбранного на сайте\n"
            "#\tid\tкод\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tналичие\tссылка\n" + ("\n".join(rows) if rows else "(пусто)"))


def _search_url(query, sort, page):
    qs = {"q": query}
    if SORTS[sort]:
        qs["sort"], qs["order"] = SORTS[sort]
    if page > 1:
        qs["PAGEN_1"] = page
    return f"{HOME}/search/?" + urllib.parse.urlencode(qs)


def _search_row(n, c):
    reviews = _rub(c["reviews"]) or ""        # the site writes no reviews as «0 отзывов»
    cells = (n, _slug(c["href"]), c["id"], _rub(c["price"]), _rub(c["old"]), _text(c["name"]), _rating(c["rating"]),
             reviews, _text(c["status"]), c["href"])
    return "\t".join("" if x is None else str(x) for x in cells)


def _rating(s):
    s = _text(s)
    return s if s and float(s) else ""      # the site writes no rating as 0.0


def _missing(r, url):
    """⚠️ text when the page has no product: a 404, or else a page we don't know (a bot check?)."""
    if r and re.search(r"404|не найден", r["title"]):
        return f"⚠️ Dr.Head: такого товара нет (404): {url}"
    log.warning("doctorhead %s: no product on the page", url)
    return BLOCKED


def item(url_or_id, full=False):
    slug = _slug(url_or_id)
    if not slug:
        return NO_ID
    url = f"{HOME}/product/{slug}/"
    p = _read(url, ITEM_JS)
    if not p or not p["ld"]:
        return _missing(p, url)
    return _card(p, slug, full)


def _card(p, slug, full):
    ld = p["ld"]
    code = _text(p["code"])
    stock = "наличие: " + _stock(p)
    delivery = "; ".join(_text(f"{a} {b}") for a, b in p["delivery"])
    lines = [ld.get("name", ""), HOME + p["path"], f"id: {slug}" + (f" · код товара: {code}" if code else ""), _price(p),
             stock, *_line("получение: ", delivery)]
    rating = ld.get("aggregateRating") or {}
    lines.append(f"рейтинг {rating.get('ratingValue') or '—'}, отзывов {rating.get('reviewCount') or 0}")
    text = (f"Особенности: {'; '.join(p['features'])}\n" if p["features"] else "") + p["description"]
    return "\n".join(lines + _about(p, ld) + ["отзывы: doctorhead_reviews", "\n" + (text if full else text[:2500])])


def _about(p, ld):
    """The card's lines that it may lack: its section, colors, specs, photos."""
    return (_line("раздел: ", " / ".join(c for c in p["crumbs"][1:] if c != ld.get("name")))     # [0] is «Главная»
            + _line("цвета: ", "; ".join(_color(c) for c in p["colors"]))
            + _line("характеристики: ", "; ".join(f"{_text(a)}: {_text(b)}" for a, b in p["specs"] if _text(b)))
            + _line("фото (shop_images): ", " ".join((ld.get("image") or [])[:10])))


def _color(c):
    """'белый /product/…/', or the card's own; a two-tone swatch has no name, only its link."""
    return " ".join(x for x in (c["name"], "(эта карточка)" if c["on"] else c["url"]) if x)


def _line(label, value):
    return [label + value] if value else []


def _price(p):
    now, old = _rub(p["price"]), _rub(p["old"])
    sale = _text(p["sale"]).replace("-", "−")
    return f"цена: {now or '—'} ₽" + (f" (было {old}, {sale})" if old else "")


def _stock(p):
    """The card's stock by shop, or the ld+json's availability when the card shows none."""
    shops = "; ".join(_text(s["title"]) + ": " + ", ".join(x for x in (s["status"], s["level"]) if x) for s in p["stores"])
    if shops:
        return f"{_text(p['storesHead'])} — {shops}"
    tail = ((p["ld"].get("offers") or {}).get("availability") or "").rsplit("/", 1)[-1]
    return AVAILABILITY.get(tail, tail or "—")


def reviews(id_or_url, sort="new", with_media=False, page=1, limit=20):
    slug = _slug(id_or_url)
    if not slug:
        return NO_ID
    if sort != "new":
        return "⚠️ Dr.Head показывает отзывы только от новых к старым: sort=new"
    url = f"{HOME}/product/{slug}/"
    r = _read(url + (f"?PAGEN_PROMO={page}" if page > 1 else ""), REVIEWS_JS)
    if not r or not r["ld"]:
        return _missing(r, url)
    rows = ["\t".join((_text(x["date"]), x["stars"] or "", _text(x["author"]), _text(x["text"]))) for x in r["reviews"][:limit]]
    return _reviews_head(r, slug, page, with_media) + "дата\t★\tавтор\tтекст\n" + ("\n".join(rows) if rows else "(отзывов нет)")


def _reviews_head(r, slug, page, with_media):
    rating = r["ld"].get("aggregateRating") or {}
    pages = max([n for n in map(_rub, r["pages"]) if n] or [1])     # the list also holds «Назад» and «Далее»
    photos = " ".join(HOME + x for x in dict.fromkeys(r["photos"]))     # the carousel repeats its slides
    return (f"Dr.Head · товар {slug}: рейтинг {rating.get('ratingValue') or '—'}, отзывов {rating.get('reviewCount') or 0}\n"
            f"страница {page} из {pages} (по {REVIEW_PAGE}), от новых к старым — другой сортировки у сайта нет; "
            "достоинства и недостатки сайт отдельно не ведёт\n"
            + ("отзывы с фото сайт не отбирает: фото покупателей он показывает одним списком к товару\n" if with_media else "")
            + (f"фото покупателей к товару (shop_images): {photos}\n" if photos else ""))
