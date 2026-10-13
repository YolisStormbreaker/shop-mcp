"""Пятёрочка (5ka.ru): catalog, cards and reviews via the site's own API, called from its tab.

The catalog API (5d.5ka.ru) needs only the tab's cookies (an anti-bot WAF sits in front: without them
it answers 403 HTML). Prices and stock are for the store the site chose: with no delivery address set
on the site that is its built-in default store 35XY, not the user's. Reviews live on gw-fb5.x5.ru and need
nothing. The cart is a draft order behind headers that only the site's code adds; no favorites on the site.
"""
import json
import re
import urllib.parse

from cdp import tab_for
from shoplog import log

API = "https://5d.5ka.ru/api/catalog"
REVIEWS = "https://gw-fb5.x5.ru/api/product-review/v1"
BLOCKED = "⚠️ Пятёрочка не отдала данные (проверка на бота?): shop-chrome show, открыть 5ka.ru, повторить."
ORDER = {"popular": "popularity", "price": "price_asc", "price_desc": "price_desc", "discount": "discount_desc", "rating": "rating_desc"}
# Diet tags are subcategories of «Здоровый выбор», not search filters (seen 2026-10-13)
STATE_JS = """(() => { const p = JSON.parse(document.getElementById('__NEXT_DATA__')?.textContent || '{}').props?.pageProps?.props || {};
  const c = typeof p.catalogStore === 'string' ? JSON.parse(p.catalogStore) : (p.catalogStore || {});
  return {store: c.storeId || '35XY', address: document.querySelector('[data-qa="delivery-panel-address"]')?.innerText || ''} })()"""


def _tab():
    tab = tab_for("5ka.ru")
    if "5ka.ru" not in (tab.js("location.hostname") or ""):
        tab.goto("https://5ka.ru/", "5ka", wait_js="!!document.getElementById('__NEXT_DATA__')")
    return tab


def _get(tab, url, retried=False):
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
            "Выбрать адрес можно на сайте.") if "Уточните" in s["address"] or not s["address"] else ""
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


def search(query, tag=None, sort="popular", page=1, limit=30):
    tab = _tab()
    try:
        store, note = _ctx(tab)
        tags = _diet_tags(tab, store)
        cat = None
        if tag:
            cat = next((cid for name, cid in tags.items() if tag.lower() in name.lower()), None)
            if not cat:
                note += f"\nтега «{tag}» среди разделов сайта нет — искал «{query} {tag}» текстом"
                query = f"{query} {tag}".strip()
        items, total = [], None
        if cat:   # a category listing: sorted by the site, filtered by the query words below
            base = f"{API}/v2/stores/{store}/categories/{cat}/products?mode=delivery&include_restrict=true&order_by={ORDER[sort]}"
            for off in range((page - 1) * 36, page * 36, 12):
                d = _get(tab, f"{base}&limit=12&offset={off}")
                if not d or not d.get("products"):
                    break
                items += d["products"]
            words = [w[:5].lower() for w in (query or "").split()]
            items = [p for p in items if all(w in p.get("name", "").lower() for w in words)]
            note += f"\nраздел сайта «{next(n for n, c in tags.items() if c == cat)}»" + (f", отобраны названия со словами «{query}»" if words else "")
        else:
            q = urllib.parse.quote(query)
            for off in range((page - 1) * max(limit, 12), page * max(limit, 12), 12):
                d = _get(tab, f"{API}/v3/stores/{store}/search?mode=delivery&include_restrict=true&q={q}&limit=12&offset={off}")
                if d is None:
                    return BLOCKED
                items += d.get("products") or []
                if len(d.get("products") or []) < 12:
                    break
    finally:
        tab.close()
    rows = [_listed(p) for p in items]
    if sort != "popular" and not cat:   # search itself has no sorting
        key = {"price": lambda x: x["price"] or 1e9, "price_desc": lambda x: -(x["price"] or 0),
               "discount": lambda x: (x["price"] or 0) / (x["old"] or x["price"] or 1), "rating": lambda x: -(x["rating"] or 0)}[sort]
        rows.sort(key=key)
        note += "\nпоиск сайта не сортирует: отсортирована полученная страница"
    diet = [n for n in tags if re.search(r"без |веган|халяль|глютен|лактоз|сахар|постн|спорт|польз", n, re.I)]
    return {"items": rows[:limit], "total": total, "facets": diet, "note": note.strip(),
            "url": "https://5ka.ru/search/?text=" + urllib.parse.quote(query or "")}


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
        rv = _get(tab, f"{REVIEWS}/product-reviews/count?plu_id={plu}") or {}
    finally:
        tab.close()
    if not c or "plu" not in c:
        return BLOCKED if c is None else f"Пятёрочка: товар {plu} не найден"
    prices = {x.get("placement_type"): _num(x.get("value")) for x in c.get("prices") or []}
    cur = prices.get("promotional_primary") or prices.get("regular_primary")
    old = prices.get("regular_secondary") if prices.get("promotional_primary") else None
    attrs = {a["name"]: f"{a['value']} {a.get('uom') or ''}".strip() for a in c.get("attributes") or []}
    nut = {}
    for n in c.get("nutrients") or []:
        k = {"белки": "protein", "жиры": "fat", "углеводы": "carbs", "ккал": "kcal"}.get((n.get("text") or "").lower())
        if k and _num(n.get("value")) is not None:
            nut[k] = _num(n["value"])
    skip = {"Белки", "Жиры", "Углеводы", "Энергетическая ценность", "Бренд"}
    rc = (rv.get("content") or {}) if isinstance(rv, dict) else {}
    rt = c.get("rating") or {}
    extra = [note] if note else []
    extra.append("характеристики: " + "; ".join(f"{k}: {v}" for k, v in attrs.items() if k not in skip))
    if rc.get("reviews_count"):
        extra.append(f"отзывов с текстом {rc['reviews_count']} (grocery_reviews), звёзды: "
                     + " ".join(f"{i}★ {rc.get(w, 0)}" for i, w in ((5, 'five'), (4, 'four'), (3, 'three'), (2, 'two'), (1, 'one'))))
    extra.append("доставка: срок и цена — только в корзине на сайте после выбора адреса")
    return {"id": plu, "name": c.get("name", ""), "brand": attrs.get("Бренд", ""), "size": c.get("property_clarification") or "",
            "price": cur, "old": old, "available": bool(c.get("is_available")), "url": f"https://5ka.ru/product/{plu}/",
            "rating": rt.get("rating_average"), "reviews": rt.get("rates_count"), "ean": None,
            "photos": [u.split("?")[0] for u in (c.get("image_links") or {}).get("normal") or []],
            "description": re.sub(r"\s+", " ", c.get("description") or "").strip(),
            "composition": c.get("ingredients") or "", "nutrition": nut,
            "composition_extra": "; ".join(f"{k}: {v}" for k, v in attrs.items() if re.search(r"какао|мяс|сок|молок|жирн", k, re.I)),
            "extra": extra}


SORTS = {"useful": "useful", "new": "newest", "high": "rating_desc", "low": "rating_asc"}


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    plu = _plu(id_or_url)
    tab = _tab()
    try:
        cnt = _get(tab, f"{REVIEWS}/product-reviews/count?plu_id={plu}") or {}
        d = _get(tab, f"{REVIEWS}/product-reviews?plu_id={plu}&page={page}&page_size={limit}&sort={SORTS[sort]}") or {}
    finally:
        tab.close()
    c = cnt.get("content") or {}
    head = (f"Пятёрочка · plu {plu}: рейтинг {c.get('rating') or '—'} ({c.get('rating_count') or 0} оценок), отзывов с текстом {c.get('reviews_count') or 0} · "
            + " ".join(f"{i}★ {c.get(w, 0)}" for i, w in ((5, 'five'), (4, 'four'), (3, 'three'), (2, 'two'), (1, 'one')))
            + f"\nстраница {page} по {limit}, сортировка {sort}. Фото и имён авторов у отзывов Пятёрочки нет"
            + (" (with_media не применим)" if with_media else "") + "\nдата\t★\tполезно +/−\tтекст")
    rows = [f"{(x.get('date') or '')[:10]}\t{x.get('rate')}\t+{x.get('likes', 0)}/−{x.get('dislikes', 0)}\t{' '.join((x.get('text') or '').split())}"
            for x in d.get("items") or []]
    return head + "\n" + ("\n".join(rows) if rows else "(отзывов нет)") + ("\nесть ещё: page=" + str(page + 1) if d.get("has_next_page") else "")
