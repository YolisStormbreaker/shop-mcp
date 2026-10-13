"""Яндекс Лавка (lavka.yandex.ru): the site's own JSON API, called from its tab.

Every call is a POST to /api/v1/providers/… with the page's CSRF token in X-Csrf-Token-Bff (read and used inside
the page, never returned) and the depot position the page itself keeps. One address has two depots with their
own assortment, prices and carts: «Лавка у дома» (regular, 5–10 min on foot) and «Большая лавка» (supermarket,
by car); ids of the latter are given here as «s:<id>». No reviews, ratings or barcodes on the site; nutrition
has no sugar line, but products carry tags (without sugar / lactose, vegan, halal…) and allergen lists.
"""
import json
import re
import urllib.parse

from cdp import tab_for
from shoplog import log

SITE = "https://lavka.yandex.ru"
BLOCKED = "⚠️ Лавка не ответила (капча Яндекса или сайт не загрузился): shop-chrome show, открыть lavka.yandex.ru, повторить."
POST_JS = """(async (path, body, depot) => {
  const s = window.storeDehydratedState || {};
  const loc = (s.depotLocation || {}).locationArr;
  const csrf = (window.__PAGE_PROPS__ || {}).csrfToken;
  if (!loc || !csrf) return {__error: 'no page state'};
  const r = await fetch('/api/v1/providers/' + path, {method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json', 'X-Csrf-Token-Bff': csrf},
    body: JSON.stringify({position: {location: loc}, currencySign: '₽', depotType: depot, ...body})});
  const t = await r.text();
  try { return JSON.parse(t) } catch (e) { return {__error: r.status} }
})"""
DEPOTS = {"regular": "Лавка у дома", "supermarket": "Большая лавка"}
# tag → where to look: product tags (customTags) or the site's facts; gluten is only «not among allergens»
TAGS = {"без лактозы": ("tag", "withoutLactose"), "без сахара": ("tag", "withoutSugar"), "без мяса": ("tag", "withoutMeat"),
        "низкокалорийное": ("tag", "lowCalorie"), "мало углеводов": ("tag", "lowCarb"), "много белка": ("tag", "highProtein"),
        "веган": ("fact", "vegan"), "халяль": ("fact", "halal"), "от фермера": ("fact", "farmer"), "фермерское": ("fact", "farmer"),
        "без молока": ("fact", "withoutMilk"), "без кофеина": ("fact", "decaf"), "детям": ("fact", "forChildren"),
        "испекли сегодня": ("fact", "bakedToday"), "местное": ("fact", "local"), "без глютена": ("noallergen", "gluten")}


def _tab():
    tab = tab_for("lavka.yandex.ru")
    if not tab.js("location.hostname === 'lavka.yandex.ru' && !!window.storeDehydratedState && !!window.__PAGE_PROPS__"):
        tab.goto(SITE + "/", "lavka", wait_js="!!window.storeDehydratedState && !!window.__PAGE_PROPS__")
    return tab


def _post(tab, path, body, depot="regular"):
    d = tab.js(f"{POST_JS}({json.dumps(path)}, {json.dumps(body)}, {json.dumps(depot)})")
    if isinstance(d, dict) and "__error" in d:
        log.warning("lavka %s: %s", path, d["__error"])
        if d["__error"] in (401, 403, "no page state"):   # stale CSRF token or a captcha page: reload once
            tab.goto(SITE + "/", "lavka", wait_js="!!window.storeDehydratedState && !!window.__PAGE_PROPS__")
            d = tab.js(f"{POST_JS}({json.dumps(path)}, {json.dumps(body)}, {json.dumps(depot)})")
    return None if not isinstance(d, dict) or "__error" in d else d


def _clean(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", (t or "").replace("\xad", "").replace("&shy;", ""))).strip()


def _num(s):
    try:
        return float(str(s).replace(",", ".").replace(" ", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _id(p, depot):
    return ("s:" if depot == "supermarket" else "") + p["id"]


def _listed(p, depot):
    sup = "/supermarket" if depot == "supermarket" else ""
    return {"id": _id(p, depot), "name": _clean(p.get("longTitle") or p.get("title")) + (" · Большая лавка" if depot == "supermarket" else ""),
            "brand": p.get("brand") or "", "size": p.get("amount") or "", "price": _num(p.get("currentPrice")), "old": _num(p.get("oldPrice")),
            "available": bool(p.get("available")), "url": f"{SITE}{sup}/good/{p.get('deepLink') or p['id']}", "rating": None, "reviews": None,
            "ean": None, "_tags": set((p.get("productTags") or []) + (p.get("facts") or []) + ((p.get("options") or {}).get("attributes") or {}).get("customTags", [])),
            "_allergens": set(((p.get("options") or {}).get("attributes") or {}).get("mainAllergens") or [])}


def _search_depot(tab, query, depot, limit):
    d = _post(tab, "search/v3/lavka", {"text": query, "productsLimit": max(limit, 32), "subcategoriesLimit": 0, "useRetail": True,
                                       "source": "manual_input", "cart": {"cartItems": []}}, depot)
    if d is None:
        return None
    cache = {p["id"]: p for p in d.get("cacheProducts") or []}
    order = [x["id"] for x in d.get("layoutItems") or [] if x.get("type") == "good" and x.get("id") in cache]
    order += [i for i in cache if i not in order]
    return [_listed(cache[i], depot) for i in order]


def search(query, tag=None, sort="popular", page=1, limit=30):
    tab = _tab()
    note = ""
    try:
        how = next((v for k, v in TAGS.items() if tag and tag.lower() in k), None) if tag else None
        if tag and not how:
            note = f"тега «{tag}» у Лавки нет — искал «{query} {tag}» текстом"
            query = f"{query} {tag}".strip()
        if how and how[0] == "fact" and not query:
            d = _post(tab, "v1/products/list/by-attribute", {"attribute": {"type": "fact", "value": how[1]}, "limit": max(limit, 20)})
            items = [_listed(p, "regular") for p in (d or {}).get("products") or []] if d else None
        else:
            items = _search_depot(tab, query, "regular", limit)
            if items is not None:
                items += _search_depot(tab, query, "supermarket", limit) or []
    finally:
        tab.close()
    if items is None:
        return BLOCKED
    if how:
        kind, val = how
        items = [p for p in items if (val not in p["_allergens"] if kind == "noallergen" else val in p["_tags"])]
        note = (f"тег Лавки «{tag}»" + (" — по списку аллергенов: глютена в нём нет (сайт этого не утверждает)" if kind == "noallergen" else "")).strip()
    for p in items:
        p.pop("_tags"), p.pop("_allergens")
    if sort != "popular":
        key = {"price": lambda x: x["price"] or 1e9, "price_desc": lambda x: -(x["price"] or 0),
               "discount": lambda x: (x["price"] or 0) / (x["old"] or x["price"] or 1), "rating": lambda x: 0}[sort]
        items.sort(key=key)
        note += ("\n" if note else "") + "Лавка не сортирует: отсортированы полученные товары"
    start = (page - 1) * limit
    return {"items": items[start:start + limit], "total": len(items), "note": note.strip(),
            "facets": list(TAGS), "url": SITE + "/search?text=" + urllib.parse.quote(query or "")}


def _pid(id_or_url):
    s = str(id_or_url).strip()
    depot = "supermarket" if s.startswith("s:") or "/supermarket/" in s else "regular"
    m = re.search(r"/good/([\w-]+)", s)
    return (m.group(1) if m else s.removeprefix("s:")), depot


def product(id_or_url):
    pid, depot = _pid(id_or_url)
    tab = _tab()
    try:
        d = _post(tab, "v1/product", {"productId": pid, "needCatalogPaths": True, "enableUnavailable": True}, depot)
        info = tab.js(f"""fetch('/api/v1/providers/v2/service-info?' + new URLSearchParams({{'position[location][0]': storeDehydratedState.depotLocation.locationArr[0],
            'position[location][1]': storeDehydratedState.depotLocation.locationArr[1], depotType: {json.dumps(depot)}}}),
            {{credentials: 'include', headers: {{'X-Csrf-Token-Bff': __PAGE_PROPS__.csrfToken}}}}).then(r => r.json()).catch(e => null)""")
    finally:
        tab.close()
    c = (d or {}).get("product")
    if not c:
        return BLOCKED if d is None else f"Лавка: товар {pid} не найден"
    p = _listed(c, depot)
    tags, allergens = p.pop("_tags"), p.pop("_allergens")
    blocks = c.get("descriptionBlocks") or []
    comp = next((b.get("value") for b in blocks if "ingredientsLoc" in (b.get("attributes") or [])), "") or ""
    traces = next((b.get("value") for b in blocks if "specificsProduction" in (b.get("attributes") or [])), "")
    other = [f"{_clean(b.get('title'))}: {_clean(b.get('value'))}" for b in blocks
             if b.get("value") and not set(b.get("attributes") or []) & {"ingredientsLoc", "specificsProduction"}]
    nut = {}
    for t in ((c.get("options") or {}).get("ingredients") or {}).get("pfcTraits") or []:
        k = {"calories": "kcal", "protein": "protein", "fat": "fat", "carbohydrate": "carbs"}.get(t.get("id"))
        v = _num((t.get("measures") or {}).get("per100g"))
        if k and v is not None:
            nut[k] = v
    attrs = (c.get("options") or {}).get("attributes") or {}
    extra = []
    disc = next((s.get("text") for s in c.get("stickersV2") or [] if s.get("stickerId") == "discount"), None)
    if disc:
        extra.append(f"скидка {disc}")
    if isinstance(info, dict) and info.get("deliveryTimeText"):
        pc = info.get("pricingConditions") or {}
        extra.append(f"доставка ({DEPOTS[depot]}): {_clean(info.get('deliveryTimeText'))}"
                     + (f", доставка {_clean(str(pc.get('deliveryCost')))} ₽" if str(pc.get("deliveryCost", "")).isdigit() else
                        f", {_clean(str(pc.get('deliveryCost')))}" if pc.get("deliveryCost") else "")
                     + "; " + "; ".join(_clean(f"{x.get('name', '')} {x.get('threshold', '')}") for x in info.get("deliveryConditions") or [])
                     + ("" if info.get("isOpen", True) else " · сейчас закрыто"))
    if c.get("isLowStock"):
        extra.append("осталось мало")
    if tags:
        extra.append("теги Лавки: " + ", ".join(sorted(tags)))
    if allergens or attrs.get("importantIngredients"):
        extra.append("аллергены: " + ", ".join(sorted(allergens)) + (" · важные ингредиенты: " + ", ".join(attrs["importantIngredients"]) if attrs.get("importantIngredients") else ""))
    if other:
        extra.append("о товаре: " + "; ".join(other)[:800])
    imgs = [u.replace("{w}x{h}", "orig") for u in c.get("imageUrlTemplates") or []] or \
           [((c.get("snippetImage") or {}).get("url") or "").replace("{w}x{h}", "orig")]
    p.update(photos=[u for u in imgs if u], description=_clean(c.get("description")),
             composition=comp + (f". {traces}" if traces and traces not in comp else ""), nutrition=nut,
             composition_extra="без сахара (тег Лавки)" if "withoutSugar" in tags or "nosugar" in tags else "", extra=extra)
    if nut.get("carbs") == 0:          # no sugar line on the site, but zero carbs means zero sugar
        nut["sugar"] = 0.0
    return p
