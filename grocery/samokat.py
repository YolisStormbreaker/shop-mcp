"""Самокат (samokat.ru): the site's own RTK Query endpoints, dispatched in its open page.

The API (api-web.samokat.ru) wants a bearer token and device headers that the site's base query adds, and the
site's bot check (ServicePipe, /xpvnsulc/) fires after a handful of page loads — even client-side route changes
count (2026-10-13). So we do not navigate at all: in the already open samokat.ru page we take the site's RTK
Query api object and Redux store and dispatch its endpoints (searchProducts, productByIdOrSlug, cart…); the
site's own code adds the headers. Cart changes go through its own «cart/scheduleCartSync» thunk with the whole
cart, as its «+» button does. Modules are found by their code, not by ids, which change with every build.
Prices are kopecks, for the user's address (one dark store, «showcase»). No reviews, ratings or favorites.
"""
import json
import re

from cdp import tab_for
from shoplog import log

SITE = "https://samokat.ru"
CHECK = "/xpvnsulc/"
BLOCKED = ("⚠️ Самокат показал проверку на бота: попроси пользователя выполнить shop-chrome show, пройти её "
           "во вкладке samokat.ru, потом shop-chrome hide.")
SETUP_JS = r"""(() => {
  if (window.__shopStore && window.__shopApi && window.__shopSync) return true;
  let req; (window.webpackChunk_N_E || []).push([[Symbol('shop-mcp')], {}, r => { req = r }]);
  if (!req) return false;
  const src = id => String(req.m[id]);
  const apiMod = Object.keys(req.m).find(id => /reducerPath:"api"/.test(src(id)));
  const api = apiMod && Object.values(req(apiMod)).find(v => v && v.endpoints && v.injectEndpoints);
  const syncMod = Object.keys(req.m).find(id => src(id).includes('"cart/scheduleCartSync"'));
  const sync = syncMod && Object.values(req(syncMod)).find(v => v && v.typePrefix === 'cart/scheduleCartSync');
  const root = document.getElementById('__next');
  const key = root && Object.keys(root).find(k => k.startsWith('__reactContainer$'));
  let store = null; const stack = key ? [root[key]] : [];
  for (let n = 0; stack.length && n < 50000; n++) { const f = stack.pop(); if (!f) continue;
    const p = f.memoizedProps; if (p && p.store && typeof p.store.getState === 'function') { store = p.store; break }
    if (f.child) stack.push(f.child); if (f.sibling) stack.push(f.sibling); }
  if (!api || !store || !sync) return false;
  window.__shopApi = api; window.__shopStore = store; window.__shopSync = sync;
  return true;
})()"""
# one endpoint call; args may say SC for the showcase id the page itself uses
CALL_JS = r"""(async (name, args) => {
  const store = window.__shopStore, api = window.__shopApi;
  const qs = Object.values(store.getState().api.queries || {});
  const sc = (qs.find(e => e.endpointName === 'showcaseSettings' || e.endpointName === 'categoriesList') || {}).originalArgs;
  const showcaseId = typeof sc === 'string' ? sc : sc && sc.showcaseId;
  const a = JSON.parse(JSON.stringify(args).replace(/"SC"/g, JSON.stringify(showcaseId || '')));
  const sub = store.dispatch(api.endpoints[name].initiate(a, {forceRefetch: true}));
  const r = await sub; sub.unsubscribe && sub.unsubscribe();
  return r.error ? {__error: r.error.status || String(r.error.message || r.error).slice(0, 200)} : {data: r.data};
})"""
# the cart as the site keeps it, changed to qty for one product and synced by the site's own thunk
SET_JS = r"""(async (pid, qty) => {
  const store = window.__shopStore, api = window.__shopApi;
  const prev = store.getState().cart.previewItems || {};
  const map = {...prev};
  map[pid] = {...(prev[pid] || {id: pid, type: 'PRODUCT', prices: {}}), id: pid, quantity: qty};
  await store.dispatch(window.__shopSync({changes: null, previewItemMap: map})).unwrap();
  return true;
})"""


LOADED = "!!window.webpackChunk_N_E && document.readyState === 'complete'"


def _checked(tab):
    return CHECK in (tab.js("location.href") or "")


def _tab():
    tab = tab_for("samokat.ru")
    if _checked(tab):           # maybe a stale page from session restore: try once
        tab.goto(SITE + "/", "samokat", wait_js=LOADED + " || location.href.includes('/xpvnsulc/')")
        if _checked(tab):
            tab.close()
            return None
    if not tab.js("location.hostname.endsWith('samokat.ru')") or not tab.js(SETUP_JS):
        tab.goto(SITE + "/", "samokat", wait_js=LOADED)   # one page load
        if _checked(tab) or not tab.js(SETUP_JS):
            tab.close()
            return None
    return tab


def _call(tab, name, args):
    r = tab.js(f"{CALL_JS}({json.dumps(name)}, {json.dumps(args, ensure_ascii=False)})", timeout=40) or {}
    if "__error" in r:
        log.warning("samokat %s: %s", name, r["__error"])
        return None
    return r.get("data")


def _norm(s):
    return (s or "").lower().replace("ё", "е").strip()


def _rub(k):
    return round(k / 100, 2) if isinstance(k, (int, float)) else None


def _listed(p):
    return {"id": p.get("slug") or p.get("id"), "name": p.get("name", ""), "brand": "", "size": "",
            "price": _rub(p.get("price")), "old": _rub(p.get("oldPrice")), "available": bool(p.get("isAvailable", (p.get("quantity") or 0) > 0)),
            "url": f"{SITE}/product/{p.get('slug') or p.get('id')}", "rating": None, "reviews": None, "ean": None}


def search(query, tag=None, sort="popular", page=1, limit=30):
    tab = _tab()
    if tab is None:
        return BLOCKED
    try:
        cats = _call(tab, "categoriesList", "SC") or []
        hit = _sections(cats, tag)
        found = _in_sections(tab, hit, tag, query) if hit else _by_text(tab, query, tag)
    finally:
        tab.close()
    return BLOCKED if found is None else _result(*found, _diet(cats), sort, page, limit)


def _diet(cats):
    """Diet tags are categories of the user's showcase («Без лактозы» under «ЗОЖ и веганство», in «Молочное»…)."""
    return sorted({c["name"] for c in cats if re.search(r"^без |веган|растит|глютен|лактоз|сахар|протеин|чистый состав", c.get("name", ""), re.I)})


def _sections(cats, tag):
    return [c for c in cats if _norm(tag) in _norm(c.get("name"))] if tag else []


def _in_sections(tab, hit, tag, query):
    """(products of the tag's categories whose names have the query's words, note, query)"""
    # the tree has no products: each category's own call lists them
    answers = [_call(tab, "categoryByIdOrSlug", {"categoryIdOrSlug": c.get("slug") or c["id"], "filters": {}, "limit": 100})
               for c in hit[:8]]
    ids = list(dict.fromkeys(i for a in answers for i in _ids(a or {})))
    got = _call(tab, "productsByIds", {"showcaseId": "SC", "productIds": ids[:200]}) if ids else []
    if got is None or all(a is None for a in answers):
        return None                      # requests failed (the bot check), not an empty shelf
    return (_named(got, query),
            f"разделы Самоката «{tag}» ({len(hit)})" + (f", названия со словами «{query}»" if (query or "").split() else ""), query)


def _ids(d):
    """One category's product ids: its subcategories' breadth first, then its own products."""
    ids, stack = [], list(d.get("categories") or [])
    while stack:
        x = stack.pop(0)
        ids += x.get("productIds") or []
        stack += x.get("children") or []
    return ids + [p.get("id") for p in d.get("products") or []]


def _named(got, query):
    """The products (the answer may hold other things) whose names have each query word's first 5 letters."""
    words = [w[:5].lower() for w in (query or "").split()]
    return [p for p in got if isinstance(p, dict) and all(w in (p.get("name") or "").lower() for w in words)]


def _by_text(tab, query, tag):
    """(products the site's search finds, note, the query searched), None when it does not answer"""
    note = ""
    if tag:
        note, query = f"раздела «{tag}» у Самоката нет — искал «{query} {tag}» текстом", f"{query} {tag}".strip()
    d = _call(tab, "searchProducts", {"query": query, "showcaseId": "SC"})
    return None if d is None else ([x for x in d if x.get("type") == "PRODUCT"], note, query)


SORT_KEYS = {"price": lambda x: x["price"] or 1e9, "price_desc": lambda x: -(x["price"] or 0),
             "discount": lambda x: (x["price"] or 0) / (x["old"] or x["price"] or 1), "rating": lambda x: 0}


def _result(items, note, query, facets, sort, page, limit):
    rows = [_listed(p) for p in items]
    if sort != "popular":
        rows.sort(key=SORT_KEYS[sort])
        note += ("\n" if note else "") + "Самокат не сортирует: отсортированы полученные товары"
    start = (page - 1) * limit
    return {"items": rows[start:start + limit], "total": len(rows), "note": note.strip(), "facets": facets,
            "url": SITE + "/search?value=" + re.sub(r"\s+", "+", query or "")}


def _slug(id_or_url):
    s = str(id_or_url).strip()
    m = re.search(r"/product/([\w-]+)", s)
    return m.group(1) if m else s


def _num(s):
    m = re.search(r"\d+(?:[.,]\d+)?", str(s or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def product(id_or_url):
    slug = _slug(id_or_url)
    tab = _tab()
    if tab is None:
        return BLOCKED
    try:
        c = _call(tab, "productByIdOrSlug", {"showcaseId": "SC", "productIdOrSlug": slug})
    finally:
        tab.close()
    if not c:
        return f"Самокат: товар {slug} не найден на витрине для адреса пользователя"
    return _card(c)


def _card(c):
    attrs = c.get("attributes") or {}
    info = _info(attrs)
    p = _listed(c)
    p.update(brand=attrs.get("Бренд") or "", size=_size(attrs), photos=_photos(c),
             description=re.sub(r"\s+", " ", _untag(c.get("description") or "")).strip(),
             composition=str(attrs.get("Состав") or ""), nutrition=_nutrition(c.get("nutritions") or {}),
             composition_extra="; ".join(x for x in info if re.search(r"жирн|какао|мяс|сок|без |сахар", x, re.I)), extra=_extra(c, info))
    return p


def _untag(s):
    return re.sub(r"<[^>]+>", " ", s)


SIZES = ("Объём", "Вес", "Масса", "Количество в упаковке")


def _size(attrs):
    return next((f"{v}" for k, v in attrs.items() if k in SIZES), "")


SHOWN = {"Состав", "Бренд", "Примечание", "Документы качества"}
FLAGS = {"TRUE": "да", "FALSE": "нет"}


def _info(attrs):
    """The card's characteristics as «name: value», without what the card shows elsewhere and whole-pack totals."""
    return [f"{k}: {FLAGS.get(str(v).upper()) or _untag(str(v)).strip()}" for k, v in attrs.items()
            if k not in SHOWN and "на весь продукт" not in k]


NUTRIENTS = (("kcal", "kilocalories"), ("protein", "protein"), ("fat", "fats"), ("carbs", "carbohydrates"))


def _nutrition(n):
    return {k: _num(n.get(src)) for k, src in NUTRIENTS if _num(n.get(src)) is not None}


def _extra(c, info):
    return [x for x in ("доставка: ~15 мин из ближайшего склада Самоката (условия сайта для адреса пользователя)",
                        c.get("quantity") and f"на складе {c['quantity']} шт",
                        c.get("discountPercent") and f"скидка {c['discountPercent']}%",
                        info and "характеристики: " + "; ".join(info)) if x]


def _photos(c):
    return [m["url"].split("?")[0] for m in c.get("media") or [] if m.get("url")]


def _cart(tab):
    args = tab.js("(Object.values(window.__shopStore.getState().api.queries).find(e => e.endpointName === 'cart') || {}).originalArgs || null")
    if not args:
        args = {"showcaseId": "SC", "buyout": False}
    d = _call(tab, "cart", args) or {}
    return {str(x.get("id")): x for x in d.get("products") or []}, d


def _qty(tab, pid):
    return ((_cart(tab)[0]).get(pid) or {}).get("quantity") or 0


def _set(tab, pid, qty):
    tab.js(f"{SET_JS}({json.dumps(pid)}, {int(qty)})", timeout=40)
    return _qty(tab, pid)


def _uuid(tab, id_or_url):
    """The cart wants the product's uuid; search gives slugs."""
    s = _slug(id_or_url)
    if re.fullmatch(r"[0-9a-f-]{36}", s):
        return s, s
    c = _call(tab, "productByIdOrSlug", {"showcaseId": "SC", "productIdOrSlug": s}) or {}
    return c.get("id"), c.get("name") or s


def cart():
    tab = _tab()
    if tab is None:
        return BLOCKED
    try:
        items, d = _cart(tab)
    finally:
        tab.close()
    if not items:
        return "корзина Самоката пуста"
    return (f"корзина Самоката: итого {_rub(d.get('totalPrice'))} ₽\nid\tшт\tцена ₽\tназвание\n"
            + "\n".join(f"{(x.get('product') or {}).get('slug') or i}\t{x.get('quantity')}\t{_rub(x.get('price'))}\t{(x.get('product') or {}).get('name') or ''}"
                        for i, x in items.items()))


def add_to_cart(id_or_url, quantity=1):
    tab = _tab()
    if tab is None:
        return BLOCKED
    try:
        pid, name = _uuid(tab, id_or_url)
        if not pid:
            return f"Самокат: товар {id_or_url} не найден на витрине для адреса пользователя"
        start = _qty(tab, pid)
        n = _set(tab, pid, start + max(1, min(int(quantity), 30)))
    finally:
        tab.close()
    if n <= start:
        return f"Самокат не положил «{name}» в корзину (нет на складе?)"
    return f"в корзине Самоката: {name} — {n} шт"


def remove_from_cart(id_or_url):
    tab = _tab()
    if tab is None:
        return BLOCKED
    try:
        pid, name = _uuid(tab, id_or_url)
        if not pid or not _qty(tab, pid):
            return f"«{name}» в корзине Самоката нет"
        left = _set(tab, pid, 0)
    finally:
        tab.close()
    return f"не удалось убрать «{name}» из корзины Самоката" if left else f"убрано из корзины Самоката: {name}"
