"""Which store sells what: the one table the server's routing rule and shop_stores() are made from.

Why: with two dozen stores an agent searched electronics on Lamoda and headphones in a grocery. Each store says
what it sells — a specialist by its categories, a marketplace as «everything but» — in one taxonomy below.
"""

# category -> what it holds; a store names categories, never its own words for them
CATEGORIES = {
    "phones": "смартфоны, планшеты, умные часы и браслеты, аксессуары к ним",
    "computers": "ноутбуки, ПК, мониторы, комплектующие, периферия, сетевое оборудование, оргтехника",
    "tv_photo": "телевизоры, проекторы, фото- и видеокамеры, экшн-камеры, дроны",
    "audio": "наушники, колонки, Hi-Fi и плееры, усилители и ЦАП, микрофоны",
    "gaming": "игровые консоли, игры, игровые кресла и периферия",
    "gadgets": "гаджеты: умный дом, электронные книги, электротранспорт, зарядки и кабели",
    "appliances_big": "крупная бытовая техника: холодильники, стиральные и посудомоечные машины, плиты, встраиваемая техника",
    "appliances_small": "мелкая техника: кухонная (кофемашины, чайники, микроволновки), уборка (пылесосы, роботы), "
                        "климат (кондиционеры, обогреватели), уход (фены, бритвы)",
    "tools": "инструменты, ремонт, дача и сад",
    "auto": "автотовары: шины, автоэлектроника, аксессуары",
    "home": "дом: мебель, посуда, текстиль, свет, хозтовары и бытовая химия",
    "clothes": "одежда, обувь, сумки и аксессуары",
    "beauty": "косметика, парфюмерия, уход за собой",
    "kids": "детские товары и игрушки",
    "sport": "спорт, туризм, отдых",
    "hobby": "книги, канцелярия, хобби и творчество",
    "pets": "зоотовары",
    "health": "аптека, витамины, медицинская техника",
    "food": "продукты питания и напитки",
    "used": "б/у и с рук",
}


class Store:
    """A store's assortment: a specialist sells some categories, a broad store everything but lacks (one or the other)."""

    def __init__(self, name, sells=None, lacks=None, note=""):
        if (sells is None) == (lacks is None) or sells == set():
            raise ValueError(f"{name}: sells (непустой) или lacks — одно из двух")
        unknown = set(sells or lacks) - set(CATEGORIES)
        if unknown:
            raise ValueError(f"{name}: нет таких категорий {sorted(unknown)}")
        self.name, self.note = name, note
        self.sells, self.lacks = frozenset(sells or ()), (None if lacks is None else frozenset(lacks))

    def has(self, category):
        return category in self.sells if self.lacks is None else category not in self.lacks

    def what(self):
        if self.lacks is None:
            return ", ".join(c for c in CATEGORIES if c in self.sells)
        return "всё, кроме " + ", ".join(c for c in CATEGORIES if c in self.lacks) if self.lacks else "всё"


TECH = {"phones", "computers", "tv_photo", "audio", "gaming", "gadgets", "appliances_big", "appliances_small"}
# keys are the tools' prefixes (ozon_*, grocery_*); assortments by the sites' own catalogues, 2026-11
STORES = {
    "ozon": Store("Ozon", lacks={"used"}, note="маркетплейс; еду — только если пользователь сам назвал"),
    "wb": Store("Wildberries", lacks={"used"}, note="маркетплейс; сильнее всего одежда, обувь, дом; еду — только по просьбе"),
    "ym": Store("Яндекс Маркет", lacks={"used"}, note="маркетплейс; много техники; еду — только по просьбе"),
    "ali": Store("AliExpress", lacks={"food", "health", "used"}, note="маркетплейс, много из-за рубежа (дольше везут): гаджеты, "
                                                                      "запчасти, хобби, мелочи"),
    "avito": Store("Авито", sells={"used"}, note="объявления: б/у и с рук, есть и новое от частных продавцов; доставка Авито"),
    "lamoda": Store("Lamoda", sells={"clothes", "beauty", "kids", "sport"}, note="одежда и обувь — основное; детская и спортивная одежда"),
    "goldapple": Store("Золотое яблоко", sells={"beauty"}, note="косметика и парфюмерия; есть фены и приборы для красоты"),
    "grocery": Store("Продуктовые (Лента, Перекрёсток, Пятёрочка, Самокат, Яндекс Лавка, ВкусВилл)", sells={"food"},
                     note="еда и напитки — сюда первым делом; там же бытовая химия, корм для животных, детское питание"),
    "mvideo": Store("М.Видео", sells=TECH, note="электроника и бытовая техника, официальная гарантия; есть товары других продавцов"),
    "eldorado": Store("Эльдорадо", sells=TECH, note="то же, что М.Видео (общий каталог), свои цены и наличие"),
    "dns": Store("DNS", sells=TECH | {"tools", "auto", "home"}, note="электроника, комплектующие ПК — сильнее всех; техника, "
                                                                     "инструменты; есть продавцы маркетплейса"),
    "citilink": Store("Ситилинк", sells=TECH | {"tools", "auto", "home"}, note="электроника и техника, стройка и ремонт, "
                                                                               "товары для геймеров"),
}


def where(category):
    """The stores that sell category, specialists before the broad ones, in the table's order."""
    has = [k for k, s in STORES.items() if s.has(category)]
    return [k for k in has if STORES[k].lacks is None] + [k for k in has if STORES[k].lacks is not None]


def _line(key):
    s = STORES[key]
    return f"{s.name} ({key}_*) — {s.note}"


def answer(category=""):
    """shop_stores(): the stores for one category, or the whole map with the categories."""
    if not category:
        return "\n".join(["магазины и что в них искать (category — для shop_stores(category)):"]
                         + [f"{s.name} ({k}_*): {s.what()} — {s.note}" for k, s in STORES.items()]
                         + ["", "категории:"] + [f"{c} — {d}" for c, d in CATEGORIES.items()])
    if category not in CATEGORIES:
        return f"нет такой категории «{category}»: " + ", ".join(CATEGORIES)
    keys = where(category)
    special = [_line(k) for k in keys if STORES[k].lacks is None]
    broad = [_line(k) for k in keys if STORES[k].lacks is not None]
    return "\n".join([f"{category} — {CATEGORIES[category]}"] + (["специализированные: " + "; ".join(special)] if special else [])
                     + (["широкий ассортимент: " + "; ".join(broad)] if broad else []))


def routing():
    """For the server's instructions: the categories with the same specialists on one line, then the broad stores once."""
    groups = {}
    for c in CATEGORIES:
        names = tuple(STORES[k].name for k in where(c) if STORES[k].lacks is None)
        if names:
            groups.setdefault(names, []).append(c)
    broad = [s.name for s in STORES.values() if s.lacks is not None]
    return [f"{', '.join(cats)}: {', '.join(names)}" for names, cats in groups.items()] + [f"везде, кроме названного у них: {', '.join(broad)}"]
