"""DNS (dns-shop.ru): search, product card and reviews. Read only: no cart, favorites or login.

Search results and the product card are server-rendered HTML; their prices, stock and delivery for the city of the
site profile come from the page's own ajax-state calls (product-buy, avails-container). Whether the page draws them
depends on whether its tab is on screen, and the shop Chrome is usually hidden (2026-11):
- a list page asks for them at once but may never draw them, so we take its answers (capture.py) and read only the
  static part of its DOM;
- a product page asks only for what scrolls into view (its AjaxState lazy loader, an IntersectionObserver), which in
  a hidden tab is nothing: we tell that loader its top price and stock are on screen, and it sends the site's own two
  requests (capture js=). Specs and description come from the static page (top specs, ld+json).
Reviews come from the site's restapi, which its page asks with a multipart form: that one request we build ourselves,
sent from a DNS page with the page's cookies and its city. The site sits behind Qrator, whose JS check the real Chrome
passes by itself on a first visit.
"""
import html
import json
import re
import urllib.parse

from capture import capture
from cdp import site_tab, tab_for
from shoplog import log

HOME = "https://www.dns-shop.ru"
SORTS = {"popular": "popular", "price_asc": "price-asc", "price_desc": "price-desc", "new": "new", "discount": "discount",
         "reviews": "opinion", "rating": "rating"}     # ours -> the site's order=
PAGE = 24
BLOCKED = "⚠️ DNS не отдал данные страницы (проверка на бота?): shop-chrome show, открыть dns-shop.ru, повторить."
GUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
LIST_ANSWERS = {"buy": ["/ajax-state/product-buy/"], "avail": ["/ajax-state/avails-container/"]}
TYPES = {"product-buy": "buy", "avails-container": "avail"}      # ajax-state types -> our names of their answers

# the static part of a list page; a card's price and stock come by the ids of its placeholders (buyId, availId)
SEARCH_JS = r"""(() => { const q = (e, s) => e ? e.querySelector(s) : null, t = (e, s) => (q(e, s) ? q(e, s).textContent : '').trim();
  return {url: location.href, title: t(document, '[data-role="items-count"]'), h1: t(document, 'h1'),
    product: !!q(document, '.product-card-top__title'),
    cards: [...document.querySelectorAll('.catalog-product')].map(c => { const r = q(c, '.catalog-product__rating'), a = q(c, '.catalog-product__name');
      return {guid: c.dataset.product || '', code: c.dataset.code || '', href: a ? a.getAttribute('href') : '',
        name: (a && a.firstChild) ? a.firstChild.textContent.trim() : '', rating: t(r, 'b'), reviews: (r && r.lastChild) ? r.lastChild.textContent.trim() : '',
        brandRating: !!(r && r.classList.contains('catalog-product__rating_brand')), seller: t(c, '.catalog-product__seller'),
        buyId: (q(c, '.catalog-product__buy') || {}).id || '', availId: (q(c, '.catalog-product__avails') || {}).id || ''} }) } })()"""
ITEM_JS = r"""(() => { const q = s => document.querySelector(s), t = s => (q(s) ? q(s).textContent : '').trim();
  return {url: location.href, name: t('.product-card-top__title'), guid: window.cardMicrodataUrl || '',
    code: t('.product-card-top__code').replace(/^\D+/, ''), seller: t('.product-card-top__seller-name'),
    buyId: (q('.product-card-top .product-buy[id]') || {}).id || '', availId: (q('.product-card-top__avails') || {}).id || '',
    drawnPrice: (q('.product-card-top .product-buy__price') && q('.product-card-top .product-buy__price').firstChild || {}).textContent || '',
    drawnPrev: t('.product-card-top .product-buy__prev'), drawnAvail: (q('.product-card-top__avails') || {}).innerHTML || '',
    specs: [...document.querySelectorAll('.product-card-top__specs-item')].map(e => [
      (e.querySelector('.product-card-top__specs-item-title') || {}).textContent || '', (e.querySelector('.product-card-top__specs-item-content') || {}).textContent || '']),
    ld: t('script[type="application/ld+json"]'),
    slider: [...document.scripts].map(s => s.textContent).find(x => x.includes('initProductImagesSlider(')) || ''} })()"""
# the card is there and its top stock block is either waiting for the screen (lazy) or drawn
ITEM_READY = ("(() => { const A = window.AjaxState, a = document.querySelector('.product-card-top__avails'); "
              "return !!(a && A && A.lazyContainers && (A.lazyContainers.has(a.id) || a.innerHTML)) })()")
# [id, type] of the card's top price and stock containers still waiting for the screen; null without the loader
PENDING_JS = r"""(() => { try { const A = window.AjaxState, top = document.querySelector('.product-card-top');
  return [...top.querySelectorAll('[id^="as-"]')].filter(e => A.lazyContainers.has(e.id)).map(e => [e.id, A.lazyContainerTypes.get(e.id)])
    .filter(x => x[1] === 'product-buy' || x[1] === 'avails-container') } catch (e) { return null } })()"""


def _rub(v):
    digits = re.sub(r"\D", "", str(v or ""))
    return int(digits) if digits else None


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _avail(markup):
    """The stock block's lines: 'В наличии в 5 магазинах; Доставим на дом за 2 часа' (each line is a <div>)."""
    return "; ".join(x for x in (_text(p.split(">", 1)[-1]) for p in re.split(r"<div\b", markup or "")) if x)


def _city(markup):
    m = re.search(r'data-city-name\s*=\s*"([^"]*)"', markup or "")
    return html.unescape(m.group(1)) if m else ""


def _states(answer):
    """{placeholder id: its data} of an ajax-state answer; a product-buy state is also found by its product's guid or code."""
    out = {}
    for s in ((answer or {}).get("data") or {}).get("states") or []:
        out[s["id"]] = s["data"]
        out.setdefault(str(s["data"].get("id")), s["data"])
    return out


def _guid(s):
    m = re.search(GUID_RE, str(s or "").lower())
    return m.group(0) if m else None


def _url_id(guid):
    """The 16-hex id of a product link, from the product's guid."""
    d = guid.replace("-", "")
    return d[:12] + d[27:31]


def _item_url(s):
    """The product card's address for a link or a bare guid, None for anything else (a list, a stale-stock offer)."""
    s = str(s).strip()
    if _guid(s) and not s.startswith(("http", "/")):
        return f"{HOME}/product/{_url_id(_guid(s))}/"
    if s.startswith("/"):
        s = HOME + s
    return s.split("?")[0] if re.match(r"https://(www\.)?dns-shop\.ru/product/", s) else None


def _with(url, params):
    """url with params set, in place of its own values of them."""
    base, _, query = url.partition("?")
    keep = [(k, v) for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True) if k not in params]
    return base + "?" + urllib.parse.urlencode(keep + list(params.items()))


def _has(url, params):
    got = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    return all(got.get(k) == [str(v)] for k, v in params.items())


def _load(tab, url, ready):
    """goto url and wait for ready on the new document: the reused tab still shows the previous DNS page."""
    old = tab.js("performance.timeOrigin")
    tab.goto(url, "dns", wait_js=f"performance.timeOrigin !== {json.dumps(old)} && ({ready})")


def _params(sort, price_min, price_max, page):
    qs = {}
    if sort != "popular":
        qs["order"] = SORTS[sort]
    if price_min or price_max:
        qs["price"] = f"{int(price_min or 0)}-{int(price_max or 10_000_000)}"
    if page > 1:
        qs["p"] = page
    return qs


def search(query, price_min=None, price_max=None, sort="popular", page=1, limit=PAGE):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    url, params = f"{HOME}/search/?" + urllib.parse.urlencode({"q": query}), _params(sort, price_min, price_max, page)
    tab = tab_for("dns-shop.ru")
    try:
        got = capture(tab, "dns", _with(url, params) if params else url, LIST_ANSWERS)
        here = tab.js("location.href")
        if params and not _has(here, params):
            # the site moves a search to its category (…&category=… or /catalog/…) and drops our params on the way
            got = capture(tab, "dns", _with(here, params), LIST_ANSWERS)
        r = tab.js(SEARCH_JS)
    finally:
        tab.close()
    return _search_text(r, got, page, limit, params)


def _search_text(r, got, page, limit, params):
    if r["product"]:
        return f"DNS сразу открыл карточку товара: {r['url']} — смотри dns_item"
    if not r["cards"]:
        if not r["h1"]:
            log.warning("dns search %s: no products and no heading", r["url"])
            return BLOCKED
        return f"DNS: товаров на странице нет («{r['h1']}») · {r['url']}"
    buys, avails = _states(got.get("buy")), _states(got.get("avail"))
    city = next((c for c in map(_city, (a.get("html") for a in avails.values())) if c), "")
    rows = [_search_row(i + 1, c, buys, avails) for i, c in enumerate(r["cards"][:limit])]
    return (f"DNS · {_count(r['title']) or len(r['cards'])} найдено · страница {page} (по {PAGE}) · {r['url']}\n" + _dropped(r["url"], params) + _heading(r)
            + f"ссылки относительно {HOME}; цены и наличие — для города из профиля на сайте" + (f" ({city})" if city else "") + "\n"
            "#\tid\tкод\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tналичие\tпродавец\tссылка\n" + "\n".join(rows))


def _dropped(url, params):
    lost = {k: v for k, v in params.items() if not _has(url, {k: v})}
    return f"⚠️ сайт не применил {urllib.parse.urlencode(lost)}: это его выдача по умолчанию\n" if lost else ""


def _count(title):
    m = re.search(r"\d[\d\s]*", title or "")
    return _rub(m.group(0)) if m else None


def _heading(r):
    """The page's own words on what it found: 'Найдено 1 727 товаров в категории Мониторы', or a category's 'Наушники: 124 товара'."""
    title, h1 = " ".join(r["title"].split()), " ".join(r["h1"].split())
    if not title:
        return ""
    return (title if not h1 or h1 in title else f"{h1}: {title}") + "\n"


def _search_row(n, c, buys, avails):
    # a card under /catalog/stale-stock/ is another offer of the same product (same guid) at its own price
    name = ("(stale-stock) " if "/stale-stock/" in c["href"] else "") + " ".join(c["name"].split())
    cells = (n, c["guid"], c["code"], *_prices(buys, c), name, *_rating(c), _avail((avails.get(c["availId"]) or {}).get("html")),
             re.sub(r"^Продавец:\s*", "", c["seller"]), c["href"])
    return "\t".join("" if x is None else str(x) for x in cells)


def _prices(buys, c):
    """(price, price before the discount or None) of a card: its state by placeholder id, or by code or guid once drawn."""
    price = (buys.get(c["buyId"]) or buys.get(c["code"]) or buys.get(c["guid"]) or {}).get("price") or {}
    current, previous = price.get("current"), price.get("previous")
    return current, previous if previous and previous != current else None


def _rating(c):
    """(rating, reviews) of a card; a marketplace card without reviews shows its brand's rating instead."""
    if c["brandRating"]:
        return f"{c['rating']} (бренда)", ""
    return c["rating"], re.sub(r"\s*отзыв\w*$", "", c["reviews"])


def item(url_or_id, full=False):
    url = _item_url(url_or_id)
    if not url and "/stale-stock/" in str(url_or_id) and _guid(url_or_id):
        return f"страницу предложения stale-stock dns_item не читает; обычная карточка этого товара — dns_item(\"{_guid(url_or_id)}\")"
    if not url:
        return f"нужна ссылка на товар из dns_search ({HOME}/product/…) или его id"
    tab = tab_for("dns-shop.ru")
    try:
        _load(tab, url, ITEM_READY)
        got = _wake(tab, url)
        p = tab.js(ITEM_JS)
    finally:
        tab.close()
    if not p["name"]:
        log.warning("dns item %s: no product card on %s", url, p["url"])
        return BLOCKED
    return _card(p, got, full)


def _wake(tab, url):
    """The answers to the card's top price and stock: its lazy loader asks for them once they are on screen, which a
    hidden tab never is, so we tell it they are (its own handleIntersection) and take the two requests it sends."""
    pending = tab.js(PENDING_JS)
    if pending is None:
        log.warning("dns item %s: no AjaxState on the page", url)
    if not pending:
        return {}
    js = ("(() => { const A = window.AjaxState; A.handleIntersection("
          f"{json.dumps([i for i, _ in pending])}.map(id => ({{intersectionRatio: 1, target: document.getElementById(id)}})), A.observer); return true }})()")
    return capture(tab, "dns", None, {TYPES[t]: LIST_ANSWERS[TYPES[t]] for _, t in pending}, js=js)


def _card(p, got, full):
    ld = json.loads(p["ld"]) if p["ld"] else {}
    guid, text = _guid(p["guid"]), " ".join((ld.get("description") or "").split())
    lines = [" ".join(p["name"].split()), p["url"].split("?")[0], f"код товара: {p['code']} · id: {guid or ''}", _offer_price(p, got, guid, ld)]
    if p["seller"]:
        lines.append(f"продавец: {p['seller']} (не DNS)")
    return "\n".join(lines + [_offer_stock(p, got, ld)] + _extras(p, ld) + ["\n" + (text if full else text[:2500])])


def _offer_price(p, got, guid, ld):
    """The price line from the site's answer, else from the drawn card, else from the page's ld+json."""
    states = _states(got.get("buy"))
    buy = states.get(p["buyId"]) or states.get(guid)
    if buy:
        return _price(buy)
    if _rub(p["drawnPrice"]):
        return _price({"price": {"current": _rub(p["drawnPrice"]), "previous": _rub(p["drawnPrev"])}})
    price = (ld.get("offers") or {}).get("price")
    return f"цена: {price} ₽ (из данных страницы: старая цена и скидка не пришли)" if price else "цена: не пришла"


def _offer_stock(p, got, ld):
    markup = (_states(got.get("avail")).get(p["availId"]) or {}).get("html") or p["drawnAvail"]
    if _avail(markup):
        city = _city(markup)
        return f"наличие и доставка (для города из профиля на сайте{': ' + city if city else ''}): {_avail(markup)}"
    known = {"InStock": "в наличии (из данных страницы: магазины и доставка не пришли)", "OutOfStock": "нет в наличии"}
    return "наличие: " + known.get(str((ld.get("offers") or {}).get("availability")).rsplit("/", 1)[-1], "не пришло")


def _extras(p, ld):
    """Rating, photos, where the reviews are and the specs: the card's lines between the stock and the description."""
    rating, photos = ld.get("aggregateRating") or {}, _photos(p["slider"])
    lines = [f"рейтинг: {rating.get('ratingValue')}, отзывов {rating['reviewCount']}"] if rating.get("reviewCount") else []
    if photos:
        lines.append("фото (shop_images): " + " ".join(photos[:10]))
    lines.append("отзывы: dns_reviews")
    if p["specs"]:
        lines.append("характеристики:\n" + "\n".join(f"{' '.join(k.split()).rstrip(':')}: {' '.join(v.split())}" for k, v in p["specs"]))
    return lines


def _price(buy):
    price = buy.get("price") or {}
    current, previous = price.get("current"), price.get("previous")
    note = f" ({buy['tooltip']})" if buy.get("tooltip") else ""
    if not (previous and current and previous > current):
        return f"цена: {current} ₽{note}"
    return f"цена: {current} ₽ (было {previous}, −{round(100 * (previous - current) / previous)}%){note}"


def _photos(script):
    """The 500 px pictures from the page's window.initProductImagesSlider('<id>', {images: [{desktop, …}]}) call."""
    call = re.search(r"initProductImagesSlider\([^{]*", script)
    try:
        data = json.JSONDecoder().raw_decode(script, call.end())[0] if call else {}
    except ValueError:      # no object after the call, or a broken one
        return []
    return [i["desktop"] for i in data.get("images") or [] if i.get("desktop")]


REVIEW_SORTS = {"useful": "2", "new": "0", "rating": "1", "edited": "3"}   # the site's «по популярности», «по дате», «по рейтингу», «по дате изменения»
OPINION_TYPE = "610d4c8e-37fc-416c-a603-bce518d57c15"                       # the objectTypeId the site's own widget sends
OPINIONS = "https://restapi.dns-shop.ru/v1/opinion/get-product-opinions"
REVIEW_PAGE = 10    # what the site's own «Показать ещё» asks for; 20 it refuses: «размер окна превышен» (2026-11)


def _opinions_js(guid, sort, with_media, page):
    """The request the site's opinions widget sends (multipart form, the city of the site profile, its cookies)."""
    form = {"objectTypeId": OPINION_TYPE, "objectId": guid, "offset": str((page - 1) * REVIEW_PAGE), "limit": str(REVIEW_PAGE),
            "isRealBuyer": "0", "hasPhotos": "1" if with_media else "0", "hasVideo": "0", "sort": REVIEW_SORTS[sort],
            "onlyObjectOpinions": "0", "init": "1"}
    return ("(() => { const f = new FormData(), city = window.baseHeaderConfig?.config?.cityGuid || '';"
            f" for (const [k, v] of Object.entries({{cityId: city, ...{json.dumps(form)}}})) f.set(k, v);"
            f" fetch({json.dumps(OPINIONS)}, {{method: 'POST', body: f, credentials: 'include'}}); return true }})()")


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    guid, url = _review_target(id_or_url)
    if not guid and not url:
        return "нужен id товара из dns_search или ссылка на товар DNS"
    tab = tab_for("dns-shop.ru") if url else site_tab("dns-shop.ru", HOME + "/", "dns", ready="window.baseHeaderConfig")
    try:
        if url:
            _load(tab, url, "!!window.cardMicrodataUrl")
            guid = _guid(tab.js("window.cardMicrodataUrl || ''"))
        # no guid on the page: not a product card (a block page, a removed product)
        d = capture(tab, "dns", None, {"o": ["/v1/opinion/get-product-opinions"]}, js=_opinions_js(guid, sort, with_media, page)).get("o") if guid else None
    finally:
        tab.close()
    return _reviews_text(d, guid, sort, with_media, page, limit)


def _review_target(id_or_url):
    """(guid, None) when the input carries the product's guid (an id, a stale-stock link), else (None, its product page):
    only that page knows its product's guid."""
    guid = _guid(id_or_url)
    return (guid, None) if guid else (None, _item_url(id_or_url))


def _reviews_text(d, guid, sort, with_media, page, limit):
    if d is None:
        return BLOCKED
    data = d.get("data")
    if data is None:
        return f"⚠️ DNS не отдал отзывы: {d.get('message') or 'пустой ответ'}"
    rows = [_review_row(o) for o in (data.get("opinions") or [])[:limit]]
    return _reviews_head(data, guid, sort, with_media, page) + "\n" + ("\n".join(rows) if rows else "(отзывов нет)")


def _reviews_head(data, guid, sort, with_media, page):
    stars = " · ".join(f"{g['grade']}★ {g['count']}" for g in sorted(data.get("grades") or [], key=lambda g: -g["grade"]))
    marks = ", ".join(f"{g['title']} {g['value']}" for g in data.get("characteristicGrades") or [])
    fc = data.get("filtersCount") or {}
    return (f"DNS · id {guid}: рейтинг {data.get('averageRating') or '—'}, отзывов {data.get('totalCount') or 0} (на все варианты товара)"
            + (f" · {stars}" if stars else "") + "\n" + (f"оценки: {marks}\n" if marks else "")
            + f"страница {page} (по {REVIEW_PAGE}: больше сайт за раз не отдаёт), сортировка {sort}{', только с фото' if with_media else ''}; "
            f"с фото: {fc.get('hasPhoto', 0)}, с видео: {fc.get('hasVideo', 0)}\n"
            "дата\t★\tполезно\tвариант\tсрок\tтекст\tфото и видео (shop_images)")


def _review_row(o):
    variant = ", ".join(f"{k} {v}" for k, v in (o.get("multiCardSpecs") or {}).items())
    return "\t".join(str(x) for x in ((o.get("insertStamp") or "")[:10], o.get("rating"), _useful(o.get("votes") or {}), variant,
                                      o.get("period") or "", _review_body(o), " ".join(_media(o))))


def _useful(votes):
    return f"+{votes.get('positive', 0)}/−{votes.get('negative', 0)}" if votes.get("positive") or votes.get("negative") else ""


def _media(o):
    return [i["thumbUrl"] for i in o.get("images") or [] if i.get("thumbUrl")] + [v["url"] for v in o.get("videos") or [] if v.get("url")]


def _review_body(o):
    parts = [f"+ {_text(o['plus'])}" if _text(o.get("plus")) else "", f"− {_text(o['minus'])}" if _text(o.get("minus")) else "", _text(o.get("comment"))]
    parts += [f"дополнение: {_text(a.get('text'))}" for a in o.get("additions") or [] if _text(a.get("text"))]
    return ("[закреплён] " if o.get("isTop") else "") + " | ".join(p for p in parts if p)
