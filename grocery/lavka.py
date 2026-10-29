"""Яндекс Лавка (lavka.yandex.ru): the site's own JSON API, called from its tab.

Every call is a POST to /api/v1/providers/… with the page's CSRF token in X-Csrf-Token-Bff (read and used inside
the page, never returned) and the depot position the page itself keeps. One address has two depots with their
own assortment, prices and carts: «Лавка у дома» (regular, 5–10 min on foot) and «Большая лавка» (supermarket,
by car); ids of the latter are given here as «s:<id>». No reviews, ratings or barcodes on the site; nutrition
has no sugar line, but products carry tags (without sugar / lactose, vegan, halal…) and allergen lists.
"""
import json
import re
import time
import urllib.parse

from cdp import site_tab
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
    return site_tab("lavka.yandex.ru", SITE + "/", "lavka", ready="!!window.storeDehydratedState && !!window.__PAGE_PROPS__")


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


def _attributes(p):
    return (p.get("options") or {}).get("attributes") or {}


def _tags(p):
    return set((p.get("productTags") or []) + (p.get("facts") or []) + _attributes(p).get("customTags", []))


def _listed(p, depot):
    sup = "/supermarket" if depot == "supermarket" else ""
    return {"id": _id(p, depot), "name": _clean(p.get("longTitle") or p.get("title")) + (" · Большая лавка" if sup else ""),
            "brand": p.get("brand") or "", "size": p.get("amount") or "", "price": _num(p.get("currentPrice")), "old": _num(p.get("oldPrice")),
            "available": bool(p.get("available")), "url": f"{SITE}{sup}/good/{p.get('deepLink') or p['id']}", "rating": None, "reviews": None,
            "ean": None, "_tags": _tags(p), "_allergens": set(_attributes(p).get("mainAllergens") or [])}


def _search_depot(tab, query, depot, limit):
    d = _post(tab, "search/v3/lavka", {"text": query, "productsLimit": max(limit, 32), "subcategoriesLimit": 0, "useRetail": True,
                                       "source": "manual_input", "cart": {"cartItems": []}}, depot)
    if d is None:
        return None
    cache = {p["id"]: p for p in d.get("cacheProducts") or []}
    order = [x["id"] for x in d.get("layoutItems") or [] if x.get("type") == "good" and x.get("id") in cache]
    order += [i for i in cache if i not in order]
    return [_listed(cache[i], depot) for i in order]


SORTS = {"price": lambda x: x["price"] or 1e9, "price_desc": lambda x: -(x["price"] or 0),
         "discount": lambda x: (x["price"] or 0) / (x["old"] or x["price"] or 1), "rating": lambda x: 0}


def search(query, tag=None, sort="popular", page=1, limit=30):
    how, query, note = _how(query, tag)
    tab = _tab()
    try:
        items = _found(tab, query, how, limit)
    finally:
        tab.close()
    if items is None:
        return BLOCKED
    if how:
        items, note = _tagged(items, how, tag)
    for p in items:
        p.pop("_tags"), p.pop("_allergens")
    if sort != "popular":
        items.sort(key=SORTS[sort])
        note += ("\n" if note else "") + "Лавка не сортирует: отсортированы полученные товары"
    start = (page - 1) * limit
    return {"items": items[start:start + limit], "total": len(items), "note": note.strip(),
            "facets": list(TAGS), "url": SITE + "/search?text=" + urllib.parse.quote(query or "")}


def _how(query, tag):
    """(where Лавка keeps the tag, the query, the note); a tag it does not have is searched as text."""
    how = next((v for k, v in TAGS.items() if tag.lower() in k), None) if tag else None
    if tag and not how:
        return None, f"{query} {tag}".strip(), f"тега «{tag}» у Лавки нет — искал «{query} {tag}» текстом"
    return how, query, ""


def _found(tab, query, how, limit):
    """Both depots' hits, or a fact's list when there is no query; None when the site did not answer."""
    if how and how[0] == "fact" and not query:
        d = _post(tab, "v1/products/list/by-attribute", {"attribute": {"type": "fact", "value": how[1]}, "limit": max(limit, 20)})
        return [_listed(p, "regular") for p in d.get("products") or []] if d else None
    items = _search_depot(tab, query, "regular", limit)
    if items is not None:
        items += _search_depot(tab, query, "supermarket", limit) or []
    return items


def _tagged(items, how, tag):
    kind, val = how
    if kind == "noallergen":
        return [p for p in items if val not in p["_allergens"]], \
            f"тег Лавки «{tag}» — по списку аллергенов: глютена в нём нет (сайт этого не утверждает)"
    return [p for p in items if val in p["_tags"]], f"тег Лавки «{tag}»"


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
    return _card(c, info, depot)


def _card(c, info, depot):
    p = _listed(c, depot)
    tags, allergens = p.pop("_tags"), p.pop("_allergens")
    composition, other = _blocks(c.get("descriptionBlocks") or [])
    p.update(photos=_photos(c), description=_clean(c.get("description")), composition=composition, nutrition=_nutrition(c),
             composition_extra="без сахара (тег Лавки)" if "withoutSugar" in tags or "nosugar" in tags else "",
             extra=[x for x in (_discount(c), _delivery(info, depot), c.get("isLowStock") and "осталось мало",
                                tags and "теги Лавки: " + ", ".join(sorted(tags)), _allergy(c, allergens),
                                other and "о товаре: " + "; ".join(other)[:800]) if x])
    return p


def _block(blocks, attribute):
    return next((b.get("value") for b in blocks if attribute in (b.get("attributes") or [])), "") or ""


def _blocks(blocks):
    """(the composition with its production traces, the card's other description lines)"""
    composition, traces = _block(blocks, "ingredientsLoc"), _block(blocks, "specificsProduction")
    other = [f"{_clean(b.get('title'))}: {_clean(b.get('value'))}" for b in blocks
             if b.get("value") and not set(b.get("attributes") or []) & {"ingredientsLoc", "specificsProduction"}]
    return composition + (f". {traces}" if traces and traces not in composition else ""), other


NUTRIENTS = {"calories": "kcal", "protein": "protein", "fat": "fat", "carbohydrate": "carbs"}


def _nutrition(c):
    nut = {}
    for t in ((c.get("options") or {}).get("ingredients") or {}).get("pfcTraits") or []:
        k, v = NUTRIENTS.get(t.get("id")), _num((t.get("measures") or {}).get("per100g"))
        if k and v is not None:
            nut[k] = v
    if nut.get("carbs") == 0:          # no sugar line on the site, but zero carbs means zero sugar
        nut["sugar"] = 0.0
    return nut


def _discount(c):
    text = next((s.get("text") for s in c.get("stickersV2") or [] if s.get("stickerId") == "discount"), None)
    return text and f"скидка {text}"


def _delivery(info, depot):
    if not isinstance(info, dict) or not info.get("deliveryTimeText"):
        return ""
    pc = info.get("pricingConditions") or {}
    cost = _clean(str(pc.get("deliveryCost")))
    return (f"доставка ({DEPOTS[depot]}): {_clean(info.get('deliveryTimeText'))}"
            + (f", доставка {cost} ₽" if str(pc.get("deliveryCost", "")).isdigit() else f", {cost}" if pc.get("deliveryCost") else "")
            + "".join("; " + _clean(f"{x.get('name', '')} {x.get('threshold', '')}") for x in info.get("deliveryConditions") or [])
            + ("" if info.get("isOpen", True) else " · сейчас закрыто"))


def _allergy(c, allergens):
    important = _attributes(c).get("importantIngredients")
    if not (allergens or important):
        return ""
    return "аллергены: " + ", ".join(sorted(allergens)) + (" · важные ингредиенты: " + ", ".join(important) if important else "")


def _photos(c):
    urls = [u.replace("{w}x{h}", "orig") for u in c.get("imageUrlTemplates") or []] or \
           [((c.get("snippetImage") or {}).get("url") or "").replace("{w}x{h}", "orig")]
    return [u for u in urls if u]


# Cart: its update call carries the whole cart with the delivery address the page keeps, so we press the page's
# own buttons on the product page (element.click() works in the hidden tab) and read the cart back by API.
MAIN = "[data-testid=snippet-control-base]"           # the product's own controls; cards below have the same buttons


def _cart_items(tab, depot):
    r = _post(tab, "cart/v1/retrieve", {}, depot) or {}
    return {i.get("id"): i for i in r.get("items") or []}, r


def _open_good(tab, pid, depot):
    d = _post(tab, "v1/product", {"productId": pid, "enableUnavailable": True}, depot)
    c = (d or {}).get("product")
    if not c:
        raise ValueError(f"Лавка: товар {pid} не найден")
    tab.goto(f"{SITE}{'/supermarket' if depot == 'supermarket' else ''}/good/{c.get('deepLink') or c['id']}", "lavka",
             wait_js="!!document.querySelector('[data-testid=snippet-control], [data-testid=snippet-control-base]')")
    return c


def _qty(tab, pid, depot):
    return float((_cart_items(tab, depot)[0].get(pid) or {}).get("quantity") or 0)


def add_to_cart(id_or_url, quantity=1):
    pid, depot = _pid(id_or_url)
    tab = _tab()
    try:
        c = _open_good(tab, pid, depot)
        pid = c["id"]
        start = _qty(tab, pid, depot)
        if not c.get("available"):
            return f"Лавка: {_clean(c.get('longTitle'))} сейчас нет в наличии"
        for i in range(max(1, min(int(quantity), 30))):
            sel = "[data-testid=snippet-control]" if i == 0 and not start else f"{MAIN} [data-testid=add-spin-button]"
            if not tab.js(f"(() => {{ const b = document.querySelector('{sel}'); if (!b) return false; b.click(); return true }})()"):
                break
            time.sleep(1.2)
        n = _qty(tab, pid, depot)
        items, r = _cart_items(tab, depot)
    finally:
        tab.close()
    if n <= start:
        return f"Лавка не положила {_clean(c.get('longTitle'))} в корзину (кнопка не сработала)"
    return (f"в корзине {DEPOTS[depot]}: {_clean(c.get('longTitle'))} — {n:g} шт; корзина {r.get('totalItemsPrice')} ₽ без доставки"
            + (f" · к заказу пока нельзя: {r.get('checkoutUnavailableReason')}" if not r.get("availableForCheckout") else ""))


def remove_from_cart(id_or_url):
    pid, depot = _pid(id_or_url)
    tab = _tab()
    try:
        c = _open_good(tab, pid, depot)
        pid = c["id"]
        for _ in range(30):
            if not _qty(tab, pid, depot):
                break
            if not tab.js(f"(() => {{ const b = document.querySelector('{MAIN} [data-testid=remove-spin-button]'); if (!b) return false; b.click(); return true }})()"):
                break
            time.sleep(1.2)
        left = _qty(tab, pid, depot)
    finally:
        tab.close()
    return f"не удалось убрать {_clean(c.get('longTitle'))} из корзины Лавки" if left else f"убрано из корзины {DEPOTS[depot]}: {_clean(c.get('longTitle'))}"


def cart():
    tab = _tab()
    try:
        out = []
        for depot, name in DEPOTS.items():
            items, r = _cart_items(tab, depot)
            if items:
                out.append(f"{name}: {r.get('totalItemsPrice')} ₽ без доставки, итого {r.get('totalPriceValue')} ₽"
                           + ("" if r.get("availableForCheckout") else f" (к заказу нельзя: {r.get('checkoutUnavailableReason')})"))
                out += [f"  {('s:' if depot == 'supermarket' else '') + i}\t{x.get('quantity')} шт\t{x.get('price')} ₽\t{_clean(x.get('title'))}" for i, x in items.items()]
    finally:
        tab.close()
    return "корзина Лавки\n" + "\n".join(out) if out else "корзины Лавки (у дома и Большой лавки) пусты"


def favorites():
    tab = _tab()
    try:
        d = _post(tab, "v1/api/v1/user/favorites", {}) or {}
    finally:
        tab.close()
    rows = [_listed(p, "regular") for p in d.get("products") or []]
    if not rows:
        return "избранное Лавки пусто"
    return "избранное Лавки\nid\tцена ₽\tналичие\tназвание\n" + "\n".join(
        f"{r['id']}\t{r['price']}\t{'' if r['available'] else 'нет в наличии'}\t{r['name']}" for r in rows)


def favorite(id_or_url, remove=False):
    pid, depot = _pid(id_or_url)
    tab = _tab()
    try:
        c = (_post(tab, "v1/product", {"productId": pid, "enableUnavailable": True}, depot) or {}).get("product") or {}
        r = _post(tab, "attributes/v2/favorite", {"productId": c.get("id") or pid, "isFavorite": not remove}, depot)
    finally:
        tab.close()
    if not r or r.get("isFavorite") is not (not remove):
        return "Лавка не изменила избранное"
    return f"{'убрано из избранного' if remove else 'в избранном'} Лавки: {_clean(c.get('longTitle')) or pid}"
