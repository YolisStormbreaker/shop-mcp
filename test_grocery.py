"""Store-independent grocery tools: one store's table, the all-stores comparison, the composition comparison
and the product card, from the product dicts the store modules return. The stores are fakes; no requests to shops.
Run: .venv/bin/python -B -m unittest -v test_grocery"""
import re
import unittest
from unittest.mock import patch

import grocery


def prod(id, name, price, size="", old=None, available=True, rating=None, reviews=None, brand="", ean=None, url=None, **card):
    return {"id": id, "name": name, "brand": brand, "size": size, "price": price, "old": old, "available": available,
            "url": f"https://shop/{id}" if url is None else url, "rating": rating, "reviews": reviews, "ean": ean, **card}


class Store:
    """A store module: search() answers `found` (an exception is raised), product(id) answers cards[id]."""
    def __init__(self, found=None, cards=None, **functions):
        self.found, self.cards, self.searched, self.opened = found, cards or {}, [], []
        self.__dict__.update(functions)

    def search(self, query, **kw):
        self.searched.append((query, kw))
        if isinstance(self.found, Exception):
            raise self.found
        return self.found

    def product(self, pid):
        self.opened.append(pid)
        if isinstance(self.cards[pid], Exception):
            raise self.cards[pid]
        return self.cards[pid]


def stores(**fakes):
    """Only these stores, in the given order; key 'ka5' stands for '5ka'."""
    return patch.dict(grocery.STORES, {k.replace("ka5", "5ka"): v for k, v in fakes.items()}, clear=True)


def found(*items, **more):
    return {"items": list(items), **more}


HEAD = "#\tмагазин\tid\tназвание\tфасовка\tцена ₽\tбез скидки\tскидка\tза кг/л/шт\tрейтинг\tналичие\tссылка"
BOT = "⚠️ проверка на бота\nпройди её во вкладке сайта"
SLOW = RuntimeError("Chrome не ответил за 30 с " + "!" * 200)


def row(*cells):
    return "\t".join(str(c) for c in cells)


class SearchTests(unittest.TestCase):
    def test_table_of_one_store(self):
        lenta = Store(found(prod("k1", "Кефир Простоквашино 2,5% 930 мл", 99.9, old=119.9, rating=4.8, reviews=120),
                            prod("k2", "Кефир Домик в деревне 3,2%", 150, size="1 кг", old=150, rating=4.5, available=False),
                            prod("k3", "Кефир фермерский 2х0,5 л", None, old=100),
                            prod("k4", "Яйца С1 10 шт", 99), prod("k5", "Сыр Российский 200гр.", 150), prod("k6", "лишний", 1),
                            total=41, note="сайт не сортирует по цене: отсортирована эта страница",
                            facets=[f"тег {i}" for i in range(45)], url="https://lenta/search?q=кефир"))
        with stores(lenta=lenta):
            got = grocery.search("Лента", "кефир", tag="без лактозы", sort="price", page=2, limit=5)
        self.assertEqual(lenta.searched, [("кефир", {"tag": "без лактозы", "sort": "price", "page": 2, "limit": 5})])
        self.assertEqual(got, "\n".join([
            "Лента · «кефир» · тег «без лактозы» · найдено 41 · страница 2 · https://lenta/search?q=кефир",
            "сайт не сортирует по цене: отсортирована эта страница",
            "теги и фильтры сайта (передавай в tag): " + "; ".join(f"тег {i}" for i in range(40)),
            HEAD,
            row(1, "Лента", "k1", "Кефир Простоквашино 2,5% 930 мл", "930 мл", 99.9, 119.9, "−17%", "107 ₽/л", "4.8 (120)", "", "https://shop/k1"),
            row(2, "Лента", "k2", "Кефир Домик в деревне 3,2%", "1 кг", 150, "", "", "150 ₽/кг", "4.5", "нет в наличии", "https://shop/k2"),
            row(3, "Лента", "k3", "Кефир фермерский 2х0,5 л", "2х0,5 л", "", "", "", "", "", "", "https://shop/k3"),
            row(4, "Лента", "k4", "Яйца С1 10 шт", "10 шт", 99, "", "", "10 ₽/шт", "", "", "https://shop/k4"),
            row(5, "Лента", "k5", "Сыр Российский 200гр.", "200гр.", 150, "", "", "750 ₽/кг", "", "", "https://shop/k5")]))

    def test_nothing_found(self):
        with stores(ka5=Store(found())):
            self.assertEqual(grocery.search("5ka", ""), "Пятёрочка · «» · страница 1 · \n" + HEAD + "\n(пусто)")

    def test_site_message_as_is(self):
        with stores(ka5=Store(BOT)):
            self.assertEqual(grocery.search("Пятёрочка", "кефир"), BOT)

    def test_unknown_sort_asks_nothing_of_the_site(self):
        five = Store(found())
        with stores(ka5=five):
            self.assertEqual(grocery.search("5ka", "кефир", sort="cheap"), "sort: одно из popular, price, price_desc, discount, rating")
        self.assertEqual(five.searched, [])


class StoreNameTests(unittest.TestCase):
    def test_names_and_aliases(self):
        fakes = {k: Store(cart=lambda k=k: f"корзина {k}") for k in ("lenta", "samokat", "lavka", "perekrestok", "5ka", "vkusvill")}
        with patch.dict(grocery.STORES, fakes, clear=True):
            for name, key in (("Пятёрочка", "5ka"), (" ПЯТЕРОЧКА ", "5ka"), ("pyaterochka", "5ka"), ("5ka", "5ka"), ("Лента", "lenta"),
                              ("самокат", "samokat"), ("Лавка", "lavka"), ("Яндекс Лавка", "lavka"), ("перекресток", "perekrestok"),
                              ("Перекрёсток", "perekrestok"), ("ВкусВилл", "vkusvill"), ("VKUSVILL", "vkusvill")):
                self.assertEqual(grocery.call(name, "cart"), f"корзина {key}", name)
            with self.assertRaisesRegex(ValueError, "^store: одно из lenta, samokat, lavka, perekrestok, 5ka, vkusvill$"):
                grocery.call("ozon", "cart")
            with self.assertRaises(ValueError):
                grocery.search(None, "кефир")

    def test_call_passes_arguments_or_says_the_site_has_none(self):
        lenta = Store(add_to_cart=lambda id_or_url, quantity=1: f"добавлено {id_or_url} × {quantity}")
        with stores(lenta=lenta, samokat=Store()):
            self.assertEqual(grocery.call("Лента", "add_to_cart", "l1", 3), "добавлено l1 × 3")
            self.assertEqual(grocery.call("самокат", "favorites"), "Самокат: favorites на этом сайте нет")


L1 = prod("l1", "Кефир Простоквашино 2,5% 930 мл", 99.9, brand="Простоквашино", rating=4.8, reviews=120)
L2 = prod("l2", "Кефир Вологодский 3,2%", 80, size="500 г")
L3 = prod("l3", "Ряженка Простоквашино 4%", 70, size="500 г")
L4 = prod("l4", "Кефир Лента 1%", 60, size="1 л")
L5 = prod("l5", "Кефир Лента 1%", 62, size="1000 мл")
F1 = prod("f1", "Кефир ПРОСТОКВАШИНО 2.5% БЗМЖ 930мл", 95, old=110)
F2 = prod("f2", "Кефир Вологодский 3,2% 500г", 85)
V1 = prod("v1", "Кефир 2,5% 930 мл", 89)
V2 = prod("v2", "Кефир «Простоквашино» 2,5%", 101, size="930 мл", brand="ПРОСТОКВАШИНО")
V3 = prod("v3", "Кефир детский 3,2% 200 мл", None)
AIRAN = [prod(f"y{i}", f"Айран {n}", p) for i, (n, p) in
         enumerate((("Тан 500 мл", 70), ("Эфир 1 л", 90), ("горный 330 мл", 55), ("1,5% 250 мл", 40), ("лишний 2 л", 100)), 1)]


class CompareTests(unittest.TestCase):
    def test_all_stores_grouped(self):
        fakes = dict(lenta=Store(found(L1, L2, L3, L4, L5)), samokat=Store(SLOW), lavka=Store(found(*AIRAN)),
                     perekrestok=Store(BOT), ka5=Store(found(F1, F2)), vkusvill=Store(found(V1, V2, V3)))
        with stores(**fakes):
            got = grocery.compare("кефир")
        for s in fakes.values():
            self.assertEqual(s.searched, [("кефир", {"tag": None, "sort": "popular", "page": 1, "limit": 24})])
        self.assertEqual(got, "\n".join([
            "Сравнение «кефир» · по 8 первых из поиска каждого магазина",
            "Самокат: ошибка: " + str(SLOW)[:150],
            "Перекрёсток: ⚠️ проверка на бота",
            "Одинаковые товары в разных магазинах (фасовка, проценты и слова названия совпадают; сверяй названия), дешевле за кг/л — выше:",
            "группа\t" + HEAD,
            row(1, 1, "Пятёрочка", "f1", "Кефир ПРОСТОКВАШИНО 2.5% БЗМЖ 930мл", "930мл", 95, 110, "−14%", "102 ₽/л", "", "", "https://shop/f1"),
            row(1, 2, "Лента", "l1", "Кефир Простоквашино 2,5% 930 мл", "930 мл", 99.9, "", "", "107 ₽/л", "4.8 (120)", "", "https://shop/l1"),
            row(1, 3, "ВкусВилл", "v2", "Кефир «Простоквашино» 2,5%", "930 мл", 101, "", "", "109 ₽/л", "", "", "https://shop/v2"),
            row(2, 4, "Лента", "l2", "Кефир Вологодский 3,2%", "500 г", 80, "", "", "160 ₽/кг", "", "", "https://shop/l2"),
            row(2, 5, "Пятёрочка", "f2", "Кефир Вологодский 3,2% 500г", "500г", 85, "", "", "170 ₽/кг", "", "", "https://shop/f2"),
            "Остальное, дешевле за кг/л — выше:",
            row("—", 6, "Лента", "l4", "Кефир Лента 1%", "1 л", 60, "", "", "60 ₽/л", "", "", "https://shop/l4"),
            row("—", 7, "Лента", "l5", "Кефир Лента 1%", "1000 мл", 62, "", "", "62 ₽/л", "", "", "https://shop/l5"),
            row("—", 8, "ВкусВилл", "v1", "Кефир 2,5% 930 мл", "930 мл", 89, "", "", "96 ₽/л", "", "", "https://shop/v1"),
            row("—", 9, "ВкусВилл", "v3", "Кефир детский 3,2% 200 мл", "200 мл", "", "", "", "", "", "", "https://shop/v3"),
            row("—", 10, "Яндекс Лавка", "y2", "Айран Эфир 1 л (≈ похожее)", "1 л", 90, "", "", "90 ₽/л", "", "", "https://shop/y2"),
            row("—", 11, "Яндекс Лавка", "y1", "Айран Тан 500 мл (≈ похожее)", "500 мл", 70, "", "", "140 ₽/л", "", "", "https://shop/y1"),
            row("—", 12, "Яндекс Лавка", "y4", "Айран 1,5% 250 мл (≈ похожее)", "250 мл", 40, "", "", "160 ₽/л", "", "", "https://shop/y4"),
            row("—", 13, "Яндекс Лавка", "y3", "Айран горный 330 мл (≈ похожее)", "330 мл", 55, "", "", "167 ₽/л", "", "", "https://shop/y3")]))

    def test_chosen_stores_not_strict_nothing_in_common(self):
        fakes = dict(lenta=Store(found(L3, L4, L1)), ka5=Store(found()), samokat=Store(found(L1)))
        with stores(**fakes):
            got = grocery.compare("кефир", stores=["Лента", "пятёрочка"], tag="без лактозы", limit=2, strict=False)
        asked = [("кефир", {"tag": "без лактозы", "sort": "popular", "page": 1, "limit": 2})]
        self.assertEqual((fakes["lenta"].searched, fakes["ka5"].searched, fakes["samokat"].searched), (asked, asked, []))
        self.assertEqual(got, "\n".join([
            "Сравнение «кефир» · тег «без лактозы» · по 2 первых из поиска каждого магазина",
            "Одинаковых товаров не нашлось — сравнивай по цене за кг/л:",
            "группа\t" + HEAD,
            "",
            row("—", 1, "Лента", "l4", "Кефир Лента 1%", "1 л", 60, "", "", "60 ₽/л", "", "", "https://shop/l4"),
            row("—", 2, "Лента", "l3", "Ряженка Простоквашино 4%", "500 г", 70, "", "", "140 ₽/кг", "", "", "https://shop/l3")]))

    def test_same_product(self):
        """Two stores, one product each: grouped or not."""
        m = "Молоко Простоквашино пастеризованное 2,5% 930 мл"
        for a, b, same in (
                ({"name": "Молоко", "ean": "1"}, {"name": "Кефир", "ean": "1"}, True),           # the barcode decides
                ({"name": m, "ean": "1"}, {"name": m, "ean": "2"}, False),
                ({"name": m, "ean": "1"}, {"name": m}, True),                                     # one barcode: by name
                ({"name": "Молоко Простоквашино 2,5%"}, {"name": "Молоко Простоквашино 2,5%"}, False),    # no size
                ({"name": "Молоко Простоквашино 1 л"}, {"name": "Молоко Простоквашино 1 кг"}, False),
                ({"name": "Молоко Простоквашино 930 мл"}, {"name": "Молоко Простоквашино 925 мл"}, True),  # within 2%
                ({"name": "Молоко Простоквашино 930 мл"}, {"name": "Молоко Простоквашино 900 мл"}, False),
                ({"name": "Молоко Простоквашино 2,5% 930 мл"}, {"name": "Молоко Простоквашино 3,2% 930 мл"}, False),
                ({"name": m, "brand": "Простоквашино"}, {"name": m, "brand": "Домик в деревне"}, False),
                ({"name": m, "brand": "Простоквашино"}, {"name": m, "brand": "ПРОСТОКВАШИНО"}, True),
                ({"name": "Лепешки тортильи MISSION пшеничные со злаками", "size": "250 г"},
                 {"name": "Лепешки Mission пшеничные тортильи гриль 250г"}, False),
                ({"name": "Без ЗМЖ 1 л"}, {"name": "Без ЗМЖ 1 л"}, False)):                    # no significant words
            with self.subTest(a=a, b=b), stores(lenta=Store(found(dict(prod("a", "", 100), **a))),
                                                ka5=Store(found(dict(prod("b", "", 100), **b)))):
                self.assertEqual("Одинаковые товары" in grocery.compare("x", strict=False), same)

    def test_relevant_names(self):
        """strict: a name without every word of the query is only a «(≈ похожее)» fallback."""
        for name, query, kept in (("Кефир Простоквашино 2,5%", "кефир простоквашино", True),
                                  ("Котлеты из щуки", "рыбные котлеты", False),
                                  ("Корм для кошек тунец в желе", "тунец", False),
                                  ("Корм для кошек тунец", "корм тунец", True),
                                  ("Паштет для собак, говядина", "говядина", False),
                                  ("Свёкла отварная", "свекла", True),
                                  ("Свекла молодая", "свёкла", True),
                                  ("Соус к фрикаделькам", "соус для фрикаделек", True),
                                  ("Молоко 2,5%", "молоко ж", True)):
            with self.subTest(name=name, query=query), stores(lenta=Store(found(prod("x", name, 100)))):
                self.assertEqual("(≈ похожее)" not in grocery.compare(query), kept)


CHOC = prod("c1", "Шоколад горький Победа 72% 100 г", 189.99, old=239.99, rating=4.9, reviews=1234, brand="Победа", ean="4600000000001",
            photos=[f"https://img/{i}.jpg" for i in range(10)], description="абв " * 600,
            composition="Состав: какао тёртое, сахар, какао-масло, эмульгатор (лецитин соевый). Какао-продукты не менее 72%. "
                        "Может содержать следы орехов.",
            nutrition={"kcal": 540, "protein": 8, "fat": 38, "carbs": 35, "sugar": 30}, composition_extra="Содержание какао: 72%",
            extra=["доставка: завтра, бесплатно", "", "осталось мало"])


class ItemTests(unittest.TestCase):
    def item(self, pid, full=False):
        lenta = Store(cards={"c1": CHOC, "c2": prod("c2", "Вода", None, available=False, url=""),
                             "c3": prod("c3", "Хлеб Бородинский", 60, old=55, rating=4.2), "c4": "Лента: товар c4 не найден"})
        with stores(lenta=lenta):
            return grocery.item("Лента", pid, full)

    def test_full_card(self):
        self.assertEqual(self.item("c1"), "\n".join([
            "Лента · Шоколад горький Победа 72% 100 г · Победа", "https://shop/c1",
            "id: c1 · штрихкод 4600000000001 · фасовка 100 г",
            "цена: 189.99 ₽, без скидки 239.99 ₽ (−21%), 1900 ₽/кг", "в наличии", "рейтинг 4.9, отзывов 1234",
            "доставка: завтра, бесплатно", "осталось мало",
            "состав (4): 1) какао тёртое; 2) сахар; 3) какао-масло; 4) эмульгатор (лецитин соевый)",
            "в составе отмечено: Какао-продукты не менее 72%", "по составу: сахар — 2-й из 4",
            "аллергены-следы: Может содержать следы орехов", "о составе: Содержание какао: 72%",
            "на 100 г: 540 ккал, Б 8, Ж 38, У 35, сахара 30",
            "фото (shop_images): " + " ".join(f"https://img/{i}.jpg" for i in range(8)),
            "", "описание: " + "абв " * 500]))

    def test_full_description(self):
        self.assertTrue(self.item("c1", full=True).endswith("\nописание: " + "абв " * 600))

    def test_bare_card(self):
        self.assertEqual(self.item("c2"), "Лента · Вода\nid: c2\n⛔ нет в наличии\nсостав: сайт не указывает")

    def test_no_discount_no_unit_price_rating_without_reviews(self):
        self.assertEqual(self.item("c3"), "Лента · Хлеб Бородинский\nhttps://shop/c3\nid: c3\nцена: 60 ₽\nв наличии\nрейтинг 4.2\n"
                                          "состав: сайт не указывает")

    def test_site_message(self):
        self.assertEqual(self.item("c4"), "Лента: товар c4 не найден")


class CompareDetailsTests(unittest.TestCase):
    def test_search_every_store(self):
        k1, k2, s1 = prod("l1", "Кефир Простоквашино 2,5% 930 мл", 99.9, rating=4.8, reviews=120), prod("l2", "Кефир Лента 1%", 60, size="1 л"), \
            prod("s1", "Ряженка 4% 500 г", 70)
        lenta = Store(found(k1, prod("l9", "Ряженка", 50), k2, prod("l3", "Кефир третий", 1)),
                      cards={"l1": dict(k1, composition="молоко нормализованное, закваска", nutrition={"kcal": 53, "protein": 2.9, "fat": 2.5, "carbs": 4}),
                             "l2": dict(k2, price=None, available=False, rating=4.5, composition="", nutrition={})})
        samokat = Store(found(s1, prod("s2", "Айран", 50), prod("s3", "Тан", 50)),
                        cards={"s1": dict(s1, composition_extra="Жирность: 4 %", nutrition={"kcal": 76}), "s2": SLOW})
        fakes = dict(lenta=lenta, samokat=samokat, lavka=Store(found()), perekrestok=Store(SLOW), ka5=Store(BOT),
                     vkusvill=Store(found(prod("v1", "Кефир", 80)), cards={"v1": "ВкусВилл: товар v1 не найден\nдругая строка"}))
        with stores(**fakes):
            got = grocery.compare_details("кефир", limit=2)
        for s in fakes.values():
            self.assertEqual(s.searched, [("кефир", {"tag": None, "sort": "popular", "page": 1, "limit": 20})])
        self.assertEqual({k: s.opened for k, s in fakes.items() if s.opened}, {"lenta": ["l1", "l2"], "samokat": ["s1", "s2"], "vkusvill": ["v1"]})
        self.assertEqual(got, "\n".join([
            "Сравнение состава «кефир» · порядок: цена за кг/л ↑ · товаров 3",
            "Яндекс Лавка: по «кефир» ничего не нашлось",
            "Перекрёсток: ошибка: " + str(SLOW)[:150],
            "Пятёрочка: ⚠️ проверка на бота",
            "Самокат s2: ошибка: " + str(SLOW)[:150],
            "ВкусВилл v1: ВкусВилл: товар v1 не найден",
            "",
            "1. Лента · Кефир Простоквашино 2,5% 930 мл · 99.9 ₽ (107 ₽/л) · рейтинг 4.8 (120) · lenta:l1",
            "   https://shop/l1",
            "   состав (2): 1) молоко нормализованное; 2) закваска",
            "   по составу: без сахара в составе",
            "   на 100 г: 53 ккал, Б 2.9, Ж 2.5, У 4, сахара ≤4 (сайт не пишет, не больше углеводов)",
            "",
            "2. Самокат · Ряженка 4% 500 г · 70 ₽ (140 ₽/кг) · samokat:s1",
            "   https://shop/s1",
            "   о составе: Жирность: 4 %",
            "   на 100 г: 76 ккал",
            "",
            "3. Лента · Кефир Лента 1% · None ₽ · нет в наличии · рейтинг 4.5 · lenta:l2",
            "   https://shop/l2",
            "   состав: сайт не указывает"]))

    def test_chosen_stores_not_strict(self):
        lenta = Store(found(prod("l9", "Ряженка", 50), prod("l2", "Кефир", 60)), cards={"l9": prod("l9", "Ряженка", 50)})
        with stores(lenta=lenta, ka5=Store(found())):
            got = grocery.compare_details("кефир", stores=["лента"], limit=1, strict=False, tag="без сахара")
        self.assertEqual(lenta.searched, [("кефир", {"tag": "без сахара", "sort": "popular", "page": 1, "limit": 20})])
        self.assertEqual(got, "Сравнение состава «кефир» · порядок: цена за кг/л ↑ · товаров 1\n\n"
                              "1. Лента · Ряженка · 50 ₽ · lenta:l9\n   https://shop/l9\n   состав: сайт не указывает")

    def test_given_items_by_share_of_an_ingredient(self):
        lenta = Store(cards={"c1": prod("c1", "Шоколад Особый", 120, size="100 г", composition="какао тертое, сахар. Какао-продукты не менее 55%."),
                             "c3": prod("c3", "Шоколад молочный", 90, size="90 г", composition="сахар, молоко сухое, какао-масло"),
                             "c4": prod("c4", "Шоколад 99", 200, composition_extra="% содержания какао: 99")})
        five = Store(cards={"c2": prod("c2", "Шоколад 72% какао", 150, rating=4.7, nutrition={"sugar": 28})})
        with stores(lenta=lenta, ka5=five):
            got = grocery.compare_details(items=["lenta:c1", "Пятёрочка: c2 ", "lenta:c3", "lenta:c4"], rank="%какао")
        self.assertEqual((lenta.opened, five.opened, lenta.searched), (["c1", "c3", "c4"], ["c2"], []))
        self.assertEqual(got, "\n".join([
            "Сравнение состава · порядок: доля «какао» ↓ · товаров 4",
            "",
            "1. Лента · Шоколад 99 · 200 ₽ · какао: 99% · lenta:c4",
            "   https://shop/c4",
            "   состав: сайт не указывает",
            "   о составе: % содержания какао: 99",
            "",
            "2. Пятёрочка · Шоколад 72% какао · 150 ₽ · какао: 72% · рейтинг 4.7 · 5ka:c2",
            "   https://shop/c2",
            "   на 100 г: сахара 28",
            "",
            "3. Лента · Шоколад Особый · 120 ₽ (1200 ₽/кг) · какао: 55% · lenta:c1",
            "   https://shop/c1",
            "   состав (2): 1) какао тертое; 2) сахар",
            "   в составе отмечено: Какао-продукты не менее 55%",
            "   по составу: сахар — 2-й из 2",
            "",
            "4. Лента · Шоколад молочный · 90 ₽ (1000 ₽/кг) · какао: % не указан · lenta:c3",
            "   https://shop/c3",
            "   состав (3): 1) сахар; 2) молоко сухое; 3) какао-масло",
            "   по составу: сахар — 1-й из 3"]))

    def test_rank_order(self):
        def card(id, price=100, size="", composition="", **nutrition):
            return prod(id, id, price, size=size, composition=composition, nutrition=nutrition)
        for rank, cards, order in (
                ("price", [card("a", 100, "1 кг"), card("b", 50, "1 кг"), card("c", 10), card("d", None, "1 кг")], "bacd"),
                ("sugar", [card("a", sugar=5), card("b", carbs=3), card("c"), card("d", sugar=1, carbs=9)], "dbac"),
                ("kcal", [card("a", kcal=300), card("b", kcal=100), card("c")], "bac"),
                ("fat", [card("a", fat=30), card("b", fat=1), card("c")], "bac"),
                ("protein", [card("a", protein=5), card("b", protein=20), card("c"), card("d", protein=0)], "badc"),
                ("ingredients", [card("a", composition="вода, соль, сахар"), card("b", composition="вода"), card("c")], "bac")):
            with self.subTest(rank=rank), stores(lenta=Store(cards={c["id"]: c for c in cards})):
                got = grocery.compare_details(items=[f"lenta:{c['id']}" for c in cards], rank=rank)
                self.assertEqual("".join(re.findall(r"^\d+\. Лента · (\S+)", got, re.M)), order)
                self.assertIn(f"порядок: {grocery.RANKS[rank]} ·", got)

    def test_unknown_rank_or_store(self):
        self.assertEqual(grocery.compare_details("кефир", rank="calories"),
                         "rank: одно из price, sugar, kcal, protein, fat, ingredients или «%ингредиент» (например %какао, %томат, %мясо)")
        with stores(lenta=Store()), self.assertRaises(ValueError):
            grocery.compare_details(items=["ozon:1"])


if __name__ == "__main__":
    unittest.main()
