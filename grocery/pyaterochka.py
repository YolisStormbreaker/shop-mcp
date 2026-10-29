"""Пятёрочка (5ka.ru): catalog, cards and reviews via the site's own API, called from its tab.

The catalog API (5d.5ka.ru) needs only the tab's cookies (an anti-bot WAF sits in front: without them
it answers 403 HTML). Prices and stock are for the store the site chose: with no delivery address set
on the site that is its built-in default store 35XY, not the user's. Reviews live on gw-fb5.x5.ru and need
nothing. The cart is a draft order behind headers that only the site's code adds; no favorites on the site.
"""
import json
import re
import time
import urllib.parse

from cdp import tab_for
from shoplog import log

API = "https://5d.5ka.ru/api/catalog"
REVIEWS = "https://gw-fb5.x5.ru/api/product-review/v1"
BLOCKED = "⚠️ Пятёрочка не отдала данные (проверка на бота?): shop-chrome show, открыть 5ka.ru, повторить."
ORDER = {"popular": "popularity", "price": "price_asc", "price_desc": "price_desc", "discount": "discount_desc", "rating": "rating_desc"}
# Diet tags are subcategories of «Здоровый выбор», not search filters (seen 2026-10-13)
# The store of the user's delivery address is kept by the site in localStorage (DeliveryPanelStore.selectedAddress
# .sapCode); the server-rendered catalogStore.storeId stays the default 35XY even then (2026-10-13). Only the code is read.
STATE_JS = """(() => { const p = JSON.parse(document.getElementById('__NEXT_DATA__')?.textContent || '{}').props?.pageProps?.props || {};
  const c = typeof p.catalogStore === 'string' ? JSON.parse(p.catalogStore) : (p.catalogStore || {});
  let sap = null; try { sap = JSON.parse(localStorage.getItem('DeliveryPanelStore') || '{}').selectedAddress?.sapCode } catch (e) {}
  return {store: sap || c.storeId || '35XY', address: document.querySelector('[data-qa="delivery-panel-address"]')?.innerText || ''} })()"""


CHECKED = ("⚠️ Пятёрочка показала проверку на бота (ServicePipe): попроси пользователя выполнить shop-chrome show, пройти её во "
           "вкладке 5ka.ru, потом shop-chrome hide.")


def _tab():
    tab = tab_for("5ka.ru")
    if "/xpvnsulc/" in (tab.js("location.pathname") or ""):      # maybe a stale page from session restore: try once
        tab.goto("https://5ka.ru/", "5ka", wait_js="!!document.getElementById('__NEXT_DATA__') || location.pathname.includes('/xpvnsulc/')")
        if "/xpvnsulc/" in (tab.js("location.pathname") or ""):
            tab.close()
            raise RuntimeError(CHECKED)
    if "5ka.ru" not in (tab.js("location.hostname") or ""):
        tab.goto("https://5ka.ru/", "5ka", wait_js="!!document.getElementById('__NEXT_DATA__')")
    return tab


_last = 0.0


def _get(tab, url, retried=False):
    global _last
    wait = 0.7 - (time.time() - _last)            # same ServicePipe as Перекрёсток: no bursts
    if wait > 0:
        time.sleep(wait)
    _last = time.time()
    r = tab.js(f"fetch({json.dumps(url)}, {{credentials: 'include'}}).then(async r => ({{s: r.status, b: await r.text()}}))"
               ".catch(e => ({s: 0, b: String(e)}))")
    try:
        return json.loads(r["b"])
    except ValueError:
        pass
    log.warning("5ka %s: %s non-JSON%s", url[:150], r["s"], " again" if retried else "")
    if retried:
        return None
    tab.goto("https://5ka.ru/", "5ka", wait_js="!!document.getElementById('__NEXT_DATA__')")  # renews the WAF cookies
    return _get(tab, url, True)


def _ctx(tab):
    s = tab.js(STATE_JS)
    note = ("⚠️ на 5ka.ru не задан адрес доставки: цены и наличие — для магазина по умолчанию сайта (35XY). "
            "Выбрать адрес можно на сайте.") if s["store"] == "35XY" and ("Уточните" in s["address"] or not s["address"]) else ""
    return s["store"], note


def _num(x):
    try:
        return round(float(x), 2) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _listed(p):
    pr = p.get("prices") or {}
    cur = _num(pr.get("discount")) or _num(pr.get("regular"))
    old = _num(pr.get("regular")) if _num(pr.get("discount")) else None
    rt = p.get("rating") or {}
    return {"id": str(p["plu"]), "name": p.get("name", ""), "brand": "", "size": p.get("property_clarification") or "",
            "price": cur, "old": old, "available": p.get("is_available", True) is not False and _num(p.get("stock_limit")) != 0,
            "url": f"https://5ka.ru/product/{p['plu']}/", "rating": rt.get("rating_average"), "reviews": rt.get("rates_count"), "ean": None}


_tree = {}


def _diet_tags(tab, store):
    """name → category id of every subcategory; diet ones («Веган, без глютена», «Без лактозы, халяль») among them."""
    if store not in _tree:
        d = _get(tab, f"{API}/v4/stores/{store}/categories?mode=delivery&include_subcategories=1&include_restrict=true") or []
        _tree[store] = {c["name"]: c["id"] for top in d for c in [top] + (top.get("categories") or [])}
    return _tree[store]


DIET = re.compile(r"без |веган|халяль|глютен|лактоз|сахар|постн|спорт|польз", re.I)


def search(query, tag=None, sort="popular", page=1, limit=30):
    tab = _tab()
    try:
        store, note = _ctx(tab)
        tags = _diet_tags(tab, store)
        section = _section(tags, tag)
        if tag and not section:
            note += f"\nтега «{tag}» среди разделов сайта нет — искал «{query} {tag}» текстом"
            query = f"{query} {tag}".strip()
        products = _section_products(tab, store, tags[section], sort, page) if section else _search_products(tab, store, query, page, limit)
        if products is None:
            return BLOCKED
        rows, more = _section_rows(products, section, query) if section else _search_rows(products, sort)
    finally:
        tab.close()
    return {"items": rows[:limit], "total": None, "facets": [n for n in tags if DIET.search(n)], "note": (note + more).strip(),
            "url": "https://5ka.ru/search/?text=" + urllib.parse.quote(query or "")}


def _section(tags, tag):
    """The site section whose name has the tag in it («лактоз» → «Без лактозы, халяль»), else None."""
    return next((name for name in tags if tag and tag.lower() in name.lower()), None)


def _section_products(tab, store, cat, sort, page):
    base = f"{API}/v2/stores/{store}/categories/{cat}/products?mode=delivery&include_restrict=true&order_by={ORDER[sort]}"
    products = []
    for off in range((page - 1) * 36, page * 36, 12):
        d = _get(tab, f"{base}&limit=12&offset={off}")
        if d is None and not products:
            return None                   # the site did not answer: a bot check, not an empty section
        if not d or not d.get("products"):
            break
        products += d["products"]
    return products


def _section_rows(products, section, query):
    """A section is sorted by the site; the query keeps names with every word's first 5 letters («кефиры» → «кефир»)."""
    words = [w[:5].lower() for w in (query or "").split()]
    rows = [_listed(p) for p in products if all(w in p.get("name", "").lower() for w in words)]
    return rows, f"\nраздел сайта «{section}»" + (f", отобраны названия со словами «{query}»" if words else "")


def _search_products(tab, store, query, page, limit):
    """Requests of 12 up to the limit, until a short one; None when the site did not answer."""
    q, size, products = urllib.parse.quote(query), max(limit, 12), []
    for off in range((page - 1) * size, page * size, 12):
        d = _get(tab, f"{API}/v3/stores/{store}/search?mode=delivery&include_restrict=true&q={q}&limit=12&offset={off}")
        if d is None:
            return None
        got = d.get("products") or []
        products += got
        if len(got) < 12:
            break
    return products


BY = {"price": lambda x: x["price"] or 1e9, "price_desc": lambda x: -(x["price"] or 0),
      "discount": lambda x: (x["price"] or 0) / (x["old"] or x["price"] or 1), "rating": lambda x: -(x["rating"] or 0)}


def _search_rows(products, sort):
    """Search itself has no sorting: the page it gave is sorted here."""
    rows = [_listed(p) for p in products]
    if sort == "popular":
        return rows, ""
    return sorted(rows, key=BY[sort]), "\nпоиск сайта не сортирует: отсортирована полученная страница"


def _plu(id_or_url):
    m = re.search(r"--(\d+)/?", str(id_or_url)) or re.search(r"/product/(\d+)", str(id_or_url)) or re.fullmatch(r"\s*(\d+)\s*", str(id_or_url))
    if not m:
        raise ValueError("нужен plu Пятёрочки или ссылка https://5ka.ru/product/<название>--<plu>/")
    return m.group(1)


def product(id_or_url):
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        store, note = _ctx(tab)
        c = _get(tab, f"{API}/v2/stores/{store}/products/{plu}?mode=delivery&include_restrict=true")
        rv = _get(tab, f"{REVIEWS}/product-reviews/count?plu_id={plu}")
    finally:
        tab.close()
    if not c or "plu" not in c:
        return BLOCKED if c is None else f"Пятёрочка: товар {plu} не найден"
    return _card(plu, c, rv, note)


def _card(plu, c, rv, note):
    attrs, rt = _attrs(c), c.get("rating") or {}
    price, old = _price(c)
    return {"id": plu, "name": c.get("name", ""), "brand": attrs.get("Бренд", ""), "size": c.get("property_clarification") or "",
            "price": price, "old": old, "available": bool(c.get("is_available")), "url": f"https://5ka.ru/product/{plu}/",
            "rating": rt.get("rating_average"), "reviews": rt.get("rates_count"), "ean": None,
            "photos": [u.split("?")[0] for u in (c.get("image_links") or {}).get("normal") or []],
            "description": re.sub(r"\s+", " ", c.get("description") or "").strip(),
            "composition": c.get("ingredients") or "", "nutrition": _nutrition(c),
            "composition_extra": "; ".join(f"{k}: {v}" for k, v in attrs.items() if re.search(r"какао|мяс|сок|молок|жирн", k, re.I)),
            "extra": _extra(note, attrs, rv)}


def _price(c):
    """(the price now, the regular price when that is a promotion)"""
    prices = {x.get("placement_type"): _num(x.get("value")) for x in c.get("prices") or []}
    promo = prices.get("promotional_primary")
    return promo or prices.get("regular_primary"), prices.get("regular_secondary") if promo else None


def _attrs(c):
    return {a["name"]: f"{a['value']} {a.get('uom') or ''}".strip() for a in c.get("attributes") or []}


NUTRIENTS = {"белки": "protein", "жиры": "fat", "углеводы": "carbs", "ккал": "kcal"}


def _nutrition(c):
    nut = {}
    for n in c.get("nutrients") or []:
        k = NUTRIENTS.get((n.get("text") or "").lower())
        if k and _num(n.get("value")) is not None:
            nut[k] = _num(n["value"])
    return nut


SKIP = {"Белки", "Жиры", "Углеводы", "Энергетическая ценность", "Бренд"}    # they have fields of their own
STARS = ((5, "five"), (4, "four"), (3, "three"), (2, "two"), (1, "one"))


def _stars(count):
    return " ".join(f"{i}★ {count.get(w, 0)}" for i, w in STARS)


def _extra(note, attrs, rv):
    rc = (rv.get("content") or {}) if isinstance(rv, dict) else {}
    extra = [note] if note else []
    chars = "; ".join(f"{k}: {v}" for k, v in attrs.items() if k not in SKIP)
    if chars:
        extra.append("характеристики: " + chars)
    if rc.get("reviews_count"):
        extra.append(f"отзывов с текстом {rc['reviews_count']} (grocery_reviews), звёзды: " + _stars(rc))
    return extra + ["доставка: срок и цена — только в корзине на сайте после выбора адреса"]


SORTS = {"useful": "useful", "new": "newest", "high": "rating_desc", "low": "rating_asc"}


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        cnt = _get(tab, f"{REVIEWS}/product-reviews/count?plu_id={plu}") or {}
        d = _get(tab, f"{REVIEWS}/product-reviews?plu_id={plu}&page={page}&page_size={limit}&sort={SORTS[sort]}")
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    return _reviews_head(plu, cnt.get("content") or {}, sort, page, limit, with_media) + "\n" + _review_rows(d, page)


def _reviews_head(plu, c, sort, page, limit, with_media):
    return (f"Пятёрочка · plu {plu}: рейтинг {c.get('rating') or '—'} ({c.get('rating_count') or 0} оценок), отзывов с текстом {c.get('reviews_count') or 0} · "
            + _stars(c) + f"\nстраница {page} по {limit}, сортировка {sort}. Фото и имён авторов у отзывов Пятёрочки нет"
            + (" (with_media не применим)" if with_media else "") + "\nдата\t★\tполезно +/−\tтекст")


def _review_rows(d, page):
    rows = [_review(x) for x in d.get("items") or []]
    return ("\n".join(rows) if rows else "(отзывов нет)") + ("\nесть ещё: page=" + str(page + 1) if d.get("has_next_page") else "")


def _review(x):
    return f"{(x.get('date') or '')[:10]}\t{x.get('rate')}\t+{x.get('likes', 0)}/−{x.get('dislikes', 0)}\t{' '.join((x.get('text') or '').split())}"


# Cart: a draft order behind headers only the site's code adds, so we press the product page's own buttons
# (element.click() reaches them in the hidden tab) and read the cart the site keeps in localStorage («cart-store»).
CART_JS = """(() => { try { const o = JSON.parse(localStorage.getItem('cart-store') || '{}').order || {};
  return {total: o.total_sum, items: (o.basket?.items || o.items || []).map(i => ({plu: String(i.product_plu), qty: parseFloat(i.quantity),
    price: i.price_promo || i.price_reg, total: i.total, name: i.name, uom: i.uom, gone: !!i.unavailability}))} } catch (e) { return {items: []} } })()"""
MAIN = "[...document.querySelectorAll('[data-qa=\"%s\"]')].find(b => !b.closest('[data-qa^=\"product-card-\"]'))"


def _qty(tab, plu):
    return next((i["qty"] for i in tab.js(CART_JS)["items"] if i["plu"] == str(plu)), 0)


ADD, PLUS, MINUS, BIN = ("product-detail-add-to-cart-button", "cart-button-increment-button", "cart-button-decrement-button",
                         "cart-button-remove-button")


def _press(tab, qa, plu):
    """Click the product's own button and wait (up to 6 s) until the site's cart shows a new quantity."""
    before = _qty(tab, plu)
    if not tab.js(f"(() => {{ const b = {MAIN % qa}; if (!b) return false; b.click(); return true }})()"):
        return False
    for _ in range(12):
        time.sleep(0.5)
        if _qty(tab, plu) != before:
            break
    return True


def _open(tab, plu):
    tab.goto(f"https://5ka.ru/product/{plu}/", "5ka", wait_js="!!document.querySelector('[data-qa=\"product-detail-add-to-cart-button\"], [data-qa=\"cart-button-with-item\"]')")
    time.sleep(2)              # hydration: a click before it does nothing
    return tab.js("document.querySelector('h1')?.innerText || ''")


def _settled(tab, plu):
    """The site sends quantity changes a moment after the clicks: wait, then reload and read what the server kept."""
    time.sleep(3)
    tab.goto(f"https://5ka.ru/product/{plu}/", "5ka", wait_js="!!document.getElementById('__NEXT_DATA__')")
    time.sleep(2)
    return _qty(tab, plu)


def _add_buttons(start, quantity):
    """The presses that add quantity (1..30, one for less than 1): the add button when it is not in the cart yet, «+» for the rest."""
    return ([PLUS] if start else [ADD]) + [PLUS] * (min(int(quantity), 30) - 1)


def _asks_address(tab, plu, buttons):
    """Press the buttons in turn while they are there; True when the site asks for a delivery address instead."""
    for qa in buttons:
        if not _press(tab, qa, plu):
            return False
        if tab.js("!!document.querySelector('[data-qa=\"delivery-modal\"]')"):
            return True
    return False


def add_to_cart(id_or_url, quantity=1):
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        name = _open(tab, plu)
        start = _qty(tab, plu)
        if _asks_address(tab, plu, _add_buttons(start, quantity)):
            return "Пятёрочка просит адрес доставки: выберите его на 5ka.ru (shop-chrome show), потом повторите"
        n, cart = _settled(tab, plu), tab.js(CART_JS)
    finally:
        tab.close()
    if n <= start:
        return f"Пятёрочка не положила «{name}» в корзину (нет в наличии?)"
    return f"в корзине Пятёрочки: {name} — {n:g} шт; корзина {cart.get('total')} ₽"


def _take_out(tab, plu):
    """Up to 30 presses until the site's cart has none: «−» above one unit, the bin (remove) button at the last one.
    The number of presses."""
    for n in range(30):
        if not _qty(tab, plu) or not (_press(tab, MINUS, plu) or _press(tab, BIN, plu)):
            return n
    return 30


def remove_from_cart(id_or_url):
    plu = _plu(id_or_url)
    tab = _tab()
    pressed = 0
    try:
        name = _open(tab, plu)
        for _ in range(2):                     # a second round if the server kept some
            pressed += _take_out(tab, plu)
            left = _settled(tab, plu)
            if not left:
                break
    finally:
        tab.close()
    if left:
        return f"не удалось убрать «{name}» из корзины Пятёрочки"
    return f"убрано из корзины Пятёрочки: {name}" if pressed else f"«{name}» в корзине Пятёрочки нет"


def cart():
    tab = _tab()
    try:
        tab.goto("https://5ka.ru/", "5ka", wait_js="!!document.getElementById('__NEXT_DATA__')")   # the site refreshes its cart on load
        time.sleep(1.5)
        c = tab.js(CART_JS)
    finally:
        tab.close()
    return _cart_text(c)


def _cart_text(c):
    if not c["items"]:
        return "корзина Пятёрочки пуста"
    return (f"корзина Пятёрочки: итого {c.get('total')} ₽\nplu\tкол-во\tцена ₽\tсумма ₽\tназвание\n"
            + "\n".join(f"{i['plu']}\t{i['qty']:g} {i['uom'] or ''}\t{i['price']}\t{i['total']}\t{i['name']}{' — нет в наличии' if i['gone'] else ''}"
                        for i in c["items"]))
