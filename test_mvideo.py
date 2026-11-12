"""М.Видео: the site's /bff JSON (search, product card, delivery, reviews) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_mvideo"""
import json
import unittest
from unittest.mock import MagicMock, patch

import pace
import mvideo

SEARCH = {"success": True, "body": {"total": 1234, "cursorId": "60", "items": [
    {"productId": "400000001", "name": "Наушники Альфа", "slug": "/products/400000001",
     "price": {"salePrice": 2499, "basePrice": 2999}, "rating": {"count": 70, "star": 4.8},
     "status": "available", "soldOut": False, "availabilityDate": "2026-11-12"},
    {"productId": "400000002", "name": "Наушники Бета", "slug": "/products/400000002", "adType": 1,
     "price": {"salePrice": 900, "basePrice": 900}, "rating": {"count": None, "star": None},
     "soldOut": False, "availabilityDate": "2026-11-13"},
    {"productId": "400000003", "name": "Наушники Гамма", "slug": "/products/400000003",
     "price": {"salePrice": 500, "basePrice": 700}, "soldOut": True}]}}
QUERY = "https://www.mvideo.ru/search?q=%D0%BD%D0%B0%D1%83%D1%88%D0%BD%D0%B8%D0%BA%D0%B8"
HEAD = ("ссылки относительно https://www.mvideo.ru; цены и наличие — для города из профиля на сайте\n"
        "#\tартикул\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tналичие\tреклама\tссылка\n")


class MvideoHelperTests(unittest.TestCase):
    def test_product_id_from_an_id_or_a_link(self):
        for s in ("400205947", 400205947, " 400205947 ", "https://www.mvideo.ru/products/400205947",
                  "https://www.mvideo.ru/products/naushniki-huawei-sinii-400205947?x=1", "/products/400205947/reviews",
                  "https://www.eldorado.ru/products/400205947"):
            self.assertEqual(mvideo.product_id(s), "400205947")
        self.assertIsNone(mvideo.product_id("наушники"))

    def test_photo_urls(self):
        self.assertEqual(mvideo.photo("product-medias/photos/1/a.jpg"), "https://img.mvideo.ru/product-medias/photos/1/a.jpg")
        self.assertEqual(mvideo.photo("/cs/rp/reviews/b.jpg"), "https://img.mvideo.ru/cs/rp/reviews/b.jpg")
        self.assertEqual(mvideo.photo("https://mcdn.mvideo.ru/c.jpg"), "https://mcdn.mvideo.ru/c.jpg")
        self.assertEqual(mvideo.photo("//img.mvideo.ru/d.jpg"), "https://img.mvideo.ru/d.jpg")

    def test_price_line(self):
        self.assertEqual(mvideo.price_line(2499, 2999), "цена: 2499 ₽ (было 2999, −17%)")
        self.assertEqual(mvideo.price_line(900, 900), "цена: 900 ₽")
        self.assertEqual(mvideo.price_line(None, None), "цена: —")

    def test_text_from_markup(self):
        self.assertEqual(mvideo.text("<p>Звук&nbsp;<b>чистый</b><br>и громкий</p> "), "Звук чистый и громкий")
        self.assertEqual(mvideo.text(None), "")


class MvideoSearchTests(unittest.TestCase):
    def search(self, answer, **kw):
        tab = MagicMock()
        with patch.object(mvideo, "tab_for", return_value=tab), patch.object(mvideo, "capture", return_value=answer) as capture, \
                patch.object(mvideo, "log"):
            return mvideo.search("наушники", **kw), capture, tab

    def test_whole_answer(self):
        got, capture, tab = self.search({"s": SEARCH})
        self.assertEqual(got, f"М.Видео · 1234 найдено · страница 1 (по 60) · реклама: 1 из 3 на странице · {QUERY}\n" + HEAD +
                         "1\t400000001\t2499\t2999\tНаушники Альфа\t4.8\t70\tс 2026-11-12\t\t/products/400000001\n"
                         "2\t400000002\t900\t\tНаушники Бета\t\t\tс 2026-11-13\tреклама\t/products/400000002\n"
                         "3\t400000003\t500\t700\tНаушники Гамма\t\t\tнет в наличии\t\t/products/400000003")
        self.assertEqual(capture.call_args.args, (tab, "mvideo", QUERY, {"s": ["re:/bff/products$"]}))
        self.assertIsNone(capture.call_args.kwargs.get("rewrite"))
        tab.close.assert_called_once()

    def test_sort_and_price_go_into_the_url(self):
        _, capture, _ = self.search({"s": SEARCH}, price_min=1000, price_max=5000, sort="price_asc")
        self.assertEqual(capture.call_args.args[2], QUERY + "&sort=price_asc&f_price=1000-5000")

    def test_page_two_rewrites_the_pages_own_request(self):
        got, capture, _ = self.search({"s": SEARCH}, price_max=5000, sort="price_desc", page=2, limit=1)
        glob, fn = capture.call_args.kwargs["rewrite"]
        self.assertEqual(glob, "*/bff/products")
        url, body = fn("https://www.mvideo.ru/bff/products")
        self.assertEqual(url, "https://www.mvideo.ru/bff/products")
        self.assertIn('"query": "наушники"', body)          # as the site sends it, not \u-escaped
        self.assertEqual(json.loads(body), {"limit": 60, "cursorId": "60", "enrich": True, "filters": [{"id": "price", "valuesId": ["-5000"]}],
                                            "sortBy": "price", "sortDirection": "desc", "isGettingBonusRoubles": True, "query": "наушники"})
        self.assertIn("страница 2 (по 60)", got)
        self.assertEqual(got.count("\n"), 3)                     # head, note, header, one row

    def test_default_sort_body(self):
        _, capture, _ = self.search({"s": SEARCH}, page=3)
        body = json.loads(capture.call_args.kwargs["rewrite"][1]("u")[1])
        self.assertEqual((body["cursorId"], body["sortBy"], body["sortDirection"], body["filters"]), ("120", "popularity", "desc", []))

    def test_wrong_sort_lists_the_allowed(self):
        got, capture, _ = self.search({}, sort="rating")
        self.assertEqual(got, "sort: одно из popular, price_asc, price_desc")
        capture.assert_not_called()

    def test_no_answer_is_blocked(self):
        got, _, tab = self.search({})
        self.assertEqual(got, mvideo.BLOCKED)
        tab.close.assert_called_once()

    def test_refusal_propagates_and_frees_the_tab(self):
        tab = MagicMock()
        with patch.object(mvideo, "tab_for", return_value=tab), patch.object(mvideo, "capture", side_effect=pace.Refused("⏸")):
            with self.assertRaises(pace.Refused):
                mvideo.search("наушники")
        tab.close.assert_called_once()


INFO = {"body": {"productDetails": {
    "productId": "400000001", "name": "Наушники Альфа синие", "brandName": "Альфа", "soldOut": False,
    "images": ["product-medias/photos/400000001/1.jpg", "product-medias/photos/400000001/2.jpg"],
    "description": "<p>Лёгкие&nbsp;наушники.<br>Чехол в комплекте.</p>",
    "properties": {"key": [{"name": "Тип", "properties": [{"name": "Тип наушников", "value": "вкладыши", "measure": None},
                                                          {"name": "Вес", "value": "60", "measure": "г"}]}]}},
    "productPrices": {"price": {"salePrice": 2499, "basePrice": 2999}}}}
REVIEWS = {"body": {"total": 3, "totalRating": 4.67, "photosCount": 1,
                    "ratingsStats": {"rating1": 0, "rating2": 0, "rating3": 0, "rating4": 1, "rating5": 2},
                    "reviews": [{"rating": 5, "createdAt": "2026-10-22T12:56:08+03:00", "authorName": "Покупатель А.",
                                 "advantages": "лёгкие", "disadvantages": "нет", "comment": "Хорошие\nнаушники", "likesCount": 4,
                                 "photoUrls": ["/cs/rp/reviews/1.jpg", "/cs/rp/reviews/2.webp"]},
                                {"rating": 4, "createdAt": "2025-01-20T00:00:00+03:00", "authorName": "Покупатель Б.",
                                 "comment": "Нормально", "likesCount": 0, "photoUrls": []},
                                {"rating": 3}]}}
HANDOVER = {"body": {"handoverBatchList": [
    {"productId": "400000009", "handoverOption": [{"handoverOption": "pickup", "availabilityDate": "2026-11-20", "minPrice": 0}]},
    {"productId": "400000001", "handoverOption": [{"handoverOption": "pickup", "availabilityDate": "2026-11-12", "minPrice": 0},
                                                  {"handoverOption": "interval-delivery", "availabilityDate": "2026-11-15", "minPrice": 499},
                                                  {"handoverOption": "new-kind", "availabilityDate": "2026-11-16"}]}]}}
SUMMARY = {"body": {"deliveryDate": "2026-11-12", "stockLocation": "MVIDEO_STORE", "hasExpressDelivery": True}}
STORES = {"body": {"stores": [{"availabilityDate": "2026-11-13"}, {"availabilityDate": "2026-11-12"}, {"availabilityDate": None}]}}
CARD = ("Наушники Альфа синие\nhttps://www.mvideo.ru/products/400000001\nартикул: 400000001\nцена: 2499 ₽ (было 2999, −17%)\n"
        "рейтинг: 4.67, отзывов 3\n"
        "получить можно с 2026-11-12, есть экспресс-доставка\n"
        "получение (для города из профиля на сайте): самовывоз из магазина — с 2026-11-12, бесплатно; курьер к интервалу — с 2026-11-15, от 499 ₽; "
        "new-kind — с 2026-11-16\n"
        "самовывоз: в 3 магазинах, раньше всего 2026-11-12\n"
        "характеристики: Тип наушников: вкладыши; Вес: 60 г\n"
        "фото (shop_images): https://img.mvideo.ru/product-medias/photos/400000001/1.jpg https://img.mvideo.ru/product-medias/photos/400000001/2.jpg\n"
        "отзывы: mvideo_reviews\n\nЛёгкие наушники. Чехол в комплекте.")


class MvideoItemTests(unittest.TestCase):
    def item(self, answer, arg="https://www.mvideo.ru/products/naushniki-alfa-400000001", **kw):
        tab = MagicMock()
        with patch.object(mvideo, "tab_for", return_value=tab), patch.object(mvideo, "capture", return_value=answer) as capture, \
                patch.object(mvideo, "log"):
            return mvideo.item(arg, **kw), capture, tab

    def test_whole_card(self):
        got, capture, tab = self.item({"p": INFO, "r": REVIEWS, "sum": SUMMARY, "h": HANDOVER, "st": STORES})
        self.assertEqual(got, CARD)
        self.assertEqual(capture.call_args.args, (tab, "mvideo", "https://www.mvideo.ru/products/400000001",
                                                  {"p": ["/bff/pdp/info", "400000001"], "r": ["/bff/reviews/list", "400000001"],
                                                   "sum": ["/bff/handover-options/v2/summary"], "st": ["/bff/product/stores"],
                                                   "h": ["/bff/handover-options/batch-list"]}))
        self.assertEqual(capture.call_args.kwargs, {"optional": ("h",)})   # asked only for goods with other sellers' offers
        tab.close.assert_called_once()

    def test_only_the_card_arrived(self):
        got, _, _ = self.item({"p": INFO}, arg="400000001")
        self.assertNotIn("рейтинг", got)
        self.assertNotIn("получ", got)
        got, _, _ = self.item({"p": INFO, "r": {"body": {"reviews": []}}, "sum": {"body": {"deliveryDate": "2026-11-14"}}})
        self.assertIn("\nрейтинг: —, отзывов 0\n", got)
        self.assertIn("\nполучить можно с 2026-11-14\n", got)
        self.assertIn("отзывы: mvideo_reviews", got)

    def test_sold_out_and_long_description(self):
        info = json.loads(json.dumps(INFO))
        info["body"]["productDetails"].update(soldOut=True, description="а" * 3000)
        got, _, _ = self.item({"p": info})
        self.assertIn("\nнет в наличии\n", got)
        self.assertTrue(got.endswith("\n" + "а" * 2500))
        got, _, _ = self.item({"p": info}, full=True)
        self.assertTrue(got.endswith("\n" + "а" * 3000))

    def test_bad_id_and_no_answer(self):
        got, capture, _ = self.item({}, arg="наушники")
        self.assertIn("нужен артикул", got)
        capture.assert_not_called()
        self.assertEqual(self.item({"r": REVIEWS})[0], mvideo.BLOCKED)


class MvideoReviewsTests(unittest.TestCase):
    def reviews(self, answer, **kw):
        tab = MagicMock()
        with patch.object(mvideo, "tab_for", return_value=tab), patch.object(mvideo, "capture", return_value=answer) as capture, \
                patch.object(mvideo, "log"):
            return mvideo.reviews("400000001", **kw), capture, tab

    def test_whole_answer(self):
        got, capture, tab = self.reviews({"r": REVIEWS})
        self.assertEqual(got, "М.Видео · артикул 400000001: рейтинг 4.67, отзывов 3 · 5★ 2 4★ 1 3★ 0 2★ 0 1★ 0\n"
                              "страница 1 (по 10), сортировка useful; фото с отзывов всего: 1\n"
                              "дата\t★\tполезно\tавтор\tтекст\tфото (shop_images)\n"
                              "2026-10-22\t5\t4\tПокупатель А.\t+ лёгкие | − нет | Хорошие наушники\t"
                              "https://img.mvideo.ru/cs/rp/reviews/1.jpg https://img.mvideo.ru/cs/rp/reviews/2.webp\n"
                              "2025-01-20\t4\t\tПокупатель Б.\tНормально\t\n"
                              "\t3\t\t\t\t")
        url, patterns = capture.call_args.args[2:]
        self.assertEqual((url, patterns), ("https://www.mvideo.ru/products/400000001/reviews", {"r": ["/bff/reviews/list", "400000001"]}))
        glob, fn = capture.call_args.kwargs["rewrite"]
        self.assertEqual(glob, "*/bff/reviews/list*")
        self.assertEqual(fn("https://www.mvideo.ru/bff/reviews/list?origin=mvideo&limit=10&offset=0&filter=&sort=useful%3Adesc&productId=400000001"),
                         "https://www.mvideo.ru/bff/reviews/list?origin=mvideo&limit=10&offset=0&filter=&sort=useful%3Adesc&productId=400000001")
        tab.close.assert_called_once()

    def test_sort_media_and_page_go_into_the_request(self):
        got, capture, _ = self.reviews({"r": REVIEWS}, sort="low", with_media=True, page=3, limit=1)
        self.assertEqual(capture.call_args.kwargs["rewrite"][1]("x"),
                         "https://www.mvideo.ru/bff/reviews/list?origin=mvideo&limit=10&offset=20&filter=photos_count%3Agt%3A0"
                         "&sort=rating%3Aasc&productId=400000001")
        self.assertIn("страница 3 (по 10), сортировка low, только с фото", got)
        self.assertEqual(got.count("\n"), 3)

    def test_wrong_input_and_no_answer(self):
        self.assertEqual(self.reviews({}, sort="best")[0], "sort: одно из useful, new, old, high, low")
        with patch.object(mvideo, "capture") as capture:
            self.assertIn("нужен артикул", mvideo.reviews("наушники"))
        capture.assert_not_called()
        self.assertEqual(self.reviews({})[0], mvideo.BLOCKED)
        self.assertEqual(self.reviews({"r": {"body": {"total": 0, "reviews": []}}})[0],
                         "М.Видео · артикул 400000001: рейтинг —, отзывов 0\n"
                         "страница 1 (по 10), сортировка useful; фото с отзывов всего: 0\n"
                         "дата\t★\tполезно\tавтор\tтекст\tфото (shop_images)\n(отзывов нет)")

    def test_stars_missing_from_the_stats_count_as_none(self):
        self.assertEqual(mvideo.reviews_head("М.Видео", "1", 5, 2, {"rating5": 2}),
                         "М.Видео · артикул 1: рейтинг 5, отзывов 2 · 5★ 2 4★ 0 3★ 0 2★ 0 1★ 0\n")


if __name__ == "__main__":
    unittest.main()
