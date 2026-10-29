"""ВкусВилл (vkusvill.ru): the store's public catalog API for search and cards, the user's tab for the rest.

VkusVill runs a public MCP server (https://mcp.vkusvill.ru/mcp, stateless JSON-RPC, no auth for the catalog,
60 calls a minute). It is the only place with sugar («в том числе сахара», even added sugar) and its prices
matched the logged-in site in every sample (2026-10-13), so search and cards come from it over plain HTTPS —
shop-mcp calls it itself, no MCP connector to install. Stock at the user's address, reviews, cart and favorites
are the site's, read in the logged-in tab (cookies), with the site's own buttons for the cart.
"""
import json
import math
import re
import time
import urllib.parse
import urllib.request

from cdp import site_tab
from shoplog import log

from .composition import nutrition_from_text

MCP = "https://mcp.vkusvill.ru/mcp"
SITE = "https://vkusvill.ru"
SORT = {"popular": "popularity", "price": "price_asc", "price_desc": "price_desc", "rating": "rating", "discount": "popularity"}
# site filters of the search page (F[DEF_n]); the rest of the diet tags are category facets, searched as text
DEF = {"веган": 5, "без добавленного сахара": 6, "без сахара": 6, "только вкусвилл": 3}


def _mcp(tool, args, retried=False):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}).encode()
    # its anti-bot answers 403 to the default «Python-urllib» agent (any other name passes, 2026-10-13)
    req = urllib.request.Request(MCP, data=body, headers={"Content-Type": "application/json", "User-Agent": "shop-mcp/1.0",
                                                          "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 429 and not retried:            # 60 calls a minute
            time.sleep(min(int(e.headers.get("X-RateLimit-Reset") or 20), 60))
            return _mcp(tool, args, True)
        raise RuntimeError(f"ВкусВилл API: HTTP {e.code}") from e
    if raw.startswith("event:") or "\ndata:" in raw:    # an SSE answer: take its data line
        raw = next(l[5:] for l in raw.splitlines() if l.startswith("data:"))
    d = json.loads(raw)
    res = json.loads(d["result"]["content"][0]["text"])
    if not res.get("ok"):
        raise RuntimeError(f"ВкусВилл API: {res.get('error')}")
    return res["data"]


def _clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", (s or "").replace("&nbsp;", " ").replace("&quot;", '"'))).strip()


def _size(p):
    w = p.get("weight") or {}
    if w.get("value"):
        v = float(w["value"])
        return f"{v:g} {w.get('unit')}" if w.get("unit") != "кг" or v >= 1 else f"{v * 1000:g} г"
    return "1 кг" if p.get("unit") == "кг" else ""      # sold by weight: the price is per kilogram


def _listed(p):
    pr, rt = p.get("price") or {}, p.get("rating") or {}
    return {"id": str(p["id"]), "name": _clean(p.get("name")), "brand": p.get("brand") or "", "size": _size(p),
            "price": pr.get("current"), "old": pr.get("old"), "available": True,
            "url": p.get("url") or f"{SITE}/goods/{p.get('slug', 'x')}-{p['id']}/",
            "rating": rt.get("average") and round(rt["average"], 2), "reviews": rt.get("count"), "ean": None}


def _tab():
    return site_tab("vkusvill.ru", SITE + "/", "vkusvill")


# Stock is per delivery address and only in the logged-in site's HTML; fetched in the tab, parsed there.
STOCK_JS = r"""(async (url) => {
  const html = await (await fetch(url, {credentials: 'include'})).text();
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const t = s => (s || '').replace(/\s+/g, ' ').trim();
  const cards = [...doc.querySelectorAll('.ProductCard[data-id]')].map(c => [c.dataset.id, t(c.querySelector('.ProductCard__Rest')?.textContent),
    +(c.querySelector('.js-delivery__basket--add')?.dataset.max ?? -1)]);
  const one = doc.querySelector('.ProductLkRest');
  return {cards, rest: one ? t(one.textContent) : null, max: +(doc.querySelector('.Product__buy .js-delivery__basket--add, .js-delivery__basket--add')?.dataset.max ?? -1),
          delivery: t(doc.querySelector('.HeaderATDToggler._type .HeaderATDToggler__TextInner')?.textContent), authed: doc.querySelector('#bx-user-authed')?.value === 'Y'};
})"""


def _site(url):
    try:
        tab = _tab()
    except Exception as e:
        log.warning("vkusvill tab: %s", e)
        return None
    try:
        return tab.js(f"{STOCK_JS}({json.dumps(url)})", timeout=40)
    except Exception as e:
        log.warning("vkusvill site %s: %s", url, e)
        return None
    finally:
        tab.close()


def _gone(rest, mx):
    return mx == 0 or bool(re.search(r"не остал|нет в наличии|закончил", rest or "", re.I))


FACETS = list(DEF) + ["без глютена", "без лактозы", "мало жира", "много белка"]
SITE_SORT = {"price": "cat_search__CATALOG_3", "price_desc": "cat_search__CATALOG_10", "rating": "cat_search__CATALOG_5"}


def _search_url(q):
    return SITE + "/search/?" + urllib.parse.urlencode(q)


def search(query, tag=None, sort="popular", page=1, limit=30):
    if tag and tag.lower() in DEF:
        return _filtered(query, tag, sort, page, limit)
    note = ""
    if tag:
        note = f"«{tag}» — фильтр разделов сайта, а не поиска: искал «{query} {tag}» текстом"
        query = f"{query} {tag}".strip()
    items, total = _found(query, sort, page, limit)
    url = _search_url({"type": "products", "q": query})
    # stock at the user's address: one look at the site's own search page (first 24 hits)
    if _restock(items, _site(url)):
        note += ("\n" if note else "") + "наличие — для адреса пользователя (по первым 24 товарам сайта)"
    return {"items": items[:limit], "total": total, "note": note.strip(), "facets": list(FACETS), "url": url}


def _found(query, sort, page, limit):
    """The catalog API's hits for this page of `limit` (it gives 10 a call) and its total."""
    n = math.ceil(min(limit, 40) / 10)
    items, total = [], None
    for pg in range((page - 1) * n + 1, page * n + 1):
        d = _mcp("vkusvill_products_search", {"q": query, "page": pg, "limit": 10, "sort": SORT[sort], "vvonly": 0})
        items += [_listed(p) for p in d.get("items") or []]
        meta = d.get("meta") or {}
        total = meta.get("total")
        if not meta.get("has_more"):
            break
    if sort == "discount":
        items.sort(key=lambda x: (x["price"] or 0) / (x["old"] or x["price"] or 1))
    return items, total


def _restock(items, st):
    """Marks the items the site's search page shows as gone; False when the page did not load."""
    if not st:
        return False
    rest = {i: (r, m) for i, r, m in st["cards"]}
    for x in items:
        if x["id"] in rest:
            x["available"] = not _gone(*rest[x["id"]])
    return True


def _filtered(query, tag, sort, page, limit):
    # a site filter: the site's own search page (24 per page), with stock for the user's address
    q = {"type": "products", "q": query, f"F[DEF_{DEF[tag.lower()]}]": 1, "sf4": "Y", "sort": SITE_SORT.get(sort, "cat_search__CATALOG_15")}
    if page > 1:
        q.update(rf4="Y", PAGEN_1=page)
    url = _search_url(q)
    tab = _tab()
    try:
        cards = tab.js(f"""(async (url) => {{ const doc = new DOMParser().parseFromString(await (await fetch(url, {{credentials: 'include'}})).text(), 'text/html');
          const t = s => (s || '').replace(/\\s+/g, ' ').trim();
          return [...doc.querySelectorAll('.ProductCard[data-id]')].map(c => ({{id: c.dataset.id, name: t(c.querySelector('.js-product-v-tizer__title-text')?.textContent),
            size: t(c.querySelector('.ProductCard__linkWeight')?.textContent), price: +t(c.querySelector('.js-datalayer-catalog-list-price')?.textContent).replace(/[^\\d.]/g, ''),
            old: +t(c.querySelector('.js-datalayer-catalog-list-price-old')?.textContent).replace(/[^\\d.]/g, ''), rest: t(c.querySelector('.ProductCard__Rest')?.textContent),
            max: +(c.querySelector('.js-delivery__basket--add')?.dataset.max ?? -1), rating: t(c.querySelector('.ProductCard__ratingText')?.textContent),
            href: c.querySelector('a[href*="/goods/"]')?.getAttribute('href') || ''}})) }})({json.dumps(url)})""", timeout=40) or []
    finally:
        tab.close()
    return {"items": [_site_card(c) for c in cards][:limit], "total": None,
            "note": f"фильтр ВкусВилла «{tag}», наличие — для адреса пользователя", "facets": list(FACETS), "url": url}


def _site_card(c):
    """One card of the site's search page, as the catalog API's hits are listed."""
    return {"id": c["id"], "name": c["name"], "brand": "", "size": c["size"], "price": c["price"] or None,
            "old": c["old"] if c["old"] and c["old"] > (c["price"] or 0) else None, "available": not _gone(c["rest"], c["max"]),
            "url": SITE + c["href"] if c["href"].startswith("/") else c["href"], "rating": c["rating"] or None, "reviews": None, "ean": None}


def _id(id_or_url):
    m = re.search(r"-(\d+)/?(?:\?|$)", str(id_or_url)) or re.fullmatch(r"\s*(\d+)\s*", str(id_or_url))
    if not m:
        raise ValueError("нужен id товара ВкусВилла или ссылка https://vkusvill.ru/goods/<название>-<id>/")
    return m.group(1)


def product(id_or_url):
    d = _mcp("vkusvill_product_details", {"id": int(_id(id_or_url))})
    p = _listed(d)
    return _card(p, d, _site(p["url"]))


def _card(p, d, st):
    props = {_clean(x.get("name")): x.get("value") or "" for x in d.get("properties") or []}
    parts, nut_raw = _compositions(_prop(props, "Состав")), _prop(props, "Пищевая")
    if st:
        p["available"] = not _gone(st.get("rest"), st.get("max"))
    p.update(photos=[i.get("large") for i in d.get("images") or [] if i.get("large")], description=_clean(d.get("description")),
             composition=parts[0] if parts else "", nutrition=nutrition_from_text(_clean(nut_raw)),
             composition_extra=_clean(nut_raw) if "сахар" in nut_raw.lower() else "",
             extra=[x for x in (_discount(d), _stock(st), _suppliers(parts), *_facts(props)) if x])
    return p


def _prop(props, name):
    return next((v for k, v in props.items() if k.startswith(name)), "")


def _compositions(raw):
    # «<Supplier>:<text>;<br>[<Supplier2>:…]» — one composition per supplier
    return [re.sub(r"^[^:]{2,80}?:", "", _clean(x), count=1).strip(" ;") for x in re.split(r"<br\s*/?>", raw) if _clean(x)]


def _suppliers(parts):
    """The card keeps the first supplier's composition and mentions the others."""
    return len(parts) > 1 and f"поставщиков {len(parts)}, у остальных состав: " + " || ".join(parts[1:])[:600]


def _discount(d):
    pr = d.get("price") or {}
    if not (pr.get("discount_info") or pr.get("discount_percent")):
        return ""
    return f"скидка {pr.get('discount_percent') or ''}% {_clean(pr.get('discount_info'))}".strip()


def _stock(st):
    return st and "на адрес пользователя: " + (st.get("rest") or "наличие не указано") + (f"; доставка: {st['delivery']}" if st.get("delivery") else "")


FACTS = ("Аллергены по производителям", "Срок годности", "Страна производства", "Изготовитель")


def _facts(props):
    return [f"{k}: {_clean(v)[:200]}" for k in FACTS if (v := _prop(props, k))]


REVIEW_SORTS = {"useful": "pr__likes_max", "new": "pr__comment_new", "high": "pr__rating_max", "low": "pr__rating_min"}
REVIEWS_JS = r"""(async (url) => {
  const r = await (await fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'include'})).json();
  const doc = new DOMParser().parseFromString(r.html || '', 'text/html');
  const t = s => (s || '').replace(/\s+/g, ' ').trim();
  return {more: !!doc.querySelector('.js-product-api-reviews-load-more'), items: [...doc.querySelectorAll('.ReviewsApiCat4ListItem')].map(e => ({
    rate: t(e.querySelector('.ReviewsApiCat4ListItemRate')?.textContent) || (e.querySelector('[class*=Rate] [class*=_active], [class*=Rate] ._full')?.parentElement?.querySelectorAll('._active, ._full').length || ''),
    date: t(e.querySelector('[class*=CardDate]')?.textContent).split('·')[0].trim(), text: t(e.querySelector('.js-product-api-review-body')?.textContent),
    likes: t(e.querySelector('.js-product-api-reviews-like-count')?.textContent)}))};
})"""


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=10):
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    pid = _id(id_or_url)
    url = SITE + "/ajax/product_comments/from_api/comments_load_page_v3.php?" + urllib.parse.urlencode(
        {"id": pid, "sort": REVIEW_SORTS[sort], "brand": "", "filter": 0, "page": page, "isInited": "N" if page == 1 else "Y"})
    tab = _tab()
    try:
        d = tab.js(f"{REVIEWS_JS}({json.dumps(url)})", timeout=40) or {}
    finally:
        tab.close()
    p = _mcp("vkusvill_product_details", {"id": int(pid)})
    rt = p.get("rating") or {}
    rows = [f"{x['date']}\t{x['rate']}\t{x['likes']}\t{x['text']}" for x in d.get("items") or []]
    return (f"ВкусВилл · {_clean(p.get('name'))}: рейтинг {rt.get('average') and round(rt['average'], 2)} ({rt.get('count')} оценок)\n"
            f"страница {page} по 10, сортировка {sort}; фото в отзывах ВкусВилла нет" + ("; есть ещё: page=" + str(page + 1) if d.get("more") else "")
            + "\nдата\t★\tполезно\tтекст\n" + ("\n".join(rows) if rows else "(отзывов нет)"))


# Cart: read by the site's dropdown endpoint; changed by the site's own buttons (element.click() works in the hidden tab).
CART_JS = r"""(async () => {
  const r = await (await fetch('/ajax/dropdown_basket.php?isInited=N', {headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'include'})).json();
  const m = (r.html || '').match(/basketPageData\s*=\s*JSON\.parse\('([\s\S]*?)'\)/);
  if (!m) return {basket: {}};
  const d = JSON.parse(Function("return '" + m[1] + "'")());
  return {basket: Object.fromEntries(Object.values(d.basket || {}).map(i => [String(i.PRODUCT_ID), {q: +i.Q, price: +i.PRICE, total: +i.TOTAL, name: i.NAME, unit: i.UNIT, can: i.CAN_BUY}])),
          totals: d.totals || {}};
})()"""


def _cart(tab):
    return tab.js(CART_JS, timeout=40) or {"basket": {}}


def cart():
    tab = _tab()
    try:
        c = _cart(tab)
    finally:
        tab.close()
    if not c["basket"]:
        return "корзина ВкусВилла пуста"
    return ("корзина ВкусВилла\nid\tкол-во\tцена ₽\tсумма ₽\tназвание\n"
            + "\n".join(f"{i}\t{x['q']:g} {x['unit'] or ''}\t{x['price']}\t{x['total']}\t{x['name']}{'' if x['can'] in (True, 'Y', 'true') else ' — нельзя купить'}"
                        for i, x in c["basket"].items()))


def _q(tab, pid):
    return (_cart(tab)["basket"].get(str(pid)) or {}).get("q") or 0


def _click(tab, sel, pid, before, js=None):
    """Click (by selector, or by a JS expression giving the element) and wait until the cart shows a new quantity."""
    el = js or f"document.querySelector({json.dumps(sel)})"
    if not tab.js(f"(() => {{ const b = {el}; if (!b) return false; b.click(); return true }})()"):
        return False
    for _ in range(14):
        time.sleep(0.5)
        if _q(tab, pid) != before:
            return True
    return True


def add_to_cart(id_or_url, quantity=1):
    pid = _id(id_or_url)
    tab = _tab()
    try:
        tab.goto(f"{SITE}/goods/x-{pid}/", "vkusvill", wait_js="!!document.querySelector('.js-delivery__basket--add')")
        time.sleep(1.5)
        name = tab.js("document.querySelector('h1')?.innerText || ''")
        start = _q(tab, pid)
        add = f".js-delivery__basket--add[data-id='{pid}'], .js-delivery__basket--add[data-xmlid='{pid}']"
        # «+» has no data of its own: it sits next to the product's add button, in the same CartButton block
        plus = f"(document.querySelector({json.dumps(add)})?.closest('.CartButton, [class*=CartButton]:not([class*=CartButton__])') || document).querySelector('.Q_Up')"
        for i in range(max(1, min(int(quantity), 30))):
            first = i == 0 and not start
            if not _click(tab, add, pid, _q(tab, pid), None if first else plus):
                break
        n = _q(tab, pid)
    finally:
        tab.close()
    if n <= start:
        return f"ВкусВилл не положил «{name}» в корзину (нет в наличии на адрес пользователя?)"
    return f"в корзине ВкусВилла: {name} — {n:g}"


def remove_from_cart(id_or_url):
    pid = _id(id_or_url)
    tab = _tab()
    try:
        tab.goto(f"{SITE}/cart/", "vkusvill", wait_js="document.readyState === 'complete'")
        time.sleep(1.5)
        row = f".js-delivery__basket--row[data-product-id='{pid}']"
        for _ in range(40):
            q = _q(tab, pid)
            if not q or not _click(tab, f"{row} .Q_Down", pid, q):
                break
        time.sleep(5)                    # the site removes a line 4 s after its last «−» (undo window)
        left = _q(tab, pid)
    finally:
        tab.close()
    return f"не удалось убрать товар {pid} из корзины ВкусВилла" if left else f"убрано из корзины ВкусВилла: {pid}"


FAV_JS = r"""(async () => {
  const doc = new DOMParser().parseFromString(await (await fetch('/favorites/?tab=products', {credentials: 'include'})).text(), 'text/html');
  const t = s => (s || '').replace(/\s+/g, ' ').trim();
  return [...doc.querySelectorAll('.ProductCard[data-id]')].map(c => ({id: c.dataset.id, name: t(c.querySelector('.js-product-v-tizer__title-text')?.textContent),
    price: t(c.querySelector('.js-datalayer-catalog-list-price')?.textContent), rest: t(c.querySelector('.ProductCard__Rest')?.textContent)}));
})()"""


def favorites():
    tab = _tab()
    try:
        items = tab.js(FAV_JS, timeout=40) or []
    finally:
        tab.close()
    if not items:
        return "избранное ВкусВилла пусто"
    return "избранное ВкусВилла\nid\tцена ₽\tналичие\tназвание\n" + "\n".join(f"{x['id']}\t{x['price']}\t{x['rest']}\t{x['name']}" for x in items)


def favorite(id_or_url, remove=False):
    """The site's own favorites call (a cookie-session form POST without a token) — the same the heart button sends."""
    pid = _id(id_or_url)
    tab = _tab()
    try:
        r = tab.js(f"""fetch('/ajax/favorites/add-remove.php', {{method: 'POST', credentials: 'include',
            headers: {{'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest'}},
            body: new URLSearchParams({{id: {json.dumps(pid)}, xmlid: {json.dumps(pid)}, command: {json.dumps('remove' if remove else 'add')}, notNeedHtml: 'false'}})}})
            .then(async r => ({{s: r.status, b: (await r.text()).slice(0, 300)}}))""")
        ids = [x["id"] for x in tab.js(FAV_JS, timeout=40) or []]
    finally:
        tab.close()
    if (pid in ids) == remove:
        log.warning("vkusvill favorite %s %s: %s", pid, remove, r)
        return "ВкусВилл не изменил избранное"
    return f"{'убрано из избранного' if remove else 'в избранном'} ВкусВилла: {pid}"
