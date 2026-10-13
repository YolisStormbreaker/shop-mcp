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

BLOCKED = "⚠️ Перекрёсток не отдал данные (проверка на бота или сайт не загрузился): shop-chrome show, открыть perekrestok.ru, повторить."
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
SORT = {"popular": ("relevance", "desc"), "price": ("price", "asc"), "price_desc": ("price", "desc"),
        "discount": ("discount", "desc"), "rating": ("rating", "desc")}


def _tab():
    tab = tab_for("perekrestok.ru")
    if "perekrestok.ru" not in (tab.js("location.hostname") or "") or not tab.js(FIND_API):
        tab.goto(SITE + "/", "perekrestok", wait_js="!!window.__LOADABLE_LOADED_CHUNKS__ && document.readyState === 'complete'")
        if not tab.js(FIND_API):
            tab.close()
            raise RuntimeError(BLOCKED)
    return tab


def _call(tab, method, path, body=None):
    """The site's client: method get/post/put/delete. Only response data comes back, never the request config."""
    args = json.dumps(path) + ("" if body is None else ", " + json.dumps(body))
    r = tab.js(f"window.__shopApi.{method}({args}).then(r => JSON.stringify(r.data ?? null))"
               ".catch(e => JSON.stringify({__error: e.response ? e.response.status : String(e.message || e)}))")
    d = json.loads(r) if r else None
    if isinstance(d, dict) and "__error" in d:
        log.warning("perekrestok %s %s: %s", method, path[:120], d["__error"])
    return d


def _rub(k):
    return round(k / 100, 2) if isinstance(k, (int, float)) else None


def _plu(id_or_url):
    m = re.search(r"-(\d+)/?(?:\?|$|/reviews)", str(id_or_url)) or re.fullmatch(r"\s*(?:plu)?(\d+)\s*", str(id_or_url))
    if not m:
        raise ValueError("нужен plu Перекрёстка или ссылка https://www.perekrestok.ru/cat/<раздел>/p/<название>-<plu>")
    return m.group(1)


def _url(p):
    md = p.get("masterData") or {}
    cat = (p.get("catalogPrimaryCategory") or p.get("primaryCategory") or {}).get("id")
    return f"{SITE}/cat/{cat}/p/{md.get('slug')}-{md.get('plu')}" if cat and md.get("slug") else f"{SITE}/cat/search?search={md.get('plu', '')}"


def _size(md):
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
    form = _call(tab, "post", "/catalog/search/form", {"filter": {"textQuery": query}, "disableBubbleUp": True, "sortByAlpha": True}) or {}
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
        flt, note = {"textQuery": query}, ""
        if tag:
            hit = next((v for t, v in facets.items() if tag.lower() in t.lower()), None)
            if hit:
                flt["features"] = [{"key": hit[0], "value": hit[1]}]
            else:
                note = f"фильтра «{tag}» у Перекрёстка для этого запроса нет — искал «{query} {tag}» текстом"
                flt["textQuery"] = f"{query} {tag}"
        order, direction = SORT[sort]
        body = {"page": page, "perPage": min(max(limit, 12), 48), "filter": flt, "withBestProductReviews": False}
        if sort != "popular":
            body.update(orderBy=order, orderDirection=direction)
        d = _call(tab, "post", "/catalog/product/feed", body)
        if tag and flt.get("features"):
            total = (_call(tab, "post", "/catalog/search/form", {"filter": flt, "disableBubbleUp": True, "sortByAlpha": True}) or {}).get("productCount")
    finally:
        tab.close()
    if not isinstance(d, dict) or "items" not in d:
        return BLOCKED
    pag = d.get("paginator") or {}
    if pag.get("nextPageExists"):
        note += ("\n" if note else "") + f"есть следующая страница: page={page + 1}"
    q = {"search": query, **({"orderBy": order, "orderDirection": direction} if sort != "popular" else {}), **({"page": page} if page > 1 else {})}
    diet = [t for t in facets if facets[t][0] == "osobennosti"]
    kinds = [t for t in facets if facets[t][0] != "osobennosti"]
    return {"items": [_listed(p) for p in d["items"]][:limit], "total": total, "note": note,
            "facets": diet + kinds[:25], "url": f"{SITE}/cat/search?" + urllib.parse.urlencode(q)}


def _feature(p, title=None, key=None):
    for f in p.get("features") or []:
        for it in f.get("items") or []:
            if (title and f.get("title") == title) or (key and it.get("key") == key):
                if key is None or it.get("key") == key:
                    return it
    return None


def product(id_or_url):
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        p = _call(tab, "get", f"/catalog/product/plu{plu}")
        delivery = _call(tab, "get", "/delivery/switcher") or {}
    finally:
        tab.close()
    if not isinstance(p, dict) or "masterData" not in p:
        return BLOCKED if not isinstance(p, dict) or p.get("__error") not in (404,) else f"Перекрёсток: товар {plu} не найден"
    nut = {}
    for f in p.get("features") or []:
        if "Пищевая ценность" in (f.get("title") or ""):
            for it in f.get("items") or []:
                k = {"kkal": "kcal", "belki": "protein", "jiry": "fat", "uglevody": "carbs"}.get(it.get("key"))
                v = (it.get("values") or [None])[0]
                if k and v not in (None, ""):
                    nut[k] = round(float(v) / 1000, 2)
    comp = ((_feature(p, key="sostav") or {}).get("values") or [""])[0]
    brand = ((_feature(p, key="brand") or {}).get("displayValues") or [""])[0]
    info = []
    for f in p.get("features") or []:
        if f.get("title") in ("Состав",) or "Пищевая ценность" in (f.get("title") or ""):
            continue
        for it in f.get("items") or []:
            if it.get("key") != "brand" and it.get("displayValues"):
                info.append(f"{it.get('title') or it.get('key')}: {', '.join(it['displayValues'])}")
    pt = p.get("priceTag") or {}
    extra = []
    if pt.get("labels"):
        extra.append("акции: " + "; ".join(x.get("text", "") for x in pt["labels"] if x.get("text")))
    if p.get("medianPrice"):
        extra.append(f"обычная цена (медиана): {_rub(p['medianPrice'])} ₽")
    tabs = [f"{t.get('title') or t.get('type')}: {t.get('costString') or (str(_rub(t.get('cost'))) + ' ₽')}, "
            f"{(t.get('congestion') or {}).get('deliveryRange') or ''}".strip(", ")
            + (f", заказ от {_rub(t['minCost'])} ₽" if t.get("minCost") else "") for t in delivery.get("tabs") or [] if t.get("type") != "catalog"]
    if tabs:
        extra.append("доставка на адрес из профиля: " + "; ".join(tabs))
    if info:
        extra.append("характеристики: " + "; ".join(info))
    imgs = [i["cropUrlTemplate"].replace("%s", "800x800-fit") for i in p.get("images") or [] if i.get("cropUrlTemplate")]
    out = _listed(p)
    out.update(brand=brand, url=_url(p), photos=imgs, description=p.get("description") or "", composition=comp,
               nutrition=nut, reviews=p.get("reviewCount") or p.get("ratingCount"),
               composition_extra="; ".join(x for x in info if re.search(r"какао|мяс|сок|жирн|шоколад", x, re.I)), extra=extra)
    return out


SORTS = {"useful": {}, "new": {}, "high": {"ratingFrom": 500, "ratingTo": 500}, "low": {"ratingFrom": 100, "ratingTo": 200}}


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=40):
    """The site shows reviews newest first, without sorting; high / low are its star filters (5★, 1–2★)."""
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    plu = _plu(id_or_url)
    q = urllib.parse.urlencode({"page": page, "perPage": limit, **SORTS[sort]})
    tab = _tab()
    try:
        cnt = _call(tab, "get", f"/catalog/product/plu{plu}/review/count") or {}
        d = _call(tab, "get", f"/catalog/product/plu{plu}/review?{q}") or {}
    finally:
        tab.close()
    rows = []
    for x in d.get("items") or []:
        photos = [i["cropUrlTemplate"].replace("%s", "800x800-fit") for i in x.get("approvedImages") or [] if i.get("cropUrlTemplate")]
        if with_media and not photos:
            continue
        ts = x.get("createdAt")
        if isinstance(ts, (int, float)) and ts > 1e11:   # milliseconds
            ts /= 1000
        date = time.strftime("%Y-%m-%d", time.localtime(ts)) if isinstance(ts, (int, float)) else str(ts or "")[:10]
        rows.append(f"{date}\t{(x.get('rating') or 0) / 100:g}\t{x.get('username') or ''}\t"
                    f"{' '.join((x.get('comment') or '').split())}\t{' '.join(photos)}")
    stars = " ".join(f"{i}★ {cnt.get(w, 0)}" for i, w in ((5, "five"), (4, "four"), (3, "three"), (2, "two"), (1, "one")))
    head = (f"Перекрёсток · plu {plu}: отзывов {cnt.get('total', '?')} · {stars}\n"
            f"страница {page} по {limit}, " + {"useful": "новые сверху (другой сортировки у сайта нет)", "new": "новые сверху",
                                                "high": "только 5★", "low": "только 1–2★"}[sort]
            + (", только с фото — из этой страницы" if with_media else "")
            + ("; есть ещё: page=" + str(page + 1) if (d.get("paginator") or {}).get("nextPageExists") else "")
            + "\nдата\t★\tавтор\tтекст\tфото (shop_images)")
    return head + "\n" + ("\n".join(rows) if rows else "(отзывов нет)")


def cart():
    tab = _tab()
    try:
        d = _call(tab, "get", "/basket") or {}
    finally:
        tab.close()
    items = d.get("items") or []
    if not items:
        return "корзина Перекрёстка пуста"
    rows = [f"{(i.get('product') or {}).get('masterData', {}).get('plu', '')}\t{i.get('quantity', '')}\t{_rub(i.get('price'))}\t{_rub(i.get('cost'))}\t"
            f"{(i.get('product') or {}).get('title', '')}\t{'' if (i.get('product') or {}).get('balanceState') != 'sold-out' else 'нет в наличии'}"
            for i in items]
    return ("корзина Перекрёстка" + (f", итого {_rub(d['totalCost'])} ₽" if d.get("totalCost") else "")
            + "\nplu\tшт\tцена ₽\tсумма ₽\tназвание\tналичие\n" + "\n".join(rows))


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
        pid, title = _product_id(tab, plu)
        b = None
        for _ in range(max(1, min(int(quantity), 30))):          # the site's own «+»: one unit per call
            b = _call(tab, "put", f"/basket/plu{plu}/plus")
            if not isinstance(b, dict) or "__error" in b:
                return f"Перекрёсток не положил {title}: {b.get('__error') if isinstance(b, dict) else b}"
    finally:
        tab.close()
    it, state = _line(b, plu)
    if not it:
        return f"Перекрёсток: {title} в корзине не появился (нет в наличии?)"
    return (f"в корзине Перекрёстка: {title} — {it.get('quantity')} шт × {_rub(it.get('price'))} ₽ = {_rub(it.get('cost'))} ₽"
            + (f"\n{state}" if state else ""))


def remove_from_cart(id_or_url):
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        pid, title = _product_id(tab, plu)
        b = _call(tab, "get", "/basket") or {}
        if not _line(b, plu)[0]:
            return f"{title} в корзине Перекрёстка нет"
        _call(tab, "delete", f"/basket/item/{pid}")
        left = _line(_call(tab, "get", "/basket") or {}, plu)[0]
    finally:
        tab.close()
    return f"не удалось убрать {title} из корзины Перекрёстка" if left else f"убрано из корзины Перекрёстка: {title}"


def favorites():
    tab = _tab()
    try:
        d = _call(tab, "get", "/user/liked-product?page=1&perPage=100") or {}
    finally:
        tab.close()
    rows = [_listed(x["product"]) for x in d.get("items") or [] if x.get("product")]
    if not rows:
        return "избранное Перекрёстка пусто"
    return "избранное Перекрёстка\nplu\tцена ₽\tналичие\tназвание\n" + "\n".join(
        f"{r['id']}\t{r['price']}\t{'' if r['available'] else 'нет в наличии'}\t{r['name']}" for r in rows)


def favorite(id_or_url, remove=False):
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        pid, title = _product_id(tab, plu)
        r = _call(tab, "delete" if remove else "post", f"/user/liked-product/{pid}")
    finally:
        tab.close()
    if isinstance(r, dict) and "__error" in r:
        return f"Перекрёсток не изменил избранное: {r['__error']}"
    return f"{'убрано из избранного' if remove else 'в избранном'} Перекрёстка: {title}"
