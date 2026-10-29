"""Перекрёсток (perekrestok.ru): the site's own API client, called inside its tab.

The API (/api/customer/1.4.1.x) wants an «Auth: Bearer …» header that the site's axios instance adds; a plain
fetch() gets 401. So we call that very instance: it is found among the page's webpack modules by its code
(the module that builds the 1.4.1 baseURL with a paramsSerializer), not by a module id, which changes with
every build. We never read the header or the token; responses come back unwrapped (the client strips
«content»). Money is in kopecks, ratings ×100, nutrition ×1000.
"""
import json
import re
import time
import urllib.parse

from cdp import tab_for
from shoplog import log

from .ids import first_group

BLOCKED = "⚠️ Перекрёсток не отдал данные (проверка на бота или сайт не загрузился): shop-chrome show, открыть perekrestok.ru, повторить."
CHECKED = ("⚠️ Перекрёсток показал проверку на бота (ServicePipe): попроси пользователя выполнить shop-chrome show, пройти её во "
           "вкладке perekrestok.ru, потом shop-chrome hide. Она включается после долгой серии запросов с одного IP.")
# the favourites are the account's own: a 401/403 there that a reload did not cure is a logged-out session
LOGGED_OUT = ("⚠️ Перекрёсток не пускает к избранному ({}): похоже, в браузере магазинов не выполнен вход. Попроси пользователя "
              "выполнить shop-chrome show, войти на perekrestok.ru, потом shop-chrome hide.")
UNCHECKED = "{}: Перекрёсток не отдал корзину, и не видно, что получилось — проверь grocery_cart, прежде чем повторять"
SITE = "https://www.perekrestok.ru"
FIND_API = """(() => {
  if (window.__shopApi) return true;
  let req; (window.__LOADABLE_LOADED_CHUNKS__ || []).push([[Symbol('shop-mcp')], {}, r => { req = r }]);
  if (!req) return false;
  for (const id of Object.keys(req.m)) {
    const s = String(req.m[id]);
    if (!s.includes('paramsSerializer') || !s.includes('/1.4.1.')) continue;
    for (const v of Object.values(req(id) || {}))
      if (v && v.defaults && /api\\/customer\\//.test(v.defaults.baseURL || '') && typeof v.get === 'function') { window.__shopApi = v; return true }
  }
  return false
})()"""
SORT = {"popular": {}, "price": {"orderBy": "price", "orderDirection": "asc"}, "price_desc": {"orderBy": "price", "orderDirection": "desc"},
        "discount": {"orderBy": "discount", "orderDirection": "desc"}, "rating": {"orderBy": "rating", "orderDirection": "desc"}}
FORM = {"disableBubbleUp": True, "sortByAlpha": True}     # the search form's own options
DIET = "osobennosti"                                      # the facet of «Без лактозы», «Без сахара»…


# the home page's client is up, or ServicePipe's check page came instead (then wait no longer)
HOME_READY = "!!window.__LOADABLE_LOADED_CHUNKS__ && document.readyState === 'complete' || location.pathname.includes('/xpvnsulc/')"


def _tab():
    tab = tab_for("perekrestok.ru")
    if "perekrestok.ru" not in (tab.js("location.hostname") or "") or not tab.js(FIND_API):
        # one load of the home page; a check page left in the tab may be stale — session restore after a Chrome
        # restart brings back the old one, already passed (2026-10-13). If the home page shows the check, it is real.
        tab.goto(SITE + "/", "perekrestok", wait_js=HOME_READY)
        if not tab.js(FIND_API):
            checked = _checked(tab)
            tab.close()
            raise RuntimeError(CHECKED if checked else BLOCKED)
    return tab


def _checked(tab):
    """The tab shows ServicePipe's bot check."""
    return "/xpvnsulc/" in (tab.js("location.pathname") or "")


_last = 0.0
_cache: dict = {}            # (method, path, body) → (time, data) for slow-changing reads: delivery terms, search facets
GAP = 1.5                    # s between calls: a burst of ~30 in a few seconds brought ServicePipe's bot check (2026-10-13)


def _cached(tab, method, path, body=None, ttl=600):
    key = (method, path, json.dumps(body, sort_keys=True))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    d = _call(tab, method, path, body)
    if isinstance(d, dict) and not _failed(d):
        _cache[key] = (time.time(), d)
    return d


def _call(tab, method, path, body=None, retried=False):
    """The site's client: method get/post/put/delete. Only response data comes back, never the request config.
    401/403: the page's session or anti-bot cookie went stale (2026-10-13, after an hour of calls) — a reload renews it."""
    global _last
    wait = GAP - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.time()
    d = _request(tab, method, path, body)
    if _failed(d):
        log.warning("perekrestok %s %s: %s%s", method, path[:120], d["__error"], " again after reload" if retried else "")
        if d["__error"] in (401, 403) and not retried and _renew(tab):
            return _call(tab, method, path, body, True)
    return d


def _failed(d):
    """The site's client answered with an error status, not with data: not an empty basket."""
    return isinstance(d, dict) and "__error" in d


def _request(tab, method, path, body):
    args = json.dumps(path) + ("" if body is None else ", " + json.dumps(body))
    r = tab.js(f"window.__shopApi.{method}({args}).then(r => JSON.stringify(r.data ?? null))"
               ".catch(e => JSON.stringify({__error: e.response ? e.response.status : String(e.message || e)}))")
    return json.loads(r) if r else None


def _renew(tab):
    """Reload the home page; True when the site's client is back, the bot check raises."""
    tab.js("delete window.__shopApi")
    tab.goto(SITE + "/", "perekrestok", wait_js=HOME_READY)
    time.sleep(1.5)
    if tab.js(FIND_API):
        return True
    if _checked(tab):
        raise RuntimeError(CHECKED)
    return False


def _rub(k):
    return round(k / 100, 2) if isinstance(k, (int, float)) else None


def _plu(id_or_url):
    return first_group(id_or_url, "нужен plu Перекрёстка или ссылка https://www.perekrestok.ru/cat/<раздел>/p/<название>-<plu>",
                       r"-(\d+)/?(?:\?|$|/reviews)", r"^\s*(?:plu)?(\d+)\s*\Z")


def _url(p):
    md = p.get("masterData") or {}
    cat = (p.get("catalogPrimaryCategory") or p.get("primaryCategory") or {}).get("id")
    return f"{SITE}/cat/{cat}/p/{md.get('slug')}-{md.get('plu')}" if cat and md.get("slug") else f"{SITE}/cat/search?search={md.get('plu', '')}"


def _size(md):
    if md.get("unitName") == "кг":       # sold by weight: the price is per kilogram
        return "1 кг"
    if md.get("weight"):
        return f"{md['weight']} г"
    if md.get("volume"):
        return f"{md['volume']} мл"
    return ""


def _listed(p):
    md, pt = p.get("masterData") or {}, p.get("priceTag") or {}
    return {"id": str(md.get("plu") or p.get("plu") or ""), "name": p.get("title", ""), "brand": "", "size": _size(md),
            "price": _rub(pt.get("price")), "old": _rub(pt.get("grossPrice")),
            "available": p.get("balanceState") not in ("sold-out", "out-of-stock") and (p.get("balanceStock") is None or p["balanceStock"] > 0),
            "url": _url(p), "rating": (p["rating"] / 100) if p.get("rating") else None, "reviews": p.get("ratingCount"), "ean": None}


def _facets(tab, query):
    """{title: (feature key, value)} of the search's own filters: «Без лактозы» → ("osobennosti", "bez-laktozy")…"""
    form = _cached(tab, "post", "/catalog/search/form", {"filter": {"textQuery": query}, **FORM}) or {}
    out = {}
    for f in form.get("searchFeatures") or []:
        if f.get("key") in ("brand",):
            continue
        for e in f.get("enumList") or []:
            out[e["title"]] = (f["key"], e["value"])
    return out, form.get("productCount")


def search(query, tag=None, sort="popular", page=1, limit=30):
    tab = _tab()
    try:
        facets, total = _facets(tab, query)
        flt, note = _filter(facets, query, tag)
        d = _call(tab, "post", "/catalog/product/feed",
                  {"page": page, "perPage": min(max(limit, 12), 48), "filter": flt, "withBestProductReviews": False, **SORT[sort]})
        if "features" in flt:      # the facet's own count
            total = (_call(tab, "post", "/catalog/search/form", {"filter": flt, **FORM}) or {}).get("productCount")
    finally:
        tab.close()
    if not isinstance(d, dict) or "items" not in d:
        return BLOCKED
    if _more(d):
        note += ("\n" if note else "") + f"есть следующая страница: page={page + 1}"
    q = {"search": query, **SORT[sort], **({"page": page} if page > 1 else {})}
    return {"items": [_listed(p) for p in d["items"]][:limit], "total": total, "note": note, "facets": _titles(facets),
            "url": f"{SITE}/cat/search?" + urllib.parse.urlencode(q)}


def _filter(facets, query, tag):
    """The feed's filter and a note: the search's own facet whose title has tag in it, or else tag added to the text."""
    if not tag:
        return {"textQuery": query}, ""
    hit = next((v for t, v in facets.items() if tag.lower() in t.lower()), None)
    if hit:
        return {"textQuery": query, "features": [{"key": hit[0], "value": hit[1]}]}, ""
    return {"textQuery": f"{query} {tag}"}, f"фильтра «{tag}» у Перекрёстка для этого запроса нет — искал «{query} {tag}» текстом"


def _titles(facets):
    """Diet filters first, then up to 25 kinds of product."""
    return [t for t, (key, _) in facets.items() if key == DIET] + [t for t, (key, _) in facets.items() if key != DIET][:25]


def _items(p):
    """(feature title, item) for every item of the card's characteristics."""
    return [(f.get("title") or "", it) for f in p.get("features") or [] for it in f.get("items") or []]


def _feature(p, key, field):
    """The first of field's values in the card's item key: _feature(p, "brand", "displayValues") → "Простоквашино"."""
    it = next((it for _, it in _items(p) if it.get("key") == key), {})
    return (it.get(field) or [""])[0]


def product(id_or_url):
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        p = _call(tab, "get", f"/catalog/product/plu{plu}")
        delivery = _cached(tab, "get", "/delivery/switcher") or {}
    finally:
        tab.close()
    if not isinstance(p, dict) or "masterData" not in p:
        return BLOCKED if not isinstance(p, dict) or p.get("__error") not in (404,) else f"Перекрёсток: товар {plu} не найден"
    return _card(p, delivery)


def _card(p, delivery):
    info = _info(p)
    out = _listed(p)
    out.update(brand=_feature(p, "brand", "displayValues"), photos=_photos(p.get("images")), description=p.get("description") or "",
               composition=_feature(p, "sostav", "values"), nutrition=_nutrition(p), reviews=p.get("reviewCount") or p.get("ratingCount"),
               composition_extra="; ".join(x for x in info if re.search(r"какао|мяс|сок|жирн|шоколад", x, re.I)), extra=_extra(p, delivery, info))
    return out


NUTRITION = "Пищевая ценность"
NUTRIENTS = {"kkal": "kcal", "belki": "protein", "jiry": "fat", "uglevody": "carbs"}


def _nutrition(p):
    nut = {}
    for title, it in _items(p):
        k = NUTRIENTS.get(it.get("key")) if NUTRITION in title else None
        v = (it.get("values") or [None])[0] if k else None
        if v not in (None, ""):
            nut[k] = round(float(v) / 1000, 2)
    return nut


def _info(p):
    """«name: values» of the card's characteristics but its composition, nutrition and brand."""
    return [f"{it.get('title') or it.get('key')}: {', '.join(it['displayValues'])}" for title, it in _items(p)
            if title != "Состав" and NUTRITION not in title and it.get("key") != "brand" and it.get("displayValues")]


def _extra(p, delivery, info):
    pt = p.get("priceTag") or {}
    return [x for x in (_labels(pt), _weighed(p.get("masterData") or {}, pt),
                        p.get("medianPrice") and f"обычная цена (медиана): {_rub(p['medianPrice'])} ₽",
                        _delivery(delivery), info and "характеристики: " + "; ".join(info)) if x]


def _labels(pt):
    texts = [x["text"] for x in pt.get("labels") or [] if x.get("text")]
    return texts and "акции: " + "; ".join(texts)


def _weighed(md, pt):
    if md.get("unitName") != "кг" or not md.get("quantum"):
        return ""
    price = _rub(pt.get("price"))
    return (f"весовой товар: цена за кг, шаг продажи {md['quantum'] / 1000:g} кг"
            + (f" (≈ {round(price * md['quantum'] / 1000)} ₽ за шаг)" if price is not None else ""))


def _delivery(delivery):
    tabs = [_delivery_tab(t) for t in delivery.get("tabs") or [] if t.get("type") != "catalog"]
    return tabs and "доставка на адрес из профиля: " + "; ".join(tabs)


def _delivery_tab(t):
    rub = _rub(t.get("cost"))
    terms = f"{t.get('costString') or ('' if rub is None else f'{rub} ₽')}, {(t.get('congestion') or {}).get('deliveryRange') or ''}".strip(", ")
    return (f"{t.get('title') or t.get('type')}" + (f": {terms}" if terms else "")
            + (f", заказ от {_rub(t['minCost'])} ₽" if t.get("minCost") else ""))


def _photos(images):
    return [i["cropUrlTemplate"].replace("%s", "800x800-fit") for i in images or [] if i.get("cropUrlTemplate")]


# sort: (the site's star filter, the order the page shows)
SORTS = {"useful": ({}, "новые сверху (другой сортировки у сайта нет)"), "new": ({}, "новые сверху"),
         "high": ({"ratingFrom": 500, "ratingTo": 500}, "только 5★"), "low": ({"ratingFrom": 100, "ratingTo": 200}, "только 1–2★")}
STARS = ((5, "five"), (4, "four"), (3, "three"), (2, "two"), (1, "one"))


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=40):
    """The site shows reviews newest first, without sorting; high / low are its star filters (5★, 1–2★)."""
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    plu = _plu(id_or_url)
    q = urllib.parse.urlencode({"page": page, "perPage": limit, **SORTS[sort][0]})
    tab = _tab()
    try:
        cnt = _call(tab, "get", f"/catalog/product/plu{plu}/review/count") or {}
        d = _call(tab, "get", f"/catalog/product/plu{plu}/review?{q}") or {}
    finally:
        tab.close()
    rows = "\n".join(filter(None, (_review(x, with_media) for x in d.get("items") or [])))
    return (f"Перекрёсток · plu {plu}: отзывов {cnt.get('total', '?')} · " + " ".join(f"{i}★ {cnt.get(w, 0)}" for i, w in STARS)
            + f"\nстраница {page} по {limit}, {SORTS[sort][1]}" + (", только с фото — из этой страницы" if with_media else "")
            + (f"; есть ещё: page={page + 1}" if _more(d) else "")
            + "\nдата\t★\tавтор\tтекст\tфото (shop_images)\n" + (rows or "(отзывов нет)"))


def _more(d):
    return (d.get("paginator") or {}).get("nextPageExists")


def _review(x, with_media):
    """One review's line; empty when only reviews with photos are wanted and it has none."""
    photos = _photos(x.get("approvedImages"))
    if with_media and not photos:
        return ""
    return (f"{_date(x.get('createdAt'))}\t{(x.get('rating') or 0) / 100:g}\t{x.get('username') or ''}\t"
            f"{' '.join((x.get('comment') or '').split())}\t{' '.join(photos)}")


def _date(ts):
    if isinstance(ts, (int, float)) and ts > 1e11:   # milliseconds
        ts /= 1000
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if isinstance(ts, (int, float)) else str(ts or "")[:10]


def cart():
    tab = _tab()
    try:
        d = _call(tab, "get", "/basket") or {}
    finally:
        tab.close()
    if _failed(d):
        return BLOCKED
    items = d.get("items") or []
    if not items:
        return "корзина Перекрёстка пуста"
    return ("корзина Перекрёстка" + (f", итого {_rub(d['totalCost'])} ₽" if d.get("totalCost") else "")
            + "\nplu\tшт\tцена ₽\tсумма ₽\tназвание\tналичие\n" + "\n".join(_cart_row(i) for i in items))


def _cart_row(i):
    p = i.get("product") or {}
    return (f"{p.get('masterData', {}).get('plu', '')}\t{i.get('quantity', '')}\t{_rub(i.get('price'))}\t{_rub(i.get('cost'))}\t"
            f"{p.get('title', '')}\t{'' if p.get('balanceState') != 'sold-out' else 'нет в наличии'}")


def _product_id(tab, plu):
    """Cart and favorites take the product's own id, not its plu."""
    p = _call(tab, "get", f"/catalog/product/plu{plu}")
    if not isinstance(p, dict) or not p.get("id"):
        raise ValueError(f"Перекрёсток: товар plu {plu} не найден")
    return p["id"], p.get("title", "")


def _line(b, plu):
    it = next((i for i in (b or {}).get("items") or [] if str(((i.get("product") or {}).get("masterData") or {}).get("plu")) == str(plu)), None)
    state = {"too_cheap": f"до минимального заказа {b.get('disabledButtonTitle', '').lower()}" if b.get("disabledButtonTitle") else "сумма меньше минимального заказа"}.get(b.get("state"), "")
    return it, state


def add_to_cart(id_or_url, quantity=1):
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        _, title = _product_id(tab, plu)
        n = max(1, min(int(quantity), 30))
        b, done, refused = _plus(tab, plu, n)
    finally:
        tab.close()
    if not done:
        return f"Перекрёсток не положил {title}: {refused}"
    it, state = _line(b, plu)
    if not it:
        return f"Перекрёсток: {title} в корзине не появился (нет в наличии?)"
    return (f"в корзине Перекрёстка: {title} — {it.get('quantity')} шт × {_rub(it.get('price'))} ₽ = {_rub(it.get('cost'))} ₽"
            + (f"\n{state}" if state else "") + (f"\nположено {done} из {n}, дальше Перекрёсток отказал: {refused}" if done < n else ""))


def _plus(tab, plu, n):
    """The site's own «+», one unit per call, n times or up to a refusal: (the last basket, calls that went through, the refusal)."""
    b = None
    for done in range(n):
        r = _call(tab, "put", f"/basket/plu{plu}/plus")
        if not isinstance(r, dict) or _failed(r):
            return b, done, r.get("__error") if isinstance(r, dict) else r
        b = r
    return b, n, None


def remove_from_cart(id_or_url):
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        pid, title = _product_id(tab, plu)
        b = _call(tab, "get", "/basket") or {}
        if _failed(b):
            return BLOCKED
        if not _line(b, plu)[0]:
            return f"{title} в корзине Перекрёстка нет"
        _call(tab, "delete", f"/basket/item/{pid}")
        b = _call(tab, "get", "/basket") or {}
    finally:
        tab.close()
    if _failed(b):
        return UNCHECKED.format(title)
    return f"не удалось убрать {title} из корзины Перекрёстка" if _line(b, plu)[0] else f"убрано из корзины Перекрёстка: {title}"


def favorites():
    tab = _tab()
    try:
        d = _call(tab, "get", "/user/liked-product?page=1&perPage=100") or {}
    finally:
        tab.close()
    if _failed(d):
        return _refused(d) or BLOCKED
    rows = [_listed(x["product"]) for x in d.get("items") or [] if x.get("product")]
    if not rows:
        return "избранное Перекрёстка пусто"
    return "избранное Перекрёстка\nplu\tцена ₽\tналичие\tназвание\n" + "\n".join(
        f"{r['id']}\t{r['price']}\t{'' if r['available'] else 'нет в наличии'}\t{r['name']}" for r in rows)


def _refused(d):
    return LOGGED_OUT.format(d["__error"]) if d["__error"] in (401, 403) else ""


def favorite(id_or_url, remove=False):
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        pid, title = _product_id(tab, plu)
        r = _call(tab, "delete" if remove else "post", f"/user/liked-product/{pid}")
    finally:
        tab.close()
    if _failed(r):
        return _refused(r) or f"Перекрёсток не изменил избранное: {r['__error']}"
    return f"{'убрано из избранного' if remove else 'в избранном'} Перекрёстка: {title}"
