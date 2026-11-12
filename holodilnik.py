"""Холодильник.ру (holodilnik.ru): search, product card and reviews. Read only.

Every page is server-rendered HTML, with no JSON of its own to take: the search list, the card (with its delivery
dates, microdata and specs) and the reviews pages (/<product>/comments/) are read from the DOM after a page load.
Product addresses carry no id: a bare code («Код» on the card) is found by the site's search first, one load more.
Prices, stock and delivery are for the city in the user's profile on the site.
"""
import html
import json
import re
import urllib.parse

from cdp import tab_for
from shoplog import log

HOME = "https://www.holodilnik.ru"
SITE = "holodilnik"
PAGE = 24
REVIEW_PAGE = 7     # the site's own page size, not settable from the address
SORTS = {"popular": "", "price_asc": "price", "price_desc": "price_desc", "discount": "bestprice", "rating": "rating",
         "stock": "ord"}                                    # ours -> the site's ?sort= («По наличию на складе» for stock)
REVIEW_SORTS = {"new": "", "old": "date-a/", "high": "r-d/", "low": "r-a/"}     # ours -> comments/<part>
BLOCKED = "⚠️ Холодильник.ру не отдал страницу (проверка на бота?): shop-chrome show, открыть сайт, повторить."
NO_ID = "нужна ссылка на товар Холодильник.ру или его код из holodilnik_search"
NO_PRICE = ("Холодильник.ру фильтрует цену в поиске только формой на странице, не адресом: "
            "повтори без price_min/price_max, с sort=price_asc или price_desc")

SEARCH_JS = r"""(() => { const q = (e, s) => e.querySelector(s), t = (e, s) => (q(e, s) ? q(e, s).textContent : '').trim(),
  all = (e, s) => [...e.querySelectorAll(s)].map(x => x.textContent.trim());
  return {origin: performance.timeOrigin, info: !!q(document, '#search_res_info'), found: t(document, '#search_res_info .found_rows b'),
    cards: [...document.querySelectorAll('.catalog-item')].map(c => ({
      href: (q(c, '.catalog-item__name a') || q(c, 'a') || {getAttribute: () => ''}).getAttribute('href') || '',
      code: (q(c, '[data-icon-link-favorite]') || {dataset: {}}).dataset.iconLinkFavorite || '',
      name: t(c, '.catalog-item__title'), price: t(c, '.price-value__actual'), old: t(c, '.price-value__old'),
      rating: t(c, '.rating-value'), count: t(c, '.rating-value__count'), delivery: all(c, '.catalog-item__add-info-delivery-item'),
      badges: all(c, '.catalog-item__badges .info-label__text'), button: t(c, '.hru-btn__text')}))} })()"""
ITEM_JS = r"""(() => { const q = s => document.querySelector(s), t = s => (q(s) ? q(s).textContent : '').trim(),
  m = s => (q(s) || {}).content || '', h = (e, s) => (e.querySelector(s) || {}).innerHTML || '';
  return {origin: performance.timeOrigin, name: m('.card-product-page meta[itemprop="name"]'), code: m('meta[itemprop="sku"]'),
    price: t('.product-price__current'), old: t('.product-price__old'), discount: t('.product-price__discount'),
    availability: m('[itemprop="offers"] meta[itemprop="availability"]'), state: t('.state_lim'),
    rating: m('meta[itemprop="ratingValue"]'), reviews: m('meta[itemprop="reviewCount"]'),
    delivery: [...document.querySelectorAll('.product-delivery-info__item')].map(e => [h(e, '.product-delivery-info__item-name'), h(e, '.flex-shrink-0')]),
    labels: [...document.querySelectorAll('.card-product-img__labels .info-label__text')].map(e => e.textContent.trim()),
    specs: [...document.querySelectorAll('.params-list--in-product .params-list__item')].map(e => [h(e, '.params-list__item-name'), h(e, '.params-list__item-value')]),
    photos: [...document.querySelectorAll('[data-fancybox="images"]')].map(e => e.dataset.src || ''),
    description: (q('#full_description') || {}).innerHTML || ''} })()"""
REVIEWS_JS = r"""(() => { const q = s => document.querySelector(s), t = (e, s) => ((e.querySelector(s) || {}).textContent || '').trim(), box = q('table.reviews');
  return {origin: performance.timeOrigin, box: !!box, name: (q('meta[itemprop="name"]') || {}).content || '',
    rating: box ? t(box, '.rating_top_box .rating_number') : '', count: (q('meta[itemprop="reviewCount"]') || {}).content || '',
    pager: [...document.querySelectorAll('table.reviews td')].map(e => e.textContent.trim()).find(x => x.startsWith('Страницы')) || '',
    items: [...document.querySelectorAll('table.review_add')].map(r => ({time: t(r, '.time'), stars: t(r, '.rating_number'),
      yes: t(r, '.rplus'), no: t(r, '.rminus'), rows: [...r.querySelectorAll('tr')].filter(x => x.querySelector('th') && x.querySelector('td'))
        .map(x => [x.querySelector('th').textContent, x.querySelector('td').innerHTML])}))} })()"""


def _text(s):
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s or "", flags=re.S | re.I)      # a delivery name holds its popup's script
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _rub(s):
    return re.sub(r"\D", "", s or "")


def _num(s):
    """'5,00' or '4.90' -> '5', '4.9'; '' stays ''."""
    s = (s or "").replace(",", ".").strip()
    return f"{float(s):g}" if re.fullmatch(r"\d+(\.\d+)?", s) else ""


def _path(s):
    """The product's address path ('/<section>/<kind>/<brand>/<model>/'), from a link or a path; None for others."""
    m = re.fullmatch(r"\s*(?:(?:https?://)?(?:www\.)?holodilnik\.ru)?(/[^?#\s]*)(?:[?#]\S*)?\s*", str(s))
    if not m:
        return None
    parts = [p for p in m.group(1).split("/comments/")[0].split("/") if p]
    return "/" + "/".join(parts) + "/" if len(parts) >= 2 and parts[0] != "search" else None


def _code(s):
    m = re.fullmatch(r"\s*(\d+)\s*", str(s))
    return m.group(1) if m else None


def _read(tab, url, js):
    """Load url and read the page with js; None when the tab still shows the previous document (the shop tab is reused)."""
    old = tab.js("performance.timeOrigin")
    tab.goto(url, SITE, wait_js=f"performance.timeOrigin !== {json.dumps(old)} && !!document.querySelector('.site-footer')")
    got = tab.js(js)
    return got if got and got.get("origin") != old else None


def _search_url(query, sort, page):
    qs = {"search": query} | ({"sort": SORTS[sort]} if SORTS[sort] else {}) | ({"page": page} if page > 1 else {})
    return f"{HOME}/search/?" + urllib.parse.urlencode(qs)


def _blocked(url):
    log.warning("holodilnik: no page at %s", url)
    return BLOCKED


def search(query, price_min=None, price_max=None, sort="popular", page=1, limit=PAGE):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    if price_min or price_max:
        return NO_PRICE
    url = _search_url(query, sort, page)
    tab = tab_for("holodilnik.ru")
    try:
        r = _read(tab, url, SEARCH_JS)
    finally:
        tab.close()
    if not r or not r.get("info"):
        return _blocked(url)
    rows = [_search_row(i + 1, c) for i, c in enumerate(r["cards"][:limit])]
    return (f"Холодильник.ру · {_rub(r['found']) or 0} найдено · страница {page} (по {PAGE}) · {url}\n"
            f"цены и наличие — для города из профиля на сайте; ссылки относительно {HOME}\n"
            "#\tкод\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tналичие\tпометки\tссылка\n" + ("\n".join(rows) if rows else "(пусто)"))


def _search_row(n, c):
    rating = _num(c["rating"].replace(c["count"], ""))
    return (f"{n}\t{c['code']}\t{_rub(c['price'])}\t{_rub(c['old'])}\t{c['name']}\t{rating}\t{_rub(c['count'])}\t"
            f"{_stock(c)}\t{', '.join(c['badges'])}\t{c['href']}")


def _stock(c):
    """The card's delivery date, or what its button says instead of «В корзину» (out of stock, to order)."""
    button = _text(c["button"])
    return "; ".join(c["delivery"]) or ("" if button == "В корзину" else button)


def _find(tab, code):
    """The path of the product with this code, by the site's search; '' when it finds none, None when no page came."""
    url = _search_url(code, "popular", 1)
    r = _read(tab, url, SEARCH_JS)
    if not r or not r.get("info"):
        _blocked(url)
        return None
    return next((c["href"] for c in r["cards"] if c["code"] == code), "")


def _open(id_or_url, suffix, js):
    """(page data, url) of the product's page path+suffix, for a link or a bare code; or (None, the answer to give)."""
    path, code = _path(id_or_url), _code(id_or_url)
    if not path and not code:
        return None, NO_ID
    tab = tab_for("holodilnik.ru")
    try:
        path = path or _find(tab, code)
        if not path:
            return None, (BLOCKED if path is None else f"Холодильник.ру не нашёл товар с кодом {code}: нужна ссылка из holodilnik_search")
        url = HOME + path + suffix
        got = _read(tab, url, js) or {}     # {}: the tab still showed the previous page
    finally:
        tab.close()
    return got, url


def item(url_or_id, full=False):
    p, url = _open(url_or_id, "", ITEM_JS)
    if p is None:
        return url
    if not p.get("name"):
        return _blocked(url)
    return _card(p, url, full)


def _card(p, url, full):
    lines = [_text(p["name"]), url, f"код товара: {p.get('code')}", _price(p), "наличие: " + _availability(p)]
    lines += _line("получение: ", "; ", _delivery(p.get("delivery")))
    lines.append(f"рейтинг {_num(p.get('rating')) or '—'}, отзывов {p.get('reviews') or 0}")
    lines += _line("пометки: ", ", ", p.get("labels"))
    lines += _line("характеристики: ", "; ", [f"{_text(a)}: {_spec(b)}" for a, b in p.get("specs") or []])
    lines += _line("фото (shop_images): ", " ", _photos(p.get("photos"))[:10])
    text = re.sub(r"^Описание\s*", "", _text(p.get("description")))
    return "\n".join(lines + ["отзывы: holodilnik_reviews", "\n" + (text if full else text[:2500])])


def _delivery(items):
    """'Самовывоз из магазина — c 15 ноября' for each way the card dates (its name ends in a » hint link)."""
    return [f"{_text(a).rstrip('» ')} — {_text(b)}" for a, b in items or [] if _text(b)]


def _photos(srcs):
    """The gallery's pictures as full links (it gives them protocol- or site-relative), without the watermarked copies."""
    return [urllib.parse.urljoin(HOME, x) for x in srcs or [] if x and "/watermark/" not in x]


def _line(label, sep, items):
    """[label + the items joined], or no line for none."""
    return [label + sep.join(items)] if items else []


def _price(p):
    old, pct = _rub(p.get("old")), _rub(p.get("discount"))
    return f"цена: {_rub(p.get('price'))} ₽" + (f" (было {old}" + (f", −{pct}%" if pct else "") + ")" if old else "")


def _availability(p):
    return _text(p.get("state")) or ("есть" if p.get("availability", "").endswith("/InStock") else "нет в наличии")


def _spec(value):
    """A spec's value; yes/no ones are icons: pres_ico.png (has it) and default.png (has not)."""
    if "pres_ico" in value:
        return "да"
    return "нет" if "default.png" in value else _text(value)


def reviews(id_or_url, sort="new", with_media=False, page=1, limit=20):
    wrong = _reviews_wrong(sort, with_media)
    if wrong:
        return wrong
    r, url = _open(id_or_url, "comments/" + REVIEW_SORTS[sort] + (f"?page={page}" if page > 1 else ""), REVIEWS_JS)
    if r is None:
        return url
    if not r.get("box"):
        return _blocked(url)
    rows = [_review_row(x) for x in r["items"][:limit]]
    pages = max(map(int, re.findall(r"\d+", r["pager"])), default=1)
    return (f"Холодильник.ру · {r['name']}: рейтинг {_num(r['rating']) or '—'}, отзывов {r['count'] or 0}\n"
            f"страница {page} из {pages} (по {REVIEW_PAGE}), сортировка {sort}; фото в отзывах сайт не показывает\n"
            "дата\t★\tполезно (да/нет)\tтекст\n" + ("\n".join(rows) if rows else "(отзывов нет)"))


def _reviews_wrong(sort, with_media):
    if sort == "useful":
        return f"Холодильник.ру не сортирует отзывы по полезности: sort одно из {', '.join(REVIEW_SORTS)}"
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    if with_media:
        return "Холодильник.ру не показывает фото в отзывах и не отбирает отзывы с ними: повтори без with_media"
    return None


MARKS = {"Преимущества": "+ ", "Недостатки": "− ", "Комментарий": ""}


def _review_row(x):
    parts = [MARKS[k] + _text(v) for k, v in ((_text(th).rstrip(":"), td) for th, td in x["rows"]) if k in MARKS and _text(v)]
    return f"{x['time'].replace(',', '')}\t{_num(x['stars'])}\t{_rub(x['yes']) or 0}/{_rub(x['no']) or 0}\t{' | '.join(parts)}"
