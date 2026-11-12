"""Dr.Head: what the site's pages show (search cards, product card, its reviews) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_doctorhead"""
import unittest
from unittest.mock import MagicMock, patch

import doctorhead
import pace

ORIGIN = 1700000000123.5


def fake_tab(shown):
    """A tab whose js() answers performance.timeOrigin before the load and then the page's extraction."""
    tab = MagicMock()
    tab.js.side_effect = lambda expr, **kw: ORIGIN if expr == "performance.timeOrigin" else shown
    return tab


def run(fn, shown, *args, **kw):
    tab = fake_tab(shown)
    with patch.object(doctorhead, "tab_for", return_value=tab) as tab_for, patch.object(doctorhead, "log") as log:
        got = fn(*args, **kw)
    return got, tab, tab_for, log


CARD = {"id": "101", "href": "/product/naushniki_a1_black/", "name": "Наушники A1 Black", "price": "24990.0", "old": " 29 990 руб. ",
        "rating": " 4.5 ", "reviews": " 21 отзыв ", "status": " В наличии "}
CHEAP = {"id": "102", "href": "/product/kabel_b2/", "name": "Кабель B2", "price": "990", "old": "", "rating": "0.0",
         "reviews": "0 отзывов", "status": "На заказ"}
BARE = {"id": "103", "href": "/product/x/", "name": "X", "price": None, "old": None, "rating": None, "reviews": None, "status": None}
LIST = {"count": "1 374", "cards": [CARD, CHEAP, BARE]}
QUERY = "https://doctorhead.ru/search/?q=%D0%BD%D0%B0%D1%83%D1%88%D0%BD%D0%B8%D0%BA%D0%B8"
SEARCH_HEAD = ("ссылки относительно https://doctorhead.ru; цены и наличие — для города, выбранного на сайте\n"
               "#\tid\tкод\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tналичие\tссылка\n")


class DrHeadSearchTests(unittest.TestCase):
    def test_a_page_of_cards(self):
        got, tab, tab_for, _ = run(doctorhead.search, LIST, "наушники")
        self.assertEqual(got, f"Dr.Head · 1374 найдено · страница 1 (по 30) · {QUERY}\n" + SEARCH_HEAD +
                         "1\tnaushniki_a1_black\t101\t24990\t29990\tНаушники A1 Black\t4.5\t21\tВ наличии\t/product/naushniki_a1_black/\n"
                         "2\tkabel_b2\t102\t990\t\tКабель B2\t\t\tНа заказ\t/product/kabel_b2/\n"
                         "3\tx\t103\t\t\tX\t\t\t\t/product/x/")
        tab_for.assert_called_once_with("doctorhead.ru")
        self.assertEqual(tab.goto.call_args.args, (QUERY, "doctorhead"))
        self.assertEqual(tab.goto.call_args.kwargs["wait_js"], f"performance.timeOrigin !== {ORIGIN} && ({doctorhead.READY})")
        self.assertIn("frameDataInserted", doctorhead.READY)     # the composite's late blocks (stock) are in
        self.assertEqual(tab.js.call_args.args, (doctorhead.SEARCH_JS,))
        tab.close.assert_called_once()

    def test_sort_and_page_go_into_the_url(self):
        tab = run(doctorhead.search, LIST, "наушники", sort="price_desc", page=3)[1]
        self.assertEqual(tab.goto.call_args.args[0], QUERY + "&sort=price&order=desc&PAGEN_1=3")
        tab = run(doctorhead.search, LIST, "наушники", sort="discount")[1]
        self.assertEqual(tab.goto.call_args.args[0], QUERY + "&sort=discount_percent&order=desc")

    def test_limit(self):
        self.assertEqual(len(run(doctorhead.search, LIST, "наушники", limit=2)[0].splitlines()), 5)

    def test_nothing_found(self):
        got = run(doctorhead.search, {"count": "0", "cards": []}, "абв", page=2)[0]
        self.assertEqual(got, "Dr.Head · 0 найдено · страница 2 (по 30) · https://doctorhead.ru/search/?q=%D0%B0%D0%B1%D0%B2&PAGEN_1=2\n"
                         + SEARCH_HEAD + "(пусто)")

    def test_no_count_on_the_tab_is_none_found(self):
        self.assertTrue(run(doctorhead.search, {"count": "", "cards": []}, "абв")[0].startswith("Dr.Head · 0 найдено · "))

    def test_not_a_search_page(self):
        got, tab, _, log = run(doctorhead.search, {"count": None, "cards": []}, "наушники")
        self.assertEqual(got, doctorhead.BLOCKED)
        self.assertEqual(log.warning.call_args.args, ("doctorhead search %s: no search page", QUERY))
        tab.close.assert_called_once()
        self.assertEqual(run(doctorhead.search, None, "наушники")[0], doctorhead.BLOCKED)

    def test_wrong_arguments_take_no_slot(self):
        with patch.object(doctorhead, "tab_for") as tab_for:
            self.assertEqual(doctorhead.search("x", sort="cheap"),
                             "⚠️ sort: одно из relevance, price_asc, price_desc, rating, new, discount, discount_rub")
            self.assertEqual(doctorhead.search("x", price_min=100), doctorhead.NO_PRICE_FILTER)
            self.assertEqual(doctorhead.search("x", price_max=100), doctorhead.NO_PRICE_FILTER)
        tab_for.assert_not_called()

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = fake_tab(LIST)
        tab.goto.side_effect = pace.Refused("⏸")
        with patch.object(doctorhead, "tab_for", return_value=tab):
            self.assertRaises(pace.Refused, doctorhead.search, "наушники")
        tab.close.assert_called_once()


LD = {"@type": "Product", "name": "Наушники A1 Black", "sku": "101", "image": [f"https://doctorhead.ru/upload/{i}.jpg" for i in range(12)],
      "offers": {"price": 24990, "availability": "https://schema.org/InStock"},
      "aggregateRating": {"ratingValue": "4.5", "reviewCount": 21}}
DESCRIPTION = "Звук чистый. " + "Долго. " * 500
PAGE = {"path": "/product/naushniki_a1_black/", "title": "Наушники A1 Black — купить", "ld": LD, "code": " 101 ",
        "price": "24990", "old": " 29 990 руб. ", "sale": " -17% ",
        "storesHead": " В наличии в 2 магазинах ",
        "stores": [{"title": " Магазин 1 ", "status": "В наличии", "level": "Много"}, {"title": "Склад", "status": "Через 1 день", "level": ""}],
        "delivery": [[" Экспресс-доставка: ", "Через 2-3 часа"], ["Доставка курьером:", " Завтра "]],
        "crumbs": ["Главная", "Наушники", "Полноразмерные", "Наушники A1 Black"],
        "colors": [{"url": "/product/naushniki_a1_white/", "name": "белый", "on": False}, {"url": "/product/naushniki_a1_black/", "name": "черный", "on": True},
                   {"url": "/product/naushniki_a1_copper/", "name": "", "on": False}],         # a two-tone swatch has no name
        "specs": [[" Бренд ", "Пример"], ["Цвет", " "], ["Вес,\xa0г", " 250 "]],
        "features": ["лёгкие", "складные"], "description": DESCRIPTION}
ITEM_URL = "https://doctorhead.ru/product/naushniki_a1_black/"
CARD_TEXT = ("Наушники A1 Black\n" + ITEM_URL + "\nid: naushniki_a1_black · код товара: 101\n"
             "цена: 24990 ₽ (было 29990, −17%)\n"
             "наличие: В наличии в 2 магазинах — Магазин 1: В наличии, Много; Склад: Через 1 день\n"
             "получение: Экспресс-доставка: Через 2-3 часа; Доставка курьером: Завтра\n"
             "рейтинг 4.5, отзывов 21\n"
             "раздел: Наушники / Полноразмерные\n"
             "цвета: белый /product/naushniki_a1_white/; черный (эта карточка); /product/naushniki_a1_copper/\n"
             "характеристики: Бренд: Пример; Вес, г: 250\n"
             "фото (shop_images): " + " ".join(f"https://doctorhead.ru/upload/{i}.jpg" for i in range(10)) + "\n"
             "отзывы: doctorhead_reviews\n\n")


class DrHeadItemTests(unittest.TestCase):
    def test_full_card(self):
        got, tab, _, _ = run(doctorhead.item, PAGE, ITEM_URL + "#product-review")
        self.assertEqual(got, CARD_TEXT + ("Особенности: лёгкие; складные\n" + DESCRIPTION)[:2500])
        self.assertEqual(tab.goto.call_args.args, (ITEM_URL, "doctorhead"))
        self.assertEqual(tab.js.call_args.args, (doctorhead.ITEM_JS,))
        tab.close.assert_called_once()

    def test_full_description(self):
        got = run(doctorhead.item, PAGE, "naushniki_a1_black", full=True)[0]
        self.assertEqual(got, CARD_TEXT + "Особенности: лёгкие; складные\n" + DESCRIPTION)

    def test_bare_card(self):
        page = {"path": "/product/x/", "title": "X", "ld": {"name": "X", "offers": {"availability": "https://schema.org/PreOrder"}},
                "code": "", "price": None, "old": "", "sale": "", "storesHead": "", "stores": [], "delivery": [], "crumbs": [],
                "colors": [], "specs": [], "features": [], "description": ""}
        got, tab, _, _ = run(doctorhead.item, page, " /product/x/ ")
        self.assertEqual(tab.goto.call_args.args[0], "https://doctorhead.ru/product/x/")
        self.assertEqual(got, "X\nhttps://doctorhead.ru/product/x/\nid: x\nцена: — ₽\nналичие: на заказ\n"
                              "рейтинг —, отзывов 0\nотзывы: doctorhead_reviews\n\n")
        page["ld"] = {"name": "X"}
        self.assertIn("\nналичие: —\n", run(doctorhead.item, page, "x")[0])
        page["ld"] = {"name": "X", "offers": {"availability": "https://schema.org/Discontinued"}}
        self.assertIn("\nналичие: Discontinued\n", run(doctorhead.item, page, "x")[0])

    def test_wrong_id_takes_no_slot(self):
        with patch.object(doctorhead, "tab_for") as tab_for:
            for bad in ("наушники", "130319", "https://example.com/product/x/", "https://doctorhead.ru/catalog/x/"):
                self.assertEqual(doctorhead.item(bad), doctorhead.NO_ID, bad)
                self.assertEqual(doctorhead.reviews(bad), doctorhead.NO_ID, bad)
        tab_for.assert_not_called()

    def test_not_found_and_blocked(self):
        got, tab, _, log = run(doctorhead.item, {"path": "/product/x/", "title": "404 Страница не найдена", "ld": None}, "x")
        self.assertEqual(got, "⚠️ Dr.Head: такого товара нет (404): https://doctorhead.ru/product/x/")
        tab.close.assert_called_once()
        got, _, _, log = run(doctorhead.item, {"path": "/product/x/", "title": "Проверка", "ld": None}, "x")
        self.assertEqual(got, doctorhead.BLOCKED)
        self.assertEqual(log.warning.call_args.args, ("doctorhead %s: no product on the page", "https://doctorhead.ru/product/x/"))
        self.assertEqual(run(doctorhead.item, None, "x")[0], doctorhead.BLOCKED)

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = fake_tab(PAGE)
        tab.goto.side_effect = pace.Refused("⏸")
        with patch.object(doctorhead, "tab_for", return_value=tab):
            self.assertRaises(pace.Refused, doctorhead.item, "x")
        tab.close.assert_called_once()


REVIEWS = {"path": "/product/naushniki_a1_black/", "title": "Наушники", "ld": LD, "pages": ["1", "2", "3", " 6 "],
           "photos": ["/upload/r1.jpg", "/upload/r2.jpg", "/upload/r1.jpg"],     # the carousel repeats its slides
           "reviews": [{"author": " Покупатель ", "date": "26.03.2026", "stars": "5", "text": " Хорошие.\n\nЛёгкие. "},
                       {"author": "", "date": "", "stars": None, "text": ""}]}
REVIEWS_HEAD = ("Dr.Head · товар naushniki_a1_black: рейтинг 4.5, отзывов 21\n"
                "страница {page} из 6 (по 4), от новых к старым — другой сортировки у сайта нет; достоинства и недостатки "
                "сайт отдельно не ведёт\n")


class DrHeadReviewsTests(unittest.TestCase):
    def test_a_page_of_reviews(self):
        got, tab, _, _ = run(doctorhead.reviews, REVIEWS, ITEM_URL, page=2)
        self.assertEqual(got, REVIEWS_HEAD.format(page=2) +
                         "фото покупателей к товару (shop_images): https://doctorhead.ru/upload/r1.jpg https://doctorhead.ru/upload/r2.jpg\n"
                         "дата\t★\tавтор\tтекст\n"
                         "26.03.2026\t5\tПокупатель\tХорошие. Лёгкие.\n"
                         "\t\t\t")
        self.assertEqual(tab.goto.call_args.args, (ITEM_URL + "?PAGEN_PROMO=2", "doctorhead"))
        self.assertEqual(tab.js.call_args.args, (doctorhead.REVIEWS_JS,))
        tab.close.assert_called_once()

    def test_first_page_limit_and_media(self):
        got, tab, _, _ = run(doctorhead.reviews, REVIEWS, "naushniki_a1_black", sort="new", with_media=True, limit=1)
        self.assertEqual(tab.goto.call_args.args[0], ITEM_URL)
        self.assertEqual(got, REVIEWS_HEAD.format(page=1) +
                         "отзывы с фото сайт не отбирает: фото покупателей он показывает одним списком к товару\n"
                         "фото покупателей к товару (shop_images): https://doctorhead.ru/upload/r1.jpg https://doctorhead.ru/upload/r2.jpg\n"
                         "дата\t★\tавтор\tтекст\n26.03.2026\t5\tПокупатель\tХорошие. Лёгкие.")

    def test_no_reviews(self):
        page = {"path": "/product/x/", "title": "X", "ld": {"name": "X"}, "pages": [], "photos": [], "reviews": []}
        self.assertEqual(run(doctorhead.reviews, page, "x")[0],
                         "Dr.Head · товар x: рейтинг —, отзывов 0\n"
                         "страница 1 из 1 (по 4), от новых к старым — другой сортировки у сайта нет; достоинства и недостатки "
                         "сайт отдельно не ведёт\nдата\t★\tавтор\tтекст\n(отзывов нет)")

    def test_unknown_sort_takes_no_slot(self):
        with patch.object(doctorhead, "tab_for") as tab_for:
            self.assertEqual(doctorhead.reviews("x", sort="useful"),
                             "⚠️ Dr.Head показывает отзывы только от новых к старым: sort=new")
        tab_for.assert_not_called()

    def test_not_found_and_blocked(self):
        self.assertEqual(run(doctorhead.reviews, {"path": "/product/x/", "title": "404", "ld": None}, "x")[0],
                         "⚠️ Dr.Head: такого товара нет (404): https://doctorhead.ru/product/x/")
        self.assertEqual(run(doctorhead.reviews, None, "x")[0], doctorhead.BLOCKED)


if __name__ == "__main__":
    unittest.main()
