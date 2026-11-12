"""Эльдорадо: the page route's loader data (search, product card, reviews) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_eldorado"""
import unittest
from unittest.mock import MagicMock, patch

import pace
import eldorado

SEARCH = {"total": 777, "items": [
    {"skuId": 400000001, "title": "Наушники Альфа", "customerPrice": 4136, "discountPercent": 6, "priceOldLabel": "4 399 ₽",
     "rating": 4.5, "reviewsCount": 12, "minEtaLabel": "15 ноября"},
    {"skuId": 400000002, "title": "Наушники Бета", "customerPrice": 900, "discountPercent": 0, "priceOldLabel": "", "rating": 0,
     "reviewsCount": 0}]}
QUERY = "https://www.eldorado.ru/search?q=%D0%BD%D0%B0%D1%83%D1%88%D0%BD%D0%B8%D0%BA%D0%B8"
ROUTE = "window.__reactRouterContext?.state?.loaderData?.[\"ui/pages/Search/Search\"]"


def run(fn, answer, *args, **kw):
    tab = MagicMock()
    tab.js.side_effect = [None, answer]
    with patch.object(eldorado, "tab_for", return_value=tab), patch.object(eldorado, "log"):
        return fn(*args, **kw), tab


class EldoradoSearchTests(unittest.TestCase):
    def test_whole_answer(self):
        got, tab = run(eldorado.search, SEARCH, "наушники")
        self.assertEqual(got, f"Эльдорадо · 777 найдено · страница 1 (по 60) · {QUERY}\n"
                              "ссылки относительно https://www.eldorado.ru; цены и сроки доставки — для города из профиля на сайте\n"
                              "#\tартикул\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tдоставка\tссылка\n"
                              "1\t400000001\t4136\t4399\tНаушники Альфа\t4.5\t12\t15 ноября\t/products/400000001\n"
                              "2\t400000002\t900\t\tНаушники Бета\t\t\t\t/products/400000002")
        self.assertEqual(tab.goto.call_args.args, (QUERY, "eldorado"))
        self.assertIn("!window.__shopStale", tab.goto.call_args.kwargs["wait_js"])
        self.assertIn(ROUTE, tab.js.call_args_list[1].args[0])      # only the page's own route, never root (the user's profile)
        self.assertNotIn("root", tab.js.call_args_list[1].args[0])
        tab.close.assert_called_once()

    def test_sort_price_and_limit(self):
        got, tab = run(eldorado.search, SEARCH, "наушники", price_min=1000, price_max=5000, sort="price_desc", limit=1)
        self.assertEqual(tab.goto.call_args.args[0], QUERY + "&sort=price_desc&price_min=1000&price_max=5000")
        self.assertEqual(got.count("\n"), 3)

    def test_what_the_site_does_not_do(self):
        with patch.object(eldorado, "tab_for") as tab_for:
            self.assertEqual(eldorado.search("наушники", sort="rating"), "sort: одно из popular, price_asc, price_desc")
            self.assertIn("только страница 1", eldorado.search("наушники", page=2))
            self.assertIn("только страница 1", eldorado.search("наушники", page=0))
        tab_for.assert_not_called()

    def test_no_data_is_blocked(self):
        self.assertEqual(run(eldorado.search, None, "наушники")[0], eldorado.BLOCKED)

    def test_refusal_propagates_and_frees_the_tab(self):
        tab = MagicMock()
        tab.goto.side_effect = pace.Refused("⏸")
        with patch.object(eldorado, "tab_for", return_value=tab):
            with self.assertRaises(pace.Refused):
                eldorado.search("наушники")
        tab.close.assert_called_once()


CARD_DATA = {"product": {"name": "Наушники Альфа синие", "sku_id": 400000001, "customer_price": 2499, "base_price": 2999,
                         "rating": "4.78", "reviews_count": 70, "description": "<p>Лёгкие&nbsp;наушники.</p>",
                         "properties": [{"name": "Вес", "properties": [{"name": "Вес", "value": "60"}]},
                                        {"name": "Цвет", "properties": [{"name": "Цвет", "value": "голубой"}]}]},
             "delivery": [{"etaLabel": "20 ноября", "methodId": "COURIER"}, {"etaLabel": "завтра", "methodId": "DRONE"}],
             "summary": {"isOutOfStock": False, "leftoversQuantity": 3}, "seller": "М.Видео",
             "gallery": ["https://mcdn.mvideo.ru/ri/1.jpg", "https://mcdn.mvideo.ru/ri/2.jpg"]}


class EldoradoItemTests(unittest.TestCase):
    def test_whole_card(self):
        got, tab = run(eldorado.item, CARD_DATA, "https://www.eldorado.ru/products/400000001")
        self.assertEqual(got, "Наушники Альфа синие\nhttps://www.eldorado.ru/products/400000001\nартикул: 400000001\n"
                              "цена: 2499 ₽ (было 2999, −17%)\nв наличии: 3 шт.\nрейтинг: 4.78, отзывов 70\n"
                              "доставка (для города из профиля на сайте): курьер — 20 ноября; DRONE — завтра\nпродавец: М.Видео\n"
                              "характеристики: Вес: 60; Цвет: голубой\n"
                              "фото (shop_images): https://mcdn.mvideo.ru/ri/1.jpg https://mcdn.mvideo.ru/ri/2.jpg\n"
                              "отзывы: eldorado_reviews\n\nЛёгкие наушники.")
        self.assertEqual(tab.goto.call_args.args, ("https://www.eldorado.ru/products/400000001", "eldorado"))
        self.assertIn('"ui/pages/ProductPage/ProductPage"', tab.js.call_args_list[1].args[0])

    def test_out_of_stock_and_bare_data(self):
        got, _ = run(eldorado.item, {"product": {"name": "Х", "description": "б" * 3000}, "summary": {"isOutOfStock": True}}, "400000001")
        self.assertEqual(got, "Х\nhttps://www.eldorado.ru/products/400000001\nартикул: 400000001\nцена: —\nнет в наличии\n"
                              "отзывы: eldorado_reviews\n\n" + "б" * 2500)

    def test_bad_id_and_no_data(self):
        with patch.object(eldorado, "tab_for") as tab_for:
            self.assertIn("нужен артикул", eldorado.item("наушники"))
        tab_for.assert_not_called()
        self.assertEqual(run(eldorado.item, None, "400000001")[0], eldorado.BLOCKED)


REVIEWS = {"rating": 4.78, "chunk": {"total": 3, "photosCount": 2, "nextCursor": "18",
                                     "ratingsStats": {"rating1": 1, "rating2": 0, "rating3": 0, "rating4": 0, "rating5": 2},
                                     "items": [{"rating": 5, "createdAt": "2026-10-22T12:56:08+03:00", "authorName": "Покупатель А.",
                                                "advantages": "звук", "comment": "Отлично", "likesCount": 2,
                                                "photoUrls": ["https://mcdn.mvideo.ru/cs/rp/reviews/1.webp"]},
                                               {"rating": 1, "createdAt": "2026-01-02T10:00:00+03:00", "authorName": "",
                                                "disadvantages": "сломались", "photoUrls": []}]}}


class EldoradoReviewsTests(unittest.TestCase):
    def test_whole_answer(self):
        got, tab = run(eldorado.reviews, REVIEWS, "https://www.eldorado.ru/products/400000001")
        self.assertEqual(got, "Эльдорадо · артикул 400000001: рейтинг 4.78, отзывов 3 · 5★ 2 4★ 0 3★ 0 2★ 0 1★ 1\n"
                              "страница 1 (по 18), сортировка useful; фото с отзывов всего: 2\n"
                              "дата\t★\tполезно\tавтор\tтекст\tфото (shop_images)\n"
                              "2026-10-22\t5\t2\tПокупатель А.\t+ звук | Отлично\thttps://mcdn.mvideo.ru/cs/rp/reviews/1.webp\n"
                              "2026-01-02\t1\t\t\t− сломались\t")
        self.assertEqual(tab.goto.call_args.args, ("https://www.eldorado.ru/products/400000001/reviews", "eldorado"))
        self.assertIn('"ui/pages/ProductReviewsPage/ProductReviewsPage"', tab.js.call_args_list[1].args[0])

    def test_sort_and_photos_go_into_the_url(self):
        got, tab = run(eldorado.reviews, REVIEWS, "400000001", sort="low", with_media=True, limit=1)
        self.assertEqual(tab.goto.call_args.args[0], "https://www.eldorado.ru/products/400000001/reviews?sort=rating-asc&photos=1")
        self.assertIn("сортировка low, только с фото", got)
        self.assertEqual(got.count("\n"), 3)

    def test_what_the_site_does_not_do(self):
        with patch.object(eldorado, "tab_for") as tab_for:
            self.assertEqual(eldorado.reviews("400000001", sort="best"), "sort: одно из useful, new, old, high, low")
            self.assertIn("только первые 18", eldorado.reviews("400000001", page=2))
            self.assertIn("только первые 18", eldorado.reviews("400000001", page=0))
            self.assertIn("нужен артикул", eldorado.reviews("отзывы"))
        tab_for.assert_not_called()
        self.assertEqual(run(eldorado.reviews, None, "400000001")[0], eldorado.BLOCKED)

    def test_bare_reviews_page(self):
        got, _ = run(eldorado.reviews, {"chunk": {"items": []}}, "400000001")
        self.assertEqual(got, "Эльдорадо · артикул 400000001: рейтинг —, отзывов 0\n"
                              "страница 1 (по 18), сортировка useful; фото с отзывов всего: 0\n"
                              "дата\t★\tполезно\tавтор\tтекст\tфото (shop_images)\n(отзывов нет)")


if __name__ == "__main__":
    unittest.main()
