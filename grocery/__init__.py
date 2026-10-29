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


HEAD = "#\tмагазин\tid\tназвание\tфасовка\tцена ₽\tбез скидки\tскидка\tза кг/л/шт\tрейтинг\tналичие\tссылка"


def search(store, query, tag=None, sort="popular", page=1, limit=30):
    store = _store(store)
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    r = STORES[store].search(query, tag=tag, sort=sort, page=page, limit=limit)
    if isinstance(r, str):          # a site's own message: bot check, unknown tag…
        return r
    items = r["items"][:limit]
    head = [f"{NAMES[store]} · «{query}»" + (f" · тег «{tag}»" if tag else "")
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


def compare(query, stores=None, tag=None, limit=8, strict=True):
    """Search every store at once (each site has its own tab and lock) and put the results in one table:
    groups of the same product (see _same) first, cheapest per kg/l inside a group."""
    keys = [_store(s) for s in stores] if stores else list(STORES)

    def one(s):
        try:
            r = STORES[s].search(query, tag=tag, sort="popular", page=1, limit=max(limit * 3, 20) if strict else limit)
            if isinstance(r, str):
                return s, r
            hits = [p for p in r["items"] if not strict or _relevant(p.get("name"), query)]
            # no name has every word («соус для фрикаделек»): the site's own best matches, marked as such
            return s, hits[:limit] or [dict(p, name=p.get("name", "") + " (≈ похожее)") for p in r["items"][:min(limit, 4)]]
        except Exception as e:
            return s, f"ошибка: {str(e)[:150]}"

    with ThreadPoolExecutor(len(keys)) as ex:
        results = list(ex.map(one, keys))
    notes, flat = [], []
    for s, items in results:
        if isinstance(items, str):
            notes.append(f"{NAMES[s]}: {items.splitlines()[0]}")
        else:
            flat += [(s, p) for p in items]
    clusters = []                      # greedy: each product joins the first cluster it matches
    for s, p in flat:
        c = next((c for c in clusters if all(_same(p, q) for _, q in c)), None)
        if c is None:
            clusters.append([(s, p)])
        else:
            c.append((s, p))
    same = {i: c for i, c in enumerate(clusters) if len({s for s, _ in c}) > 1}
    rest = [x for i, c in enumerate(clusters) if i not in same for x in c]

    def per_unit(x):
        u = unit_price(x[1])
        return float(u.split()[0]) if u else float("inf")

    lines = [f"Сравнение «{query}»" + (f" · тег «{tag}»" if tag else "") + f" · по {limit} первых из поиска каждого магазина"]
    lines += notes
    lines.append("Одинаковые товары в разных магазинах (фасовка, проценты и слова названия совпадают; сверяй названия), "
                 "дешевле за кг/л — выше:" if same else "Одинаковых товаров не нашлось — сравнивай по цене за кг/л:")
    lines.append("группа\t" + HEAD)
    n = 0
    for gi, (k, v) in enumerate(sorted(same.items(), key=lambda kv: min(per_unit(x) for x in kv[1])), 1):
        for s, p in sorted(v, key=per_unit):
            n += 1
            lines.append(f"{gi}\t" + _row(n, s, p))
    if rest:
        lines.append("Остальное, дешевле за кг/л — выше:" if same else "")
        for s, p in sorted(rest, key=lambda x: ("(≈ похожее)" in (x[1].get("name") or ""), per_unit(x))):   # exact matches first
            n += 1
            lines.append("—\t" + _row(n, s, p))
    return "\n".join(x for x in lines if x is not None)


def item(store, id_or_url, full=False):
    store = _store(store)
    p = STORES[store].product(id_or_url)
    if isinstance(p, str):
        return p
    price, old = p.get("price"), p.get("old")
    lines = [f"{NAMES[store]} · {p.get('name', '')}" + (f" · {p['brand']}" if p.get("brand") else ""), p.get("url", ""),
             f"id: {p.get('id')}" + (f" · штрихкод {p['ean']}" if p.get("ean") else "") + (f" · фасовка {_display_size(p)}" if _display_size(p) else "")]
    if price is not None:
        lines.append(f"цена: {price} ₽" + (f", без скидки {old} ₽ (−{round(100 - price * 100 / old)}%)" if old and old > price else "")
                     + (f", {unit_price(p)}" if unit_price(p) else ""))
    lines.append("в наличии" if p.get("available", True) else "⛔ нет в наличии")
    if p.get("rating"):
        lines.append(f"рейтинг {p['rating']}" + (f", отзывов {p['reviews']}" if p.get("reviews") else ""))
    lines += p.get("extra") or []
    lines += composition.describe(p.get("composition"), p.get("nutrition"), p.get("composition_extra"))
    if p.get("photos"):
        lines.append("фото (shop_images): " + " ".join(p["photos"][:8]))
    desc = p.get("description") or ""
    if desc:
        lines.append("\nописание: " + (desc if full else desc[:2000]))
    return "\n".join(x for x in lines if x)


RANKS = {"price": "цена за кг/л ↑", "sugar": "сахар на 100 г ↑", "kcal": "ккал на 100 г ↑", "protein": "белок на 100 г ↓",
         "fat": "жир на 100 г ↑", "ingredients": "число ингредиентов ↑"}


def _rank_value(p, rank):
    """Sort key, smaller is better; unknown values go last."""
    n, comp = p.get("nutrition") or {}, p.get("composition") or ""
    comp_all = "; ".join((comp, p.get("composition_extra") or "", p.get("name") or ""))   # «74% какао» is often only in the name
    inf = float("inf")
    if rank == "price":
        u = unit_price(p)
        return float(u.split()[0]) if u else inf
    if rank == "sugar":
        v = n.get("sugar", n.get("carbs"))
        return inf if v is None else v
    if rank in ("kcal", "fat"):
        return n.get(rank, inf)
    if rank == "protein":
        return -n["protein"] if n.get("protein") is not None else inf
    if rank == "ingredients":
        return len(composition.parse(comp)["ingredients"]) if comp else inf
    v = composition.percent_of(rank.lstrip("%"), comp_all)   # "%какао": more is better
    return -v if v is not None else inf


def _relevant(name, query):
    """Every word of the query (by its first four letters) is in the name: sites pad their results with
    neighbours — dried fish for «рыбные котлеты», chicken cutlets in Лавка."""
    stems = [w[:4] for w in re.findall(r"[а-яёa-z]{3,}", (query or "").lower()) if w not in ("для", "или", "под", "как")]
    if re.search(r"\bкорм|для (кошек|собак)", (name or "").lower()) and "корм" not in (query or "").lower():
        return False                       # pet food: «Корм … курица-тунец» is not «тунец»
    return all(st in (name or "").lower().replace("ё", "е") for st in (x.replace("ё", "е") for x in stems))


def compare_details(query=None, stores=None, tag=None, limit=5, rank="price", items=None, strict=True):
    """Composition and nutrition side by side: either the first `limit` search results of every store,
    or the given items ["store:id", …]. Ranked by `rank` (see RANKS, or "%word" — share of that ingredient)."""
    if rank not in RANKS and not rank.startswith("%"):
        return f"rank: одно из {', '.join(RANKS)} или «%ингредиент» (например %какао, %томат, %мясо)"
    if items:
        wanted = {}
        for x in items:
            s, _, pid = x.partition(":")
            wanted.setdefault(_store(s), []).append(pid.strip())
    else:
        found = {}
        keys = [_store(s) for s in stores] if stores else list(STORES)

        def one(s):
            try:
                r = STORES[s].search(query, tag=tag, sort="popular", page=1, limit=max(limit * 4, 20))
                if isinstance(r, str):
                    return s, r
                hits = [p for p in r["items"] if not strict or _relevant(p.get("name"), query)] or r["items"][:min(limit, 3)]
                return s, [p["id"] for p in hits[:limit]] or f"по «{query}» ничего не нашлось"
            except Exception as e:
                return s, f"ошибка: {str(e)[:150]}"
        with ThreadPoolExecutor(len(keys)) as ex:
            found = dict(ex.map(one, keys))
        wanted = {s: v for s, v in found.items() if not isinstance(v, str)}
    notes = [f"{NAMES[s]}: {v.splitlines()[0]}" for s, v in (found.items() if not items else []) if isinstance(v, str)]

    def details(s):
        out = []
        for pid in wanted[s]:                 # one store's cards one after another: its tab is shared
            try:
                p = STORES[s].product(pid)
            except Exception as e:
                p = f"ошибка: {str(e)[:150]}"
            out.append((s, pid, p))
        return out
    with ThreadPoolExecutor(max(1, len(wanted))) as ex:
        got = [x for chunk in ex.map(details, list(wanted)) for x in chunk]
    ok = [(s, p) for s, pid, p in got if not isinstance(p, str)]
    notes += [f"{NAMES[s]} {pid}: {p.splitlines()[0]}" for s, pid, p in got if isinstance(p, str)]
    ok.sort(key=lambda x: _rank_value(x[1], rank))
    head = (f"Сравнение состава" + (f" «{query}»" if query else "") + f" · порядок: {RANKS.get(rank) or 'доля «' + rank.lstrip('%') + '» ↓'}"
            + f" · товаров {len(ok)}")
    lines = [head] + notes
    for i, (s, p) in enumerate(ok, 1):
        price = p.get("price")
        val = ""
        if rank.startswith("%"):
            v = composition.percent_of(rank.lstrip("%"), "; ".join((p.get("composition") or "", p.get("composition_extra") or "", p.get("name") or "")))
            val = f" · {rank.lstrip('%')}: {v:g}%" if v is not None else f" · {rank.lstrip('%')}: % не указан"
        rating = f" · рейтинг {p['rating']}" + (f" ({p['reviews']})" if p.get("reviews") else "") if p.get("rating") else ""
        lines.append(f"\n{i}. {NAMES[s]} · {p.get('name', '')} · {price} ₽" + (f" ({unit_price(p)})" if unit_price(p) else "")
                     + ("" if p.get("available", True) else " · нет в наличии") + val + rating + f" · {s}:{p.get('id')}")
        lines.append(f"   {p.get('url', '')}")
        lines += ["   " + x for x in composition.describe(p.get("composition"), p.get("nutrition"), p.get("composition_extra"))]
    return "\n".join(lines)


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
