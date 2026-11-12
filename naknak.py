"""НакНак (naknak.ru): a Moscow shop of Apple, Samsung, Google, Dyson and PlayStation gear. Read only.

A Bitrix site whose pages come rendered from the server, read from the DOM after one load. It has no site search:
its form goes to /catalog/?q=, a 404 (as do /search/ and /?q=), Enter is switched off and the dropdown's own POST
comes back empty. So search names a section of its catalogue menu (14 of them, kept here: the menu is only on its
home page) and lists that section's models, each with its «от» price. A model is one card with configurations
(?oid=<offer>); the page shows the price of the chosen one only, and the range of all in its ld+json. Its products
have no reviews; the site's «Отзывы» are about the shop.
"""
import json
import re

from cdp import tab_for
from shoplog import log

HOME = "https://naknak.ru"
SITE = "naknak"
PAGE = 50
# the site's catalogue menu: path -> (name, other words for it); three entries lead straight to a model
SECTIONS = {"aksessuary": ("Аксессуары", "аксессуар чехол чехлы стекло адаптер"),     # first: a case names its phone too
            "iphone": ("iPhone", "айфон"), "samsung": ("Samsung", "самсунг galaxy"), "google": ("Google", "pixel пиксель"),
            "macbook": ("MacBook", "макбук"), "mac": ("Mac", "imac аймак"), "ipad": ("iPad", "айпад"),
            "airpods": ("AirPods", "аирподс эйрподс"), "apple-watch": ("Apple Watch", "watch"), "dyson": ("Dyson", "дайсон"),
            "playstation": ("PlayStation", "ps5 плейстейшн"), "homepod/homepod-2023": ("HomePod", ""),
            "apple-tv/apple-tv-4k-2022": ("Apple TV", ""), "apple-vision-pro/apple-vision-pro": ("Apple Vision Pro", "vision")}
AVAILABILITY = {"InStock": "в наличии", "OutOfStock": "нет в наличии", "PreOrder": "под заказ"}
BLOCKED = "⚠️ НакНак не отдал страницу (проверка на бота?): shop-chrome show, открыть naknak.ru, повторить."
NO_SEARCH = ("⚠️ на naknak.ru нет поиска по сайту (его страница поиска отдаёт 404), а в запросе не назван раздел его меню. "
             "Разделы: " + ", ".join(name for name, _ in SECTIONS.values()))
NO_OPTIONS = ("⚠️ у НакНак нет сортировки, фильтра по цене и страниц выдачи: раздел умещается на одной странице, "
              "у каждой модели цена «от»; повтори без sort, price_min, price_max и page")
NO_ID = "⚠️ нужна ссылка на модель НакНак или её id из naknak_search (например iphone/iphone-17-pro)"
NO_REVIEWS = ("НакНак: отзывов о товарах на сайте нет (на странице товара их нет); есть только отзывы о самом магазине — "
              f"{HOME}/reviews")
READY = "document.readyState === 'complete'"
DELIVERY = f"получение: на странице товара не указано; условия доставки и самовывоза — {HOME}/help/delivery/"

# a section's models, or a model's card: its ld+json and what only its DOM shows (price, options, chosen ones, photos)
PAGE_JS = r"""(() => { const q = s => document.querySelector(s), all = s => [...document.querySelectorAll(s)];
  const t = (e, s) => ((e && e.querySelector(s)) || {}).textContent || '';
  const own = e => e ? [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ') : '';   // without its label
  return {path: location.pathname, oid: new URLSearchParams(location.search).get('oid'), title: document.title, h1: t(document, 'h1'),
    ld: [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => { try { return JSON.parse(s.textContent) } catch (e) { return null } })
      .find(x => x && x['@type'] === 'Product') || null,
    models: all('a.catalog-section__item-wrapper').map(a => ({href: a.getAttribute('href'), name: own(a.querySelector('.catalog-section__item-name')),
      label: t(a, '.catalog-section__item-name span'), price: t(a, '.catalog-section__item-first-description')}))
      .concat(all('a.catalog-card__link').map(a => ({href: a.getAttribute('href'), name: t(a, '.catalog-card__title'),     // accessories, by phone
        label: ((a.closest('.catalog-preview__list') || {}).previousElementSibling || {}).textContent || '', price: t(a, '.catalog-card__content span')}))),
    price: t(document, '.price__new-val'), old: t(document, '.price__old-val'),
    props: all('.sku-props__item').map(e => ({title: t(e, '.sku-props__title'),
      values: [...e.querySelectorAll('.sku-props__value')].map(b => ({name: b.dataset.title, on: b.classList.contains('sku-props__value--active')}))})),
    config: all('.config__elem--custom').map(e => e.textContent), photos: all('a.detail-gallery-big__link').map(a => a.getAttribute('href')),
    specs: (q('.detail-text--custom') || {}).innerText || ''} })()"""


def _text(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _rub(s):
    digits = re.sub(r"\D", "", str(s or ""))
    return int(digits) if digits else None


def _section(query):
    """(menu path, the query's other words) of the section the query names, or None; whole words only (Mac ≠ MacBook)."""
    q = query.lower()
    for path, (name, others) in SECTIONS.items():
        for word in [name.lower(), *others.split()]:
            m = re.search(rf"(?<!\w){re.escape(word)}(?!\w)", q)
            if m:
                return path, (q[:m.start()] + q[m.end():]).split()
    return None


def _path(url_or_id):
    """'<section>/<model>/' with its '?oid=N' if any, of a link or an id; None for a bare section or anything else."""
    m = re.fullmatch(r"(?:https?://(?:www\.)?naknak\.ru)?/?([a-z0-9-]+(?:/[a-z0-9-]+)+)/?(\?oid=\d+)?", str(url_or_id).strip())
    return m.group(1) + "/" + (m.group(2) or "") if m else None


def _read(url):
    """One load of url by the site's slot, then its PAGE_JS: the reused tab shows the previous page until the new one is in."""
    tab = tab_for("naknak.ru")
    try:
        old = tab.js("performance.timeOrigin")
        tab.goto(url, SITE, wait_js=f"performance.timeOrigin !== {json.dumps(old)} && ({READY})")
        return tab.js(PAGE_JS)
    finally:
        tab.close()


def _missing(r, url):
    if r and "не найдена" in r["title"]:
        return f"⚠️ НакНак: такой страницы нет (404): {url}"
    log.warning("naknak %s: neither models nor a product", url)
    return BLOCKED


def search(query, price_min=None, price_max=None, sort="default", page=1, limit=PAGE):
    if price_min or price_max or sort != "default" or page != 1:
        return NO_OPTIONS
    found = _section(query)
    if not found:
        return NO_SEARCH
    path, words = found
    url = f"{HOME}/{path}/"
    r = _read(url)
    if not r or not (r["models"] or r["ld"]):
        return _missing(r, url)
    return _models_text(r, SECTIONS[path][0], words, url, limit)


def _models_text(r, name, words, url, limit):
    models = [_model(m) for m in r["models"]] or [_single(r)]       # a menu entry may lead straight to a model
    hits = [m for m in models if all(w in m[2].lower() for w in words)]
    shown = hits or models
    rows = ["\t".join(map(str, (i + 1, m[0], m[1] or "", m[2], m[3]))) for i, m in enumerate(shown[:limit])]
    return (f"НакНак · {len(shown)} найдено · страница 1 (по {limit}) · {url}\n"
            + ("" if hits else f"⚠️ в разделе {name} нет моделей со словами «{' '.join(words)}»: ниже весь раздел\n")
            + f"поиска у сайта нет: это модели его раздела {name}" + (f" со словами «{' '.join(words)}»" if hits and words else "")
            + "; цена — «от», за самую дешёвую конфигурацию; точная цена, варианты и наличие — naknak_item; "
            f"ссылки относительно {HOME}; магазин в Москве\n#\tid\tцена от ₽\tназвание\tссылка\n" + "\n".join(rows))


def _model(m):
    """(id, «от» price, name, link) of a section's model."""
    label = _text(m["label"])
    return m["href"].strip("/"), _rub(m["price"]), _text(m["name"]) + (f" ({label})" if label else ""), m["href"]


def _single(r):
    return r["path"].strip("/"), _rub((r["ld"].get("offers") or {}).get("lowPrice")), _text(r["h1"]), r["path"]


def item(url_or_id, full=False):
    path = _path(url_or_id)
    if not path:
        return NO_ID
    url = f"{HOME}/{path}"
    r = _read(url)
    if r and r["models"]:                       # a sub-section of the menu, e.g. one kind of accessories
        return _models_text(r, _text(r["h1"]), [], url, PAGE)
    if not r or not r["ld"]:
        return _missing(r, url)
    return _card(r, full)


def _card(r, full):
    r = {**r, "oid": _oid(r)}
    offers = r["ld"].get("offers") or {}
    specs = "; ".join(f"{x.get('name')}: {x.get('value')}" for x in r["ld"].get("additionalProperty") or [])
    lines = _head(r, offers) + _variants(r["props"]) + ["наличие: " + _availability(offers, r["oid"]), DELIVERY]
    lines += [f"характеристики: {specs}"] if specs else []
    photos = [HOME + x for x in dict.fromkeys(r["photos"])][:10]
    lines += [f"фото (shop_images): {' '.join(photos)}"] if photos else []
    text = "\n".join(x for x in map(_text, r["specs"].splitlines()) if x)
    return "\n".join(lines + ["отзывы: naknak_reviews (у товаров сайта отзывов нет)", "\n" + (text if full else text[:2500])])


def _oid(r):
    """The chosen offer: from the address, else from the ld+json's url (a one-offer product keeps its bare address)."""
    m = re.search(r"oid=(\d+)", r["ld"].get("url") or "")
    return r["oid"] or (m.group(1) if m else None)


def _head(r, offers):
    """Name, link, id with the chosen offer, its price and configuration, and the price range of all of them."""
    oid = r["oid"]
    chosen = "; ".join(_text(c) for c in r["config"])
    link = HOME + r["path"] + (f"?oid={oid}" if oid else "")
    ids = f"id: {r['path'].strip('/')}" + (f" · вариант (oid): {oid}" if oid else "")
    price = _price(r) + (f" — выбранная конфигурация: {chosen}" if chosen else "")
    lines = [_text(r["h1"]) or _text(r["ld"].get("name")), link, ids, price]
    if (offers.get("offerCount") or 0) > 1:
        lines.append(f"конфигураций {offers['offerCount']}, от {offers.get('lowPrice')} до {offers.get('highPrice')} ₽; "
                     "цену другой сайт показывает только после выбора на странице")
    return lines


def _price(r):
    now, old = _rub(r["price"]), _rub(r["old"])
    cut = f" (было {old}, −{round(100 * (old - now) / old)}%)" if now and old and old > now else ""
    return f"цена: {now or '—'} ₽" + cut


def _variants(props):
    """'Память: 256 ГБ*, 512 ГБ' for each option, * — the chosen value; the page draws the block twice."""
    lines = {}
    for p in props:
        lines.setdefault(_text(p["title"]), ", ".join(_text(v["name"]) + ("*" if v["on"] else "") for v in p["values"]))
    return [f"{k}: {v}" for k, v in lines.items()]


def _availability(offers, oid):
    """The chosen offer's availability in the ld+json's list of offers, or the product's own when it has no offers."""
    tail = offers.get("availability") or next((o.get("availability") or "" for o in offers.get("offers") or [] if (o.get("url") or "").endswith(f"oid={oid}")), "")
    tail = tail.rsplit("/", 1)[-1]
    return AVAILABILITY.get(tail, tail or "—")


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    """The site has no product reviews: sort, with_media, page and limit, kept for the other shops' shape, change nothing."""
    return NO_REVIEWS
