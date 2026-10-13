"""Лента (lenta.com): data the page itself fetches (capture.py), moved around with the site's own router.

The API (/api-gateway/v1) answers 400 to a plain fetch(): the site's interceptor adds the session token and
device headers. So we navigate inside the Angular app (pushState + popstate: no page load) and read the
responses its own requests get. For search the page's own POST /catalog/items is sent with our body (query,
sort, tag, page) through CDP Fetch — the headers stay the page's and are never read. Prices are in kopecks and
for the delivery store the site chose (Гипер Лента or Супер Лента zone of the user's address).
"""
import json
import re
import time
import urllib.parse

from capture import capture
from cdp import tab_for
from shoplog import log

from .composition import nutrition_from_text

SITE = "https://lenta.com"
BLOCKED = "⚠️ Лента не отдала данные (проверка на бота или сайт не загрузился): shop-chrome show, открыть lenta.com, повторить."
NAV_JS = "history.pushState({}, '', %s); dispatchEvent(new PopStateEvent('popstate', {state: {}}))"
ITEMS = "*/api-gateway/v1/catalog/items"
SORT = {"popular": ("popular", "desc"), "price": ("price", "asc"), "price_desc": ("price", "desc"),
        "discount": ("sale", "desc"), "rating": ("rating", "desc")}
# Diet tags are categories at Лента (ids seen 2026-10-13), combined with the text query
DIET = {"без глютена": 221, "без лактозы": 13615, "вегетарианское": 13616, "веган": 13616, "фермерское": 13617,
        "много белка": 24940, "высокий белок": 24940, "диабетическое": 222, "халяль": 22305, "без сахара": 25612,
        "напитки без сахара": 25612, "шоколад без сахара": 17315, "хлеб без глютена": 25609}
ZONES_JS = """(() => { try { const s = JSON.parse(document.getElementById('ng-state').textContent);
  const m = Object.entries(s).find(([k]) => k.includes('/delivery/mode'));
  const d = m && (m[1].b || m[1].body || m[1]);
  return (d && d.zones || []).map(z => ({name: z.name, selected: z.isSelected, time: z.timeDisplay || z.time, min: z.minOrderAmount,
    prices: ((z.deliveryPrice || {}).b2c || []).map(p => [p.price, p.stage])})) } catch (e) { return [] } })()"""


def _tab():
    tab = tab_for("lenta.com")
    if not tab.js("location.hostname === 'lenta.com' && !!document.querySelector('app-root, lu-root, [ng-version]')"):
        tab.goto(SITE + "/", "lenta", wait_js="!!document.querySelector('[ng-version]')")
    return tab


def _nav(tab, path, patterns, rewrite=None, timeout=15):
    """Go to path inside the app and return the page's responses; the same path again would fetch nothing."""
    here = tab.js("location.pathname")
    if path.startswith("/search/") and here.startswith(path):
        # another query string fires the search (paging inside one query does not); the body is ours anyway
        path = path[:-1] + "%20/"
    elif path.startswith("/product/") and here.startswith("/product/") and here.rstrip("/").split("-")[-1] == path.rstrip("/").split("-")[-1]:
        tab.js(NAV_JS % json.dumps("/"))      # the same product id again fetches nothing: leave it first
        time.sleep(1.5)
    got = capture(tab, "lenta", None, patterns, timeout=timeout, rewrite=rewrite, js=NAV_JS % json.dumps(path))
    if len(got) < len(patterns):
        log.warning("lenta %s: got %s of %s", path, list(got), list(patterns))
    return got


def _rub(k):
    return round(k / 100, 2) if isinstance(k, (int, float)) else None


def _listed(p):
    pr, d = p.get("prices") or {}, p.get("display") or {}
    price, regular = _rub(pr.get("price")), _rub(pr.get("priceRegular"))
    weight = (p.get("features") or {}).get("isWeight")
    return {"id": str(p.get("id")), "name": d.get("name") or p.get("name", ""), "brand": "",
            "size": d.get("package") or "" if not weight else f"{(p.get('units') or {}).get('saleUnitQuantity', '')} кг",
            "price": price, "old": regular if regular and price and regular > price else None,
            "available": (p.get("count") or 0) > 0, "url": f"{SITE}/product/{p.get('slug') or 'x'}-{p.get('id')}/",
            "rating": (p.get("rating") or {}).get("rate"), "reviews": (p.get("rating") or {}).get("votes"), "ean": None,
            "_per_kg": _rub(pr.get("cost")) if weight else None}


def _search(tab, query, mc=None, cat=None, sort="popular", limit=40, offset=0):
    body = {"query": query, "filters": {"checkbox": [], "multicheckbox": mc or [], "range": []},
            "sort": {"type": SORT[sort][0], "order": SORT[sort][1]}, "limit": limit, "offset": offset}
    if cat:
        body["categoryId"] = cat
    path = "/search/" + urllib.parse.quote(query or "товары") + "/"
    got = _nav(tab, path, {"s": ["re:/api-gateway/v1/catalog/items$"]}, rewrite=(ITEMS, lambda u: (u, json.dumps(body, ensure_ascii=False))))
    return got.get("s")


def search(query, tag=None, sort="popular", page=1, limit=30):
    limit = min(limit, 40)
    tab = _tab()
    note = ""
    try:
        cat = next((v for k, v in DIET.items() if tag and tag.lower() in k), None) if tag else None
        d = _search(tab, query, cat=cat, sort=sort, limit=limit, offset=(page - 1) * limit)
        if d is None:
            return BLOCKED
        if cat:
            note = f"раздел Ленты «{next(k for k, v in DIET.items() if v == cat)}» + запрос «{query}»"
        elif tag:   # a value of the search's own facets («Сахар: без добавления сахара», «Тип продукта: …»)
            hit = next(((f, v) for f in (d.get("filters") or {}).get("multicheckbox") or [] for v in f.get("values") or []
                        if tag.lower() in str(v.get("value", "")).lower()), None)
            if hit:
                d = _search(tab, query, mc=[{"key": hit[0]["key"], "valueIds": [hit[1]["id"]]}], sort=sort, limit=limit,
                            offset=(page - 1) * limit) or d
                note = f"фильтр Ленты «{hit[0]['name']}: {hit[1]['value']}»"
            else:
                note = f"тега «{tag}» у Ленты для этого запроса нет — искал «{query} {tag}» текстом"
                d = _search(tab, f"{query} {tag}", sort=sort, limit=limit, offset=(page - 1) * limit) or d
    finally:
        tab.close()
    facets = list(DIET)
    for f in (d.get("filters") or {}).get("multicheckbox") or []:
        if f.get("key") not in ("brand", "rating") and f.get("values"):
            facets.append(f"{f['name']}: " + " / ".join(str(v.get("value")) for v in f["values"][:6]))
    rows = [_listed(p) for p in d.get("items") or []]
    for r in rows:
        r.pop("_per_kg")      # a weighed item's price is for its sale step, which is its size
    total = d.get("total")
    if total and total > page * limit:
        note += ("\n" if note else "") + f"есть следующая страница: page={page + 1}"
    return {"items": rows, "total": total, "note": note.strip(), "facets": facets[:40],
            "url": f"{SITE}/search/{urllib.parse.quote(query or '')}/"}


def _id(id_or_url):
    m = re.search(r"-(\d+)/?(?:\?|$)", str(id_or_url)) or re.fullmatch(r"\s*(\d+)\s*", str(id_or_url))
    if not m:
        raise ValueError("нужен id товара Ленты или ссылка https://lenta.com/product/<название>-<id>/")
    return m.group(1)


def product(id_or_url):
    pid = _id(id_or_url)
    tab = _tab()
    try:
        got = _nav(tab, f"/product/x-{pid}/", {"p": [f"re:/api-gateway/v1/catalog/items/{pid}(\\?|$)"]})
        zones = tab.js(ZONES_JS) or []
    finally:
        tab.close()
    c = got.get("p")
    if not c:      # the app keeps a card it has shown and does not fetch it again: a full load has it server-rendered
        tab = _tab()
        try:
            tab.goto(f"{SITE}/product/x-{pid}/", "lenta", wait_js="!!document.getElementById('ng-state')")
            c = tab.js(rf"""(() => {{ const s = JSON.parse(document.getElementById('ng-state').textContent);
                const m = Object.entries(s).find(([k]) => /\/catalog\/items\/{pid}($|[?|])/.test(k));
                return m ? (m[1].b || m[1].body || m[1]) : null }})()""")
            zones = zones or tab.js(ZONES_JS) or []
        finally:
            tab.close()
    if not c or not c.get("id"):
        return f"Лента: карточка {pid} не пришла (неверный id или проверка на бота)"
    attrs = {a.get("id"): a for a in c.get("attributes") or []}
    by_alias = {a.get("alias"): a.get("value") for a in c.get("attributes") or [] if a.get("alias")}
    nutri_text = " ; ".join(str((attrs.get(i) or {}).get("value") or "") for i in (233, 234))   # the two are swapped on some cards
    nut = nutrition_from_text(nutri_text)
    p = _listed(c)
    per_kg = p.pop("_per_kg")
    skip = {232, 233, 234, 238, 242, 84, 236}
    info = [f"{a.get('name')}: {a.get('value')}" for i, a in attrs.items() if i not in skip and a.get("value")]
    extra = []
    disc = [b.get("title") for b in (c.get("badges") or {}).get("discount") or [] if b.get("title")]
    if disc:
        extra.append("скидка " + ", ".join(disc))
    if per_kg:
        extra.append(f"весовой товар: {per_kg} ₽/кг, шаг {(c.get('units') or {}).get('saleUnitQuantity')} кг")
    if c.get("count"):
        extra.append(f"в наличии до {c['count']} шт")
    sel = [z for z in zones if z.get("selected")] or zones
    if sel:
        extra.append("доставка: " + "; ".join(
            f"{z['name']} {z.get('time') or ''}, заказ от {z.get('min')} ₽, доставка " + ", ".join(f"{pr} ₽ от {st} ₽" for pr, st in z.get("prices") or [])
            for z in sel))
    if info:
        extra.append("характеристики: " + "; ".join(info))
    revs = c.get("reviews") or []
    if revs:
        extra.append(f"отзывы (первые {len(revs)}, ещё — grocery_reviews): " + " | ".join(
            f"{r.get('rating')}★ {' '.join((r.get('text') or '').split())[:200]}" for r in revs if r.get("text")))
    p.update(brand=by_alias.get("brand") or "", photos=[i.get("large") or i.get("original") for i in c.get("images") or [] if i.get("large") or i.get("original")],
             description=re.sub(r"<[^>]+>", " ", (attrs.get(242) or {}).get("value") or "").strip(),
             composition=(attrs.get(232) or {}).get("value") or by_alias.get("ingredients") or "", nutrition=nut,
             composition_extra="; ".join(x for x in info if re.search(r"^(Сахар|Содержание|Веганское|Фермерская)", x)), extra=extra)
    return p


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=5):
    """The first five reviews come with the card; the site pages them by five."""
    p = product(id_or_url)
    if isinstance(p, str):
        return p
    line = next((x for x in p.get("extra") or [] if x.startswith("отзывы")), "")
    return (f"Лента · {p['name']}: рейтинг {p.get('rating') or '—'} ({p.get('reviews') or 0} оценок)\n"
            "Лента отдаёт с карточкой 5 последних отзывов; фото в отзывах у Ленты нет\n" + (line or "(отзывов нет)"))


# Cart and favorites: the legacy cart API signs its body with the session token, so we press the page's own
# buttons (element.click() works in the hidden tab) on a fully loaded product page and read the site's answers.
DEC = "[...document.querySelectorAll('button[automation-id=goods-card-delete-btn]')].find(b => !b.closest('lu-product-card, lu-sidebar-cart-item'))"
INC = "[...document.querySelectorAll('button[automation-id=goods-card-add-btn]')].find(b => !b.closest('lu-product-card, lu-sidebar-cart-item'))"
ADD = "document.querySelector('div.add-to-cart button.lui-button')"
HEART = "document.querySelector('button.product-page-favorite-btn')"
CARD_JS = r"""(pid => { try { const s = JSON.parse(document.getElementById('ng-state').textContent);
  const m = Object.entries(s).find(([k]) => new RegExp('/catalog/items/' + pid + '($|[?|])').test(k));
  const c = m && (m[1].b || m[1].body || m[1]); return c ? {name: (c.display || {}).name || c.name, fav: !!(c.features || {}).isFavorite, count: c.count} : null } catch (e) { return null } })"""


def _goods(cart_lookup):
    cl = (((cart_lookup or {}).get("Body") or {}).get("CartList") or [{}])[0]
    # the cart writes some ids with a leading zero («052602» for 52602)
    return {str(g.get("GoodsItemId")).lstrip("0") or "0": g for g in cl.get("Goods") or []}, cl


def _load(tab, pid):
    """Full load of the product page: the cart (cartLookup, sent on every load) and the card from ng-state."""
    got = capture(tab, "lenta", f"{SITE}/product/x-{pid}/", {"c": ["/api/rest/cartLookup"]}, timeout=20)
    time.sleep(1.5)
    return _goods(got.get("c")), tab.js(f"{CARD_JS}({json.dumps(pid)})")


def _press(tab, js, what="m", url="/api/rest/cartItemModify"):
    return capture(tab, "lenta", None, {what: [url]}, timeout=10, js=f"({js}).click()").get(what)


def cart():
    tab = _tab()
    try:
        got = capture(tab, "lenta", SITE + "/", {"c": ["/api/rest/cartLookup"]}, timeout=20)
    finally:
        tab.close()
    goods, cl = _goods(got.get("c"))
    if not goods:
        return "корзина Ленты пуста"
    rows = [f"{i}\t{g.get('Quantity')}\t{g.get('Price')}\t{g.get('PriceTotal') or ''}\t{g.get('Name') or ''}" for i, g in goods.items()]
    return (f"корзина Ленты: позиций {cl.get('PositionsCount')}, итого {cl.get('TotalCost')} ₽"
            + (f", доставка {cl.get('DeliveryPrice')} ₽" if cl.get("DeliveryPrice") is not None else "")
            + "\nid\tшт\tцена ₽\tсумма ₽\tназвание\n" + "\n".join(rows))


def add_to_cart(id_or_url, quantity=1):
    pid = _id(id_or_url)
    tab = _tab()
    try:
        (goods, _), card = _load(tab, pid)
        if not card:
            return f"Лента: товар {pid} не открылся"
        have = float((goods.get(pid) or {}).get("Quantity") or 0)
        for i in range(max(1, min(int(quantity), 30))):
            first = i == 0 and not have
            if not tab.js(f"!!({ADD if first else INC})"):
                return f"Лента: кнопки «{'В корзину' if first else '+'}» на странице {card['name']} нет (нет в наличии?)"
            _press(tab, ADD if first else INC)
            time.sleep(0.8)
        (goods, cl), _ = _load(tab, pid)
    finally:
        tab.close()
    g = goods.get(pid)
    if not g or float(g.get("Quantity") or 0) <= have:
        return f"Лента не положила {card['name']} в корзину"
    return f"в корзине Ленты: {card['name']} — {g.get('Quantity')} шт × {g.get('Price')} ₽; итого корзины {cl.get('TotalCost')} ₽"


def remove_from_cart(id_or_url):
    pid = _id(id_or_url)
    tab = _tab()
    try:
        (goods, _), card = _load(tab, pid)
        name = (card or {}).get("name") or pid
        n = int(float((goods.get(pid) or {}).get("Quantity") or 0))
        if not n:
            return f"{name} в корзине Ленты нет"
        for _ in range(min(n, 30)):            # «−» takes one unit; at one unit it removes the line
            if not tab.js(f"!!({DEC})"):
                break
            _press(tab, DEC)
            time.sleep(0.8)
        (goods, _), _ = _load(tab, pid)
    finally:
        tab.close()
    return f"не удалось убрать {name} из корзины Ленты" if pid in goods else f"убрано из корзины Ленты: {name}"


def _favorite_ids(tab):
    """The user's favorites, from the list page's own request on a full load (moving there inside the app
    fetched nothing more than once; the card's isFavorite in the server-rendered page lags behind: it still
    said false right after an add, 2026-10-13)."""
    return capture(tab, "lenta", SITE + "/my-account/favorites/", {"f": ["re:/catalog/items/favorites$"]}, timeout=20).get("f")


def favorites():
    tab = _tab()
    try:
        d = _favorite_ids(tab)
    finally:
        tab.close()
    if d is None:
        return "Лента не отдала избранное"
    rows = [_listed(p) for p in d.get("items") or []]
    if not rows:
        return "избранное Ленты пусто"
    return f"избранное Ленты ({d.get('total')})\nid\tцена ₽\tналичие\tназвание\n" + "\n".join(
        f"{r['id']}\t{r['price']}\t{'' if r['available'] else 'нет в наличии'}\t{r['name']}" for r in rows)


def favorite(id_or_url, remove=False):
    pid = _id(id_or_url)
    tab = _tab()
    try:
        d = _favorite_ids(tab)
        if d is None:
            return "Лента не отдала избранное"
        now = any(str(p.get("id")) == pid for p in d.get("items") or [])
        _, card = _load(tab, pid)
        if not card:
            return f"Лента: товар {pid} не открылся"
        if now != remove:      # already as asked
            return f"{card['name']} {'уже в избранном' if now else 'и так не в избранном'} Ленты"
        r = _press(tab, HEART, "f", "/catalog/items/favorites/" + ("delete" if remove else "add"))
    finally:
        tab.close()
    if not (r or {}).get("result"):
        return "Лента не изменила избранное"
    return f"{'убрано из избранного' if remove else 'в избранном'} Ленты: {card['name']}"
