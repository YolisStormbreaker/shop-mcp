"""Groceries: Лента, Самокат, Яндекс Лавка, Перекрёсток, Пятёрочка, ВкусВилл — one tool family, store by name.

Every site module has the same functions:
  search(query, tag=None, sort="popular", page=1, limit=30) -> {"items": [product], "total", "facets", "note", "url"}
  product(id_or_url) -> product with the card's details (or a str: the site's own message, e.g. a bot check)
  reviews(id_or_url, ...) -> str      (only where the site has reviews)
  cart() -> str      add_to_cart(id_or_url, quantity=1) -> str      remove_from_cart(id_or_url) -> str
  favorites() -> str      favorite(id_or_url, remove=False) -> str
where product = {"id", "name", "brand", "size", "price", "old", "available", "url", "rating", "reviews", "ean",
and from product() also "photos": [url], "description", "composition" (the «Состав» text),
"nutrition": {"kcal", "protein", "fat", "carbs", "sugar"} per 100 g, "extra": ["delivery: …", …]}
(missing values are None or ""). Prices are for the user's address or store chosen on the site.
"""
import re
from concurrent.futures import ThreadPoolExecutor

from . import composition, lavka, lenta, perekrestok, pyaterochka, samokat, vkusvill

STORES = {"lenta": lenta, "samokat": samokat, "lavka": lavka, "perekrestok": perekrestok, "5ka": pyaterochka, "vkusvill": vkusvill}
NAMES = {"lenta": "Лента", "samokat": "Самокат", "lavka": "Яндекс Лавка", "perekrestok": "Перекрёсток", "5ka": "Пятёрочка",
         "vkusvill": "ВкусВилл"}
SORTS = ("popular", "price", "price_desc", "discount", "rating")

SIZE = re.compile(r"(?:(\d+)\s*[xх×*]\s*)?(\d+(?:[.,]\d+)?)\s*(кг|г|гр|л|мл|шт)\b\.?", re.I)


def size_of(text):
    """(amount, unit) in кг / л / шт from «молоко 3,2% 930 мл», «2х0,5 л», «яйца 10 шт»; the last match wins."""
    m = None
    for m in SIZE.finditer(text or ""):
        pass
    if not m:
        return None
    n, v, unit = int(m.group(1) or 1), float(m.group(2).replace(",", ".")), m.group(3).lower()
    if unit in ("г", "гр"):
        return n * v / 1000, "кг"
    if unit == "мл":
        return n * v / 1000, "л"
    return n * v, unit


def _size(p):
    """The size in the product's name, else its size field: the name says «930 мл» where a site's own
    weight field says 958 г (Перекрёсток), and per litre is what people compare."""
    return size_of(p.get("name") or "") or size_of(p.get("size") or "")


def unit_price(p):
    """«123 ₽/кг» from the product's price and its size (see _size)."""
    s = _size(p)
    if not s or not p.get("price") or not s[0]:
        return ""
    return f"{p['price'] / s[0]:.0f} ₽/{s[1]}"


def _store(store):
    s = (store or "").lower().strip()
    s = {"пятерочка": "5ka", "пятёрочка": "5ka", "pyaterochka": "5ka", "лента": "lenta", "самокат": "samokat",
         "лавка": "lavka", "яндекс лавка": "lavka", "перекресток": "perekrestok", "перекрёсток": "perekrestok",
         "вкусвилл": "vkusvill"}.get(s, s)
    if s not in STORES:
        raise ValueError(f"store: одно из {', '.join(STORES)}")
    return s


def _old(p):
    """The price before the discount, when the site gives one above the price."""
    old, price = p.get("old"), p.get("price")
    return old if old and price and old > price else None


def _off(p):
    """«−17%» off the old price, or ""."""
    return f"−{round(100 - p['price'] * 100 / _old(p))}%" if _old(p) else ""


def _rating(p):
    """«4.8 (120)»: the rating and how many reviews, or ""."""
    return f"{p['rating']}" + (f" ({p['reviews']})" if p.get("reviews") else "") if p.get("rating") else ""


def _row(i, store, p):
    price = p.get("price")
    return "\t".join(str(x) for x in (i, NAMES[store], p.get("id", ""), p.get("name", ""), _display_size(p),
                                      "" if price is None else price, _old(p) or "", _off(p), unit_price(p),
                                      _rating(p), "" if p.get("available", True) else "нет в наличии", p.get("url", "")))


def _tag(tag):
    return f" · тег «{tag}»" if tag else ""


HEAD = "#\tмагазин\tid\tназвание\tфасовка\tцена ₽\tбез скидки\tскидка\tза кг/л/шт\tрейтинг\tналичие\tссылка"


def search(store, query, tag=None, sort="popular", page=1, limit=30):
    store = _store(store)
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    r = STORES[store].search(query, tag=tag, sort=sort, page=page, limit=limit)
    if isinstance(r, str):          # a site's own message: bot check, unknown tag…
        return r
    items = r["items"][:limit]
    head = [f"{NAMES[store]} · «{query}»" + _tag(tag)
            + (f" · найдено {r['total']}" if r.get("total") is not None else "") + f" · страница {page} · {r.get('url', '')}"]
    if r.get("note"):
        head.append(r["note"])
    if r.get("facets"):
        head.append("теги и фильтры сайта (передавай в tag): " + "; ".join(r["facets"][:40]))
    head.append(HEAD)
    return "\n".join(head + [_row(i + 1, store, p) for i, p in enumerate(items)] or ["(пусто)"])


STOP = {"без", "змж", "бзмж", "для", "или", "шт", "мл", "гр", "упаковка", "пэт", "россия", "из", "лавки"}


def _words(name):
    """Significant words of a name: «Молоко пастеризованное ПРОСТОКВАШИНО 2,5%, без змж» → {молоко, пастеризованное, простоквашино}."""
    t = re.sub(r"\d+(?:[.,]\d+)?\s*(?:%|кг|г|гр|л|мл|шт)\b", " ", (name or "").lower().replace("ё", "е"))
    return {w for w in re.findall(r"[a-zа-я]{3,}", t) if w not in STOP}


def _percents(name):
    return tuple(sorted({float(x.replace(",", ".")) for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", name or "")}))


def _same(a, b):
    """Same product in two stores. No site gives a barcode, and search results rarely carry a brand, so:
    same size, same percents (fat, cocoa) and at least 75% of the name's significant words in common
    (60% joined «тортильи со злаками» with «тортильи гриль»).
    ponytail: a word-overlap rule, not a matcher; it misses renamed lines and may join near-twins."""
    if a.get("ean") and b.get("ean"):
        return a["ean"] == b["ean"]
    return _same_size(a, b) and _percents(a.get("name")) == _percents(b.get("name")) and _same_brand(a, b) and _same_words(a, b)


def _same_size(a, b):
    """Both sizes known, in one unit, within 2% of each other."""
    sa, sb = _size(a), _size(b)
    return bool(sa and sb) and sa[1] == sb[1] and abs(sa[0] - sb[0]) <= 0.02 * max(sa[0], sb[0])


def _same_brand(a, b):
    """Brands match, or a site does not say."""
    return not (a.get("brand") and b.get("brand")) or a["brand"].lower() == b["brand"].lower()


def _same_words(a, b):
    wa, wb = _words(a.get("name")), _words(b.get("name"))
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.75


def _display_size(p):
    """The size the name states («930мл»), else the site's own field (Перекрёсток's is a weight: «958 г» for 930 ml)."""
    m = list(SIZE.finditer(p.get("name") or ""))
    return m[-1].group(0).strip() if m else (p.get("size") or "")


def _keys(stores):
    return [_store(s) for s in stores] if stores else list(STORES)


def _safe(fn, *args):
    """fn(*args), or «ошибка: …» if it raises: one store failing is a note, not the whole tool failing."""
    try:
        return fn(*args)
    except Exception as e:
        return f"ошибка: {str(e)[:150]}"


def _each(keys, fn):
    """[(store, fn(store))] for every store at once: each site has its own tab and lock."""
    with ThreadPoolExecutor(max(1, len(keys))) as ex:
        return list(ex.map(lambda s: (s, _safe(fn, s)), keys))


def _notes(results):
    """The first line of each store's message (bot check, error) that came instead of results."""
    return [f"{NAMES[s]}: {v.splitlines()[0]}" for s, v in results if isinstance(v, str)]


def _hits(r, query, strict):
    """Search results whose names have every word of the query (see _relevant); all of them unless strict."""
    return [p for p in r["items"] if not strict or _relevant(p.get("name"), query)]


def _matches(s, query, tag, limit, strict):
    """One store's products for compare, or the site's message."""
    r = STORES[s].search(query, tag=tag, sort="popular", page=1, limit=max(limit * 3, 20) if strict else limit)
    if isinstance(r, str):
        return r
    # no name has every word («соус для фрикаделек»): the site's own best matches, marked as such
    return _hits(r, query, strict)[:limit] or [dict(p, name=p.get("name", "") + " (≈ похожее)") for p in r["items"][:min(limit, 4)]]


def _groups(found):
    """(clusters of the same product seen in more than one store, the other products) from [(store, product)];
    greedy: each product joins the first cluster whose every member it matches (see _same)."""
    clusters = []
    for s, p in found:
        c = next((c for c in clusters if all(_same(p, q) for _, q in c)), None)
        if c is None:
            clusters.append([(s, p)])
        else:
            c.append((s, p))
    shared = [len({s for s, _ in c}) > 1 for c in clusters]
    return [c for c, m in zip(clusters, shared) if m], [x for c, m in zip(clusters, shared) if not m for x in c]


def _table(same, rest):
    """The comparison table: groups by their cheapest per kg/l, cheapest first inside each; then the rest,
    exact matches before «(≈ похожее)»."""
    groups = [(gi, s, p) for gi, c in enumerate(sorted(same, key=lambda c: min(_per_unit(p) for _, p in c)), 1)
              for s, p in sorted(c, key=lambda x: _per_unit(x[1]))]
    others = [("—", s, p) for s, p in sorted(rest, key=lambda x: ("(≈ похожее)" in (x[1].get("name") or ""), _per_unit(x[1])))]
    rows = [f"{g}\t" + _row(n, s, p) for n, (g, s, p) in enumerate(groups + others, 1)]
    middle = ["Остальное, дешевле за кг/л — выше:" if same else ""] if rest else []
    head = ("Одинаковые товары в разных магазинах (фасовка, проценты и слова названия совпадают; сверяй названия), дешевле за кг/л — выше:"
            if same else "Одинаковых товаров не нашлось — сравнивай по цене за кг/л:")
    return [head, "группа\t" + HEAD] + rows[:len(groups)] + middle + rows[len(groups):]


def compare(query, stores=None, tag=None, limit=8, strict=True):
    """Search every store at once and put the results in one table: groups of the same product (see _same)
    first, cheapest per kg/l inside a group."""
    found = _each(_keys(stores), lambda s: _matches(s, query, tag, limit, strict))
    same, rest = _groups([(s, p) for s, items in found if not isinstance(items, str) for p in items])
    return "\n".join([f"Сравнение «{query}»" + _tag(tag) + f" · по {limit} первых из поиска каждого магазина"] + _notes(found) + _table(same, rest))


def item(store, id_or_url, full=False):
    store = _store(store)
    p = STORES[store].product(id_or_url)
    if isinstance(p, str):
        return p
    lines = _card_head(store, p) + (p.get("extra") or []) + _describe(p) + _card_tail(p, full)
    return "\n".join(x for x in lines if x)


def _card_head(store, p):
    """Name, link, ids, price, stock and rating lines of a card; "" where the site gives nothing."""
    size = _display_size(p)
    return [f"{NAMES[store]} · {p.get('name', '')}" + (f" · {p['brand']}" if p.get("brand") else ""), p.get("url", ""),
            f"id: {p.get('id')}" + (f" · штрихкод {p['ean']}" if p.get("ean") else "") + (f" · фасовка {size}" if size else ""),
            _price_line(p), "в наличии" if p.get("available", True) else "⛔ нет в наличии",
            f"рейтинг {p['rating']}" + (f", отзывов {p['reviews']}" if p.get("reviews") else "") if p.get("rating") else ""]


def _price_line(p):
    """«цена: 189.99 ₽, без скидки 239.99 ₽ (−21%), 1900 ₽/кг», or "" without a price."""
    if p.get("price") is None:
        return ""
    return f"цена: {p['price']} ₽" + (f", без скидки {p['old']} ₽ ({_off(p)})" if _off(p) else "") + (f", {unit_price(p)}" if unit_price(p) else "")


def _card_tail(p, full):
    """Photo links and the description, cut at 2000 characters unless full."""
    desc = p.get("description") or ""
    return ["фото (shop_images): " + " ".join(p["photos"][:8]) if p.get("photos") else "",
            "\nописание: " + (desc if full else desc[:2000]) if desc else ""]


def _describe(p):
    return composition.describe(p.get("composition"), p.get("nutrition"), p.get("composition_extra"))


RANKS = {"price": "цена за кг/л ↑", "sugar": "сахар на 100 г ↑", "kcal": "ккал на 100 г ↑", "protein": "белок на 100 г ↓",
         "fat": "жир на 100 г ↑", "ingredients": "число ингредиентов ↑"}


INF = float("inf")


def _last(v, sign=1):
    """Sort key sign × v; an unknown value goes after every known one."""
    return INF if v is None else sign * v


def _per_unit(p):
    """The price per kg/l/шт as the table shows it, INF when unknown."""
    u = unit_price(p)
    return float(u.split()[0]) if u else INF


def _all_text(p):
    """Composition, the site's composition facts and the name: «74% какао» is often only in the name."""
    return "; ".join((p.get("composition") or "", p.get("composition_extra") or "", p.get("name") or ""))


def _rank_value(p, rank):
    """Sort key, smaller is better; unknown values go last."""
    n = p.get("nutrition") or {}
    if rank == "price":
        return _per_unit(p)
    if rank == "sugar":
        return _last(n.get("sugar", n.get("carbs")))
    if rank in ("kcal", "fat"):
        return _last(n.get(rank))
    if rank == "protein":
        return _last(n.get("protein"), -1)
    if rank == "ingredients":
        return len(composition.parse(p["composition"])["ingredients"]) if p.get("composition") else INF
    return _last(composition.percent_of(rank.lstrip("%"), _all_text(p)), -1)   # "%какао": more is better


def _relevant(name, query):
    """Every word of the query (by its first four letters) is in the name: sites pad their results with
    neighbours — dried fish for «рыбные котлеты», chicken cutlets in Лавка."""
    stems = [w[:4] for w in re.findall(r"[а-яёa-z]{3,}", (query or "").lower()) if w not in ("для", "или", "под", "как")]
    if re.search(r"\bкорм|для (кошек|собак)", (name or "").lower()) and "корм" not in (query or "").lower():
        return False                       # pet food: «Корм … курица-тунец» is not «тунец»
    return all(st in (name or "").lower().replace("ё", "е") for st in (x.replace("ё", "е") for x in stems))


def _ids(s, query, tag, limit, strict):
    """One store's product ids for compare_details, or the site's message."""
    r = STORES[s].search(query, tag=tag, sort="popular", page=1, limit=max(limit * 4, 20))
    if isinstance(r, str):
        return r
    hits = _hits(r, query, strict) or r["items"][:min(limit, 3)]
    return [p["id"] for p in hits[:limit]] or f"по «{query}» ничего не нашлось"


def _from_search(query, stores, tag, limit, strict):
    """({store: [id]}, notes) from the first search results of every store."""
    found = _each(_keys(stores), lambda s: _ids(s, query, tag, limit, strict))
    return {s: v for s, v in found if not isinstance(v, str)}, _notes(found)


def _wanted(items):
    """{store: [id]} from ["store:id", …]."""
    wanted = {}
    for x in items:
        s, _, pid = x.partition(":")
        wanted.setdefault(_store(s), []).append(pid.strip())
    return wanted


def _cards(s, ids):
    """[(store, id, card or message)], one card after another: the store's tab is shared."""
    return [(s, pid, _safe(STORES[s].product, pid)) for pid in ids]


def _share(p, rank):
    """« · какао: 72%» when ranked by an ingredient's share."""
    if not rank.startswith("%"):
        return ""
    word = rank.lstrip("%")
    v = composition.percent_of(word, _all_text(p))
    return f" · {word}: {v:g}%" if v is not None else f" · {word}: % не указан"


def _details(i, s, p, rank):
    """One product of the composition comparison: its line, link and composition."""
    head = (f"\n{i}. {NAMES[s]} · {p.get('name', '')} · {p.get('price')} ₽" + (f" ({unit_price(p)})" if unit_price(p) else "")
            + ("" if p.get("available", True) else " · нет в наличии") + _share(p, rank)
            + (f" · рейтинг {_rating(p)}" if _rating(p) else "") + f" · {s}:{p.get('id')}")
    return [head, f"   {p.get('url', '')}"] + ["   " + x for x in _describe(p)]


def compare_details(query=None, stores=None, tag=None, limit=5, rank="price", items=None, strict=True):
    """Composition and nutrition side by side: either the first `limit` search results of every store,
    or the given items ["store:id", …]. Ranked by `rank` (see RANKS, or "%word" — share of that ingredient)."""
    if rank not in RANKS and not rank.startswith("%"):
        return f"rank: одно из {', '.join(RANKS)} или «%ингредиент» (например %какао, %томат, %мясо)"
    wanted, notes = (_wanted(items), []) if items else _from_search(query, stores, tag, limit, strict)
    got = [x for _, cards in _each(list(wanted), lambda s: _cards(s, wanted[s])) for x in cards]
    notes += [f"{NAMES[s]} {pid}: {p.splitlines()[0]}" for s, pid, p in got if isinstance(p, str)]
    ok = sorted(((s, p) for s, _, p in got if not isinstance(p, str)), key=lambda x: _rank_value(x[1], rank))
    head = (f"Сравнение состава" + (f" «{query}»" if query else "") + f" · порядок: {RANKS.get(rank) or 'доля «' + rank.lstrip('%') + '» ↓'}"
            + f" · товаров {len(ok)}")
    return "\n".join([head] + notes + [x for i, (s, p) in enumerate(ok, 1) for x in _details(i, s, p, rank)])


def call(store, fn, *args, **kwargs):
    """store's own function (item, reviews, cart, add_to_cart, …), or a plain «нет на сайте» if it has none."""
    store = _store(store)
    f = getattr(STORES[store], fn, None)
    if f is None:
        return f"{NAMES[store]}: {fn} на этом сайте нет"
    return f(*args, **kwargs)


if __name__ == "__main__":
    assert size_of("Молоко 3,2% 930 мл") == (0.93, "л")
    assert size_of("Сок 2х0,5 л") == (1.0, "л")
    assert size_of("Хлеб 300г") == (0.3, "кг")
    assert size_of("Яйца С1 10 шт") == (10.0, "шт")
    assert unit_price({"price": 93, "name": "Молоко 930 мл"}) == "100 ₽/л"
    a = {"name": "Молоко пастеризованное ПРОСТОКВАШИНО 2,5%, без змж", "size": "930 мл"}
    assert _same(a, {"name": "Молоко Простоквашино пастеризованное 2.5% БЗМЖ 930мл"})
    assert _same(a, {"name": "Молоко 2,5% «Простоквашино» пастеризованное", "size": "930 мл"})
    assert not _same(a, {"name": "Молоко Простоквашино пастеризованное 3.2% БЗМЖ 930мл"})      # other fat
    assert not _same(a, {"name": "Кефир 2,5% «Простоквашино»", "size": "930 мл"})               # other product
    assert _display_size({"name": "Молоко 2.5%, 930мл", "size": "958 г"}) == "930мл"
    assert not _same({"name": "Лепешки тортильи MISSION пшеничные со злаками", "size": "250 г"}, {"name": "Лепешки Mission пшеничные тортильи гриль 250г"})
    print("ok")
