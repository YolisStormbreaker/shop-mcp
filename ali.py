"""AliExpress (aliexpress.ru): search via the site's own API, called from the logged-in tab.

Stops at the cart, never checks out.
"""
import datetime
import json
import re
import time

from cdp import tab_for
from shoplog import dump, log

SORTS = {"default": "", "orders": "total_tranpro_desc", "price": "price_asc", "price_desc": "price_desc"}
_last_call = 0.0


def _tab():
    tab = tab_for("aliexpress.ru")
    if "aliexpress.ru" not in (tab.js("location.hostname") or ""):
        tab.goto("https://aliexpress.ru/", "ali", wait_js="document.readyState === 'complete'")
    return tab


def _fetch(tab, path, body=None, method="POST", retried=False):
    global _last_call
    gap = 1.5 - (time.time() - _last_call)
    if gap > 0:
        time.sleep(gap)
    _last_call = time.time()
    opts = {"method": method, "credentials": "include", "headers": {"Content-Type": "application/json"}}
    if body is not None:
        opts["body"] = json.dumps(body)
    r = tab.js(f"fetch({json.dumps(path)}, {json.dumps(opts)}).then(async r => ({{s: r.status, b: await r.text()}}))")
    try:
        return json.loads(r["b"])
    except ValueError:
        pass
    saved = dump("ali", r["s"], r["b"])
    if retried:
        log.error("ali %s %s: %s again after reload, body %s", method, path, r["s"], saved)
        raise RuntimeError(f"AliExpress ответил {r['s']} не-JSON и после перезагрузки вкладки "
                           f"(вероятно, проверка на бота: shop-chrome show). Ответ целиком: {saved}")
    # Same idea as Ozon: a real page load renews anti-bot cookies that fetch() cannot.
    log.warning("ali %s %s: %s non-JSON, body %s; reloading tab and retrying", method, path, r["s"], saved)
    tab.goto("https://aliexpress.ru/", "ali", wait_js="document.readyState === 'complete'")
    time.sleep(3)
    return _fetch(tab, path, body, method, retried=True)


def _find(o, key):
    """First dict value under `key` anywhere in o."""
    if isinstance(o, dict):
        if key in o:
            return o[key]
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            r = _find(v, key)
            if r is not None:
                return r
    return None


def _product(p):
    item = _find(p, "itemData") or {}
    pd = item.get("pdpInfo", {}).get("preloadedData", {})
    props = item.get("properties", {})
    exp = _find(item.get("trackingInfo", {}), "exp_attribute") or {}
    snippet = ""
    for la in _find(p, "layoutAreas") or []:
        if "delivery" in la.get("id", {}).get("name", ""):
            snippet = ", ".join(re.findall(r'"text": "([^"]+)"', json.dumps(la, ensure_ascii=False)))
    if not snippet and exp.get("snippet_delivery_eta"):
        ship = exp.get("delivery_price")
        snippet = f"{exp['snippet_delivery_eta']} дн., " + (f"{ship} ₽" if ship else "бесплатно")
    return {
        "id": props.get("id", ""),
        "sku": props.get("preselectSkuId", ""),
        "price": pd.get("price", {}).get("value", ""),
        "title": pd.get("title", ""),
        "rating": pd.get("rating", ""),
        "sold": pd.get("salesCount", "").replace(" купили", ""),
        "store": pd.get("store", {}).get("name", ""),
        "delivery": snippet,
        "by": _latest_date(snippet, exp.get("snippet_delivery_eta", "")),
    }


def _latest_date(snippet, eta):
    """'до 10 дней' / '11-14' -> latest arrival date as 04.10."""
    days = re.findall(r"(\d+)\s*(?:дн|день|дня|дней)", snippet) or re.findall(r"\d+", eta or "")
    if not days:
        return ""
    return (datetime.date.today() + datetime.timedelta(days=max(map(int, days)))).strftime("%d.%m")


def search(query, price_min=None, price_max=None, sort="default", limit=30):
    if sort not in SORTS:
        raise ValueError(f"sort: одно из {tuple(SORTS)}")
    body = {"catId": "", "searchInfo": "", "searchText": query, "page": 1, "storeIds": [], "pgChildren": [],
            "aeBrainIds": [], "searchTrigger": "search_bar", "mainFilters": "", "source": "direct"}
    if SORTS[sort]:
        body["sortType"] = SORTS[sort]
    if price_min:
        body["minPrice"] = int(price_min)
    if price_max:
        body["maxPrice"] = int(price_max)
    tab = _tab()
    items, seen, pages = [], set(), 1
    try:
        while len(items) < limit and body["page"] <= min(pages, 5):
            d = _fetch(tab, "/aer-webapi/v1/search", body).get("data") or {}
            pages = (d.get("pagination") or {}).get("totalPages", 1)
            for p in (d.get("productsFeed") or {}).get("productsV2") or []:
                x = _product(p)
                if x["id"] and x["id"] not in seen:
                    seen.add(x["id"])
                    items.append(x)
            body["page"] += 1
    finally:
        tab.close()
    rows = [f"{i+1}\t{x['id']}\t{x['sku']}\t{x['price']}\t{x['title'][:110]}\t{x['rating']}\t{x['sold']}\t{x['by']}\t{x['delivery']}\t{x['store']}"
            for i, x in enumerate(items[:limit])]
    head = ("AliExpress · товар: https://aliexpress.ru/item/<id>.html\n"
            "«привезут до» = сегодня + максимальный срок из карточки; точная дата — в ali_item\n"
            "#\tid\tsku\tцена ₽\tназвание\tрейтинг\tкупили\tпривезут до\tдоставка (срок, цена)\tмагазин")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


# ---------- product page, cart ----------

MONTHS = "января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря"
PROP = '[class*="SkuPropertyItem__skuProp"]'
CART_BTN = "[...document.querySelectorAll('button')].filter(b => b.innerText.trim() === 'В корзину' && b.getBoundingClientRect().height > 0).pop()"


def _item_id(id_or_url):
    m = re.search(r"(?:item/(?:\d+_)?)?(\d{9,})", str(id_or_url))
    if not m:
        raise ValueError(f"не нашёл id товара в {id_or_url!r}")
    return m.group(1)


NOT_ON_SCREEN = ("не добавлено: вкладка AliExpress не на экране, а клик по «В корзину» работает только в видимой вкладке. "
                 "Попроси пользователя выполнить shop-chrome show и открыть вкладку aliexpress.ru, потом повтори.")


def _click_js(tab, js_elem):
    """Real mouse click on the element; False if it is missing or the tab is not on screen (clicks then do nothing)."""
    if not tab.visible():
        return False
    pos = tab.js(f"(() => {{ const e = {js_elem}; if (!e) return null; e.scrollIntoView({{block: 'center'}}); return 1; }})()")
    if not pos:
        return False
    time.sleep(0.4)
    pos = tab.js(f"(() => {{ const r = ({js_elem}).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()")
    for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
        tab.call("Input.dispatchMouseEvent", type=typ, x=pos[0], y=pos[1], button="left", clickCount=1)
    return True


def _open_item(tab, item_id, sku=None):
    url = f"https://aliexpress.ru/item/{item_id}.html" + (f"?sku_id={sku}" if sku else "")
    tab.goto(url, "ali", wait_js=f"!!({CART_BTN}) || document.body.innerText.includes('Нет в наличии')")
    time.sleep(1.2)


def _pdp_state(tab):
    lines = [l.strip() for l in tab.js("document.body.innerText").splitlines() if l.strip()]
    deliv = []
    for i, l in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if re.match(rf"^\d+(?:[–-]\d+)?\s+(?:{MONTHS})", l) and len(l) < 60 and re.fullmatch(r"Бесплатно|[\d\s\u00a0,]+₽", nxt):
            deliv.append(f"{l} — {nxt.lower()}")
    props = tab.js(f"""[...document.querySelectorAll('{PROP}')].map(p => p.querySelector('[class*="propNameWrap"]')?.innerText.replace(/\\s+/g, ' ').trim())""")
    price = tab.js("""(() => { const l = document.body.innerText.split('\\n').map(s => s.trim());
        const i = l.findIndex(s => s === 'В корзину'); return l.slice(0, i > 0 ? i : 200).find(s => /^[\\d\\s\\u00a0,]+₽$/.test(s)) || ''; })()""")
    return {"title": tab.js("document.querySelector('h1')?.innerText.trim() || ''"), "price": price,
            "delivery": list(dict.fromkeys(deliv)), "props": props,
            "sku": (re.search(r"sku_id=(\d+)", tab.js("location.search")) or [None, ""])[1],
            "in_stock": bool(tab.js(f"!!({CART_BTN})"))}


def _skus(tab, item_id):
    """Every variant from the product API: [{label, sku, price, stock, props}], no clicking.

    Clicking through options (the old way) does nothing in a background tab and returned the
    default variant for every option (seen 2026-09-30).
    """
    d = _fetch(tab, f"/aer-jsonapi/v1/bx/pdp/web/productData?productId={item_id}&sourceId=0&sku_id=0", method="GET")
    info = (d.get("data") or {}).get("skuInfo") or {}
    values = {v["id"]: (p["name"], v) for p in info.get("propertyList") or [] for v in p.get("values") or []}
    out = []
    for s in info.get("priceList") or []:
        props = [values[i] for i in str(s.get("skuPropIds") or "").split(",") if i in values]
        out.append({
            "label": "; ".join(f"{n}: {(v.get('displayName') or v['name']).strip()}" for n, v in props),
            "props": {n.lower(): {v["name"].strip().lower(), (v.get("displayName") or "").strip().lower()} for n, v in props},
            "sku": str(s.get("skuId")),
            "price": (s.get("activityAmount") or {}).get("formatted") or (s.get("amount") or {}).get("formatted") or "",
            "stock": s.get("availQuantity") or 0,
        })
    return out


def _sku_for(variants, options):
    """The one variant whose properties have all the given values (name or display name, any case)."""
    hits = [v for v in variants if all(str(val).strip().lower() in v["props"].get(k.lower(), ()) for k, val in options.items())]
    if len(hits) != 1:
        found = "подходит несколько" if hits else "нет такого варианта"
        raise ValueError(f"{found} для {options}; варианты: " + " | ".join(v["label"] for v in (hits or variants)))
    return hits[0]["sku"]


def item(id_or_url, sku=None, list_variants=True):
    item_id = _item_id(id_or_url)
    tab = _tab()
    try:
        _open_item(tab, item_id, sku)
        st = _pdp_state(tab)
        variants = _skus(tab, item_id) if list_variants else []
    finally:
        tab.close()
    lines = [st["title"], f"id {item_id} · sku {st['sku']} · {st['price']}" + ("" if st["in_stock"] else " · НЕТ В НАЛИЧИИ"),
             "выбрано: " + "; ".join(p for p in st["props"] if p)]
    lines += ["доставка:"] + [f"  {d}" for d in st["delivery"]] if st["delivery"] else ["доставка: не нашёл на странице"]
    if variants:
        lines.append("варианты (свойства\tsku\tцена\tостаток):")
        lines += [f"  {v['label']}\t{v['sku']}\t{v['price']}\t{v['stock'] or 'нет'}" for v in variants]
    return "\n".join(lines)


def _count(tab):
    r = _fetch(tab, "/aer-jsonapi/v2/cart/count", {})
    return (r.get("data") or {}).get("count")


def add_to_cart(id_or_url, sku=None, options=None):
    item_id = _item_id(id_or_url)
    tab = _tab()
    try:
        if options:
            sku = _sku_for(_skus(tab, item_id), options)
        _open_item(tab, item_id, sku)
        st = _pdp_state(tab)
        if not st["in_stock"]:
            return f"не добавлено: «{st['title'][:80]}» нет в наличии для {st['props']}"
        before = _count(tab)
        if not _click_js(tab, CART_BTN):
            return NOT_ON_SCREEN
        after = before
        for _ in range(10):
            time.sleep(0.7)
            after = _count(tab)
            if after != before:
                break
    finally:
        tab.close()
    status = "добавлено" if after != before else "позиций в корзине не прибавилось (такой вариант уже лежал в корзине — проверь ali_cart)"
    return (f"{status}: {st['title'][:90]}\nsku {st['sku']} · {st['price']} · {'; '.join(p for p in st['props'] if p)}\n"
            "доставка: " + " | ".join(st["delivery"]))


CART_ROWS_JS = r"""[...document.querySelectorAll('[class*="ProductWrapper__w"]')].map(r => ({
  cart_id: (r.querySelector('[id^="cart-item-"]')?.id || '').replace('cart-item-', ''),
  link: r.querySelector('a[href*="/item/"]')?.href || '',
  checked: !!r.querySelector('input[type=checkbox]')?.checked,
  lines: r.innerText.split('\n').map(s => s.trim()).filter(Boolean),
}))"""


def _open_cart(tab):
    tab.goto("https://aliexpress.ru/cart", "ali", wait_js="document.body.innerText.includes('Корзина')")
    time.sleep(1.5)


def _cart_text(tab):
    rows = tab.js(CART_ROWS_JS)
    if not rows:
        return "корзина AliExpress пуста"
    out = ["корзина AliExpress (✓ = выбран к оформлению)", "cart_id\t✓\tid товара\tшт\tцена\tназвание\tдоставка"]
    for r in rows:
        ln = r["lines"]
        price = next((x for x in ln if "₽" in x), "")
        qty = ln[-1] if ln and ln[-1].isdigit() else ""
        deliv = next((x for x in ln if x.lower().startswith("доставка")), "")
        m = re.search(r"item/(?:\d+_)?(\d+)", r["link"])
        out.append(f"{r['cart_id']}\t{'✓' if r['checked'] else ''}\t{m.group(1) if m else ''}\t{qty}\t{price}\t{ln[0][:90] if ln else ''}\t{deliv}")
    body = [l.strip() for l in tab.js("document.body.innerText").splitlines() if l.strip()]
    i = next((k for k, l in enumerate(body) if l == "К оформлению"), None)
    if i:
        out.append("итого к оформлению: " + " · ".join(body[max(0, i - 4):i]))
    return "\n".join(out)


def cart():
    tab = _tab()
    try:
        _open_cart(tab)
        return _cart_text(tab)
    finally:
        tab.close()


def remove_from_cart(cart_id_or_item_id):
    """Removes one cart line. Keeps the other lines' ✓ selection as it was."""
    key = str(cart_id_or_item_id)
    tab = _tab()
    try:
        _open_cart(tab)
        rows = tab.js(CART_ROWS_JS)
        hit = [r for r in rows if r["cart_id"] == key or re.search(rf"item/(?:\d+_)?{key}\b", r["link"])]
        if not hit:
            return f"в корзине нет строки {key}\n" + _cart_text(tab)
        ids = [r["cart_id"] for r in hit]
        keep = [r["cart_id"] for r in rows if r["checked"] and r["cart_id"] not in ids]
        r = _fetch(tab, "/aer-jsonapi/v4/cart/hot/items/delete",
                   {"ids": ids, "selection": keep, "selectAll": False, "currentPage": 1, "sortType": 2})
        _open_cart(tab)
        return f"удалено строк: {len(ids)}\n" + _cart_text(tab)
    finally:
        tab.close()
