"""Composition («Состав») split into ingredients, plus nutrition per 100 g, for comparing products.

Sites give the composition as one line of text written by the manufacturer, e.g.
«Состав: какао тёртое, сахар, какао-масло, эмульгатор (лецитин соевый). Какао-продукты не менее 70%.»
We split it at top-level commas (not inside brackets, not in «3,2%»), keep sub-ingredients in brackets,
pull out percentages and flag what people usually choose by: where sugar is in the list (ingredients go in
descending order by weight), sweeteners, palm oil, E-numbers, flavourings, starch.
"""
import re

TRACES = re.compile(r"(?:может\s+содержать|возможно\s+наличие|возможны\s+следы|продукт\s+может\s+содержать)[^.]*", re.I)
SUGARS = re.compile(r"(?<!без )сахар(?!о)(?!н\w*\s+колер)|сироп|глюкоз|фруктоз|декстроз|мальтодекстрин|патока|\bм[её]д\b|инверт|лактоз(?!а\s*не)|сахароз", re.I)
SWEETENERS = re.compile(r"аспартам|сукралоз|ацесульфам|цикламат|сахарин|стеви|ребаудиоз|эритрит|мальтит|сорбит(?!ан)|ксилит|E ?95[0-9]|E ?96[0-9]", re.I)
FLAGS = {
    "пальмовое масло": re.compile(r"пальм", re.I),
    "ароматизатор": re.compile(r"ароматизатор", re.I),
    "крахмал": re.compile(r"крахмал", re.I),
    "консервант": re.compile(r"консервант|сорбат|бензоат", re.I),
    "усилитель вкуса": re.compile(r"глутамат|усилител", re.I),
    "краситель": re.compile(r"краситель", re.I),
    "загуститель": re.compile(r"загустител|камедь|каррагинан", re.I),
}
ECODE = re.compile(r"\b[EЕ]\s?-?(\d{3,4}[a-zа-я]?)\b")
PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def _split_top(text, seps=",;"):
    """Split at separators outside () and [], and not at a comma inside a number like 3,2."""
    out, depth, cur = [], 0, []
    for i, ch in enumerate(text):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in seps and depth == 0 and not (ch == "," and 0 < i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit()):
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [s.strip(" .\n\t") for s in out if s.strip(" .\n\t")]


def parse(text):
    """{"ingredients": [str], "percents": {ingredient: pct}, "traces": str, "notes": [str]} from a composition text."""
    t = re.sub(r"^\s*состав\s*[:.\-–—]?\s*", "", (text or "").strip(), flags=re.I)
    traces = "; ".join(m.group(0).strip() for m in TRACES.finditer(t))
    t = TRACES.sub("", t)
    # sentences after the list («Какао-продукты не менее 70%.», «Пищевая ценность…») are notes, not ingredients
    parts = re.split(r"\.\s+(?=[А-ЯЁA-Z])", t, maxsplit=1)
    head, notes = parts[0], [s.strip(" .;") for s in re.split(r"\.\s+|\.$", parts[1]) if s.strip(" .;")] if len(parts) > 1 else []
    items = _split_top(head)
    percents = {}
    for s in items:
        m = PCT.search(re.sub(r"\(.*?\)", "", s)) or PCT.search(s)
        if m:
            percents[s] = float(m.group(1).replace(",", "."))
    return {"ingredients": items, "percents": percents, "traces": traces, "notes": notes}


def percent_of(word, text):
    """Share of an ingredient by name: «какао» in «Какао-продукты не менее 70%» or «какао тёртое 55%» → 70.0."""
    w = re.escape(word.lower().rstrip("аеиоуыяюь")[:6] or word.lower())
    best = None
    pats = (rf"{w}[^,;.()%]{{0,40}}?(\d+(?:[.,]\d+)?)\s*%",          # какао-продукты не менее 72%
            rf"(\d+(?:[.,]\d+)?)\s*%[^,;.()]{{0,25}}?{w}",           # 74% какао
            rf"%[^;:]{{0,25}}{w}[^;:]{{0,5}}:\s*(\d+(?:[.,]\d+)?)")   # «% содержания какао: 72» (Перекрёсток)
    for pat in pats:
        for m in re.finditer(pat, (text or "").lower()):
            v = float(m.group(1).replace(",", "."))
            if 0 < v <= 100:                                       # the sites sometimes fill 0
                best = v if best is None else max(best, v)
    return best


def flags(text, items=None):
    """Short facts: «сахар — 2-й из 6», «подсластители: сукралоза», «пальмовое масло», «E-добавки: 6».
    In a sugar-free product a sweetener name like «сорбит» is not «sugar»."""
    text = text or ""
    items = items if items is not None else parse(text)["ingredients"]
    sw = sorted({m.group(0).lower() for m in SWEETENERS.finditer(text)})
    e = sorted({"E" + m.group(1).upper() for m in ECODE.finditer(text)})
    return (_sugar(items) + (["подсластители: " + ", ".join(sw)] if sw else []) + [name for name, rx in FLAGS.items() if rx.search(text)]
            + ([f"E-добавки ({len(e)}): " + " ".join(e)] if e else []))


def _head(s):
    """An ingredient's own name, without its bracketed parts: «томатный соус (паста, сахар…)» → «томатный соус»."""
    return re.sub(r"\(.*", "", s).strip()


def _sugary(s):
    return SUGARS.search(s) and not SWEETENERS.search(s)


def _sugar(items):
    """Where sugar is in the list (ingredients go by weight, largest first): an ingredient of its own,
    inside a compound one («томатный соус (…, сахар)»), or none at all."""
    own = next((i for i, s in enumerate(items, 1) if _sugary(_head(s))), None)
    inner = next((i for i, s in enumerate(items, 1) if _sugary(s)), None)
    if not own and not inner:
        return ["без сахара в составе"] if items else []
    within = [f"сахар внутри «{_head(items[inner - 1])[:40]}» ({inner}-й компонент из {len(items)})"] if inner and inner != own else []
    return _own_sugar(items, own) + within


def _own_sugar(items, own):
    """«сахар — 2-й из 6», or «сахар как «мед» — 2-й из 3» for another kind of sugar."""
    if not own:
        return []
    name = _head(items[own - 1])
    kind = "сахар" if SUGARS.search(name).group(0).lower().startswith("сахар") else f"сахар как «{name[:40]}»"
    return [f"{kind} — {own}-й из {len(items)}"]


NUTRIENTS = {"kcal": r"ккал|калорийн|энергетическ", "protein": r"белк", "fat": r"жир", "carbs": r"углевод", "sugar": r"сахар"}


def nutrition_from_text(text):
    """{"kcal", "protein", "fat", "carbs", "sugar"} per 100 g from «Белки 3 г, жиры 3,2 г, углеводы 4,7 г, в т.ч. сахара 4,7 г; 58 ккал»."""
    out = {}
    low = (text or "").lower()
    for k, rx in NUTRIENTS.items():
        if k == "kcal":
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*ккал", low) or re.search(rf"(?:{rx})[^\d]{{0,30}}(\d+(?:[.,]\d+)?)", low)
        else:
            m = re.search(rf"(?:{rx})[а-я.]*\s*(?:\([а-я ]*\))?\s*[:\-–—]?\s*(?:[а-я. ]{{0,12}}?)(\d+(?:[.,]\d+)?)", low)
        if m:
            out[k] = float(m.group(1).replace(",", "."))
    m = re.search(r"добавленн\w*\s+сахар\w*\s*[:\-–—]?\s*(\d+(?:[.,]\d+)?)", low)     # ВкусВилл also gives added sugar
    if m:
        out["added_sugar"] = float(m.group(1).replace(",", "."))
    return out


def nutrition_line(n):
    """«на 100 г: 230 ккал, Б 3, Ж 12, У 25, сахара 20»; sugar unknown but carbs known → «сахара ≤25»."""
    if not n:
        return ""
    parts = [f"{n['kcal']:g} ккал" if n.get("kcal") is not None else ""]
    parts += [f"{label} {n[k]:g}" for k, label in (("protein", "Б"), ("fat", "Ж"), ("carbs", "У")) if n.get(k) is not None]
    if n.get("sugar") is not None:
        parts.append(f"сахара {n['sugar']:g}" + (f" (добавленного {n['added_sugar']:g})" if n.get("added_sugar") is not None else ""))
    elif n.get("carbs") is not None:
        parts.append(f"сахара ≤{n['carbs']:g} (сайт не пишет, не больше углеводов)")
    return "на 100 г: " + ", ".join(p for p in parts if p)


def describe(composition, nutrition=None, extra=None):
    """Lines for a product card or comparison: ingredients numbered, percents, flags, traces, nutrition.
    extra: the site's own composition facts outside the text («Содержания какао: до 35%»)."""
    if not composition and not nutrition:
        return ["состав: сайт не указывает"] + ([f"о составе: {extra}"] if extra else [])
    lines = []
    if composition:
        p = parse(composition)
        lines.append(f"состав ({len(p['ingredients'])}): " + "; ".join(f"{i}) {s}" for i, s in enumerate(p["ingredients"], 1)))
        if p["notes"]:
            lines.append("в составе отмечено: " + "; ".join(p["notes"]))
        f = flags(composition, p["ingredients"])
        if f:
            lines.append("по составу: " + "; ".join(f))
        if p["traces"]:
            lines.append("аллергены-следы: " + p["traces"])
    if extra:
        lines.append(f"о составе: {extra}")
    if nutrition:
        lines.append(nutrition_line(nutrition))
    return lines


if __name__ == "__main__":
    choc = ("Состав: какао тёртое, сахар, масло какао, эмульгатор (лецитин соевый), ароматизатор ванилин. "
            "Какао-продукты не менее 72%. Может содержать следы орехов.")
    p = parse(choc)
    assert p["ingredients"] == ["какао тёртое", "сахар", "масло какао", "эмульгатор (лецитин соевый)", "ароматизатор ванилин"], p
    assert p["traces"].startswith("Может содержать"), p
    assert percent_of("какао", choc) == 72.0
    assert percent_of("какао", "Шоколад тёмный Ritter Sport 74% какао; % содержания какао: 0") == 74.0
    assert percent_of("какао", "Тип продукта: Шоколад; % содержания какао: 72") == 72.0
    assert flags("какао тертое, мед, масло какао")[0] == "сахар как «мед» — 2-й из 3"
    f = flags("скумбрия, томатный соус (паста томатная, сахар, соль)")
    assert f[0] == "сахар внутри «томатный соус» (2-й компонент из 2)", f
    assert flags(choc)[0] == "сахар — 2-й из 5" and "ароматизатор" in flags(choc)
    soda = "вода питьевая, диоксид углерода, регулятор кислотности лимонная кислота, подсластители (аспартам, ацесульфам калия), консервант бензоат натрия (E211), ароматизатор"
    f = flags(soda)
    assert f[0] == "без сахара в составе" and any(x.startswith("подсластители") for x in f) and "E-добавки (1): E211" in f, f
    assert flags("вода, краситель сахарный колер IV, подсластитель сукралоза")[0] == "без сахара в составе"
    milk = "молоко нормализованное, 3,2%"
    assert parse(milk)["ingredients"] == ["молоко нормализованное", "3,2%"] or len(parse(milk)["ingredients"]) <= 2
    assert parse("томаты (60%), вода, соль")["percents"] == {"томаты (60%)": 60.0}
    n = nutrition_from_text("Пищевая ценность на 100 г: белки 3 г, жиры 3,2 г, углеводы 4,7 г, в т.ч. сахара 4,7 г; энергетическая ценность 58 ккал")
    assert n == {"kcal": 58.0, "protein": 3.0, "fat": 3.2, "carbs": 4.7, "sugar": 4.7}, n
    n = nutrition_from_text("белки 0 г, жиры 0 г, углеводы 12 г,, в том числе сахара (общие) - 12 г, в том числе добавленный сахар - 12 г; 48 ккал")
    assert n == {"kcal": 48.0, "protein": 0.0, "fat": 0.0, "carbs": 12.0, "sugar": 12.0, "added_sugar": 12.0}, n
    assert nutrition_line({"carbs": 10.6, "kcal": 42}).endswith("сахара ≤10.6 (сайт не пишет, не больше углеводов)")
    print("ok")
