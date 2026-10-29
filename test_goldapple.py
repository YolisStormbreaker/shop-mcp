"""Золотое яблоко: the site's JSON (search, product card, delivery, reviews) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_goldapple"""
import unittest
from unittest.mock import MagicMock, patch

import goldapple

DELIVERY = {"options": [
    {"name": "экспресс-доставка", "dateInfo": "сегодня за 3 часа", "cost": {"value": {"amount": 99}}},
    {"name": "самовывоз из магазина", "date": "2026-10-30T10:00:00+03:00", "cost": {"value": {"amount": 0}},
     "costSpecial": "при заказе от 1000 ₽ — бесплатно"},
    {"name": "курьер", "cost": {"value": None}}]}


class GoldAppleHelperTests(unittest.TestCase):
    def test_delivery_options(self):
        self.assertEqual(goldapple._delivery(DELIVERY), ["экспресс-доставка — сегодня за 3 часа, 99 ₽",
                                                         "самовывоз из магазина — 2026-10-30, бесплатно (при заказе от 1000 ₽ — бесплатно)",
                                                         "курьер — "])
        self.assertEqual(goldapple._delivery(None), [])

    def test_picture_from_the_template(self):
        self.assertEqual(goldapple._img({"url": "https://cdn/p/1/${screen}.${format}", "format": ["webp", "jpg"]}), "https://cdn/p/1/fullhd.jpg")
        self.assertEqual(goldapple._img({"url": "https://cdn/p/1/${screen}.${format}", "format": ["avif"]}, "mobile"), "https://cdn/p/1/mobile.avif")
        self.assertEqual(goldapple._img({}), "")

    def test_cart_items(self):
        self.assertEqual(goldapple._items({"data": {"rawCart": {"items": [{"productSku": "1"}]}}}), [{"productSku": "1"}])
        self.assertEqual(goldapple._items({"data": None}), [])
        self.assertEqual(goldapple._items(None), [])

    def test_rub(self):
        self.assertEqual(goldapple._rub({"actual": {"amount": 453}}, "actual"), 453)
        self.assertIsNone(goldapple._rub({"old": None}, "old"))
        self.assertIsNone(goldapple._rub(None, "actual"))

    def test_sku_from_an_id_or_a_link(self):
        for s in ("https://goldapple.ru/19000163536-cushion", " /19000163536-cushion ", "19000163536", 19000163536):
            self.assertEqual(goldapple._sku(s), "19000163536")
        self.assertIsNone(goldapple._sku("кушон"))

    def test_text_from_markup(self):
        self.assertEqual(goldapple._text("<p>Крем&nbsp;для <b>рук</b></p>\n  "), "Крем для рук")
        self.assertEqual(goldapple._text(None), "")


SEARCH = {"data": {"count": 2000, "products": [
    {"itemId": "19000163536", "price": {"actual": {"amount": 2150}, "old": {"amount": 3070}}, "brand": "Brand A", "name": "Кушон",
     "productType": "тональный кушон", "attributes": {"units": {"currentUnitValue": "7.5", "name": "г", "count": 9}},
     "reviews": {"rating": 4.6, "reviewsCount": 7274}, "inStock": True, "url": "/19000163536-cushion"},
    {"itemId": "19000000001", "price": {"actual": {"amount": 500}, "old": {"amount": 500}}, "brand": "Brand B", "name": "Шампунь",
     "productType": "шампунь", "attributes": {"units": {"currentUnitValue": "250", "name": "мл", "count": 1}}, "reviews": {"rating": 0},
     "inStock": False, "url": "/19000000001-shampoo"},
    {"itemId": "19000000002"}]}}
SEARCH_HEAD = ("ссылки относительно https://goldapple.ru; цены и наличие — для города из профиля\n"
               "#\tартикул\tцена ₽\tбез скидки\tбренд\tназвание\tтип\tобъём\tрейтинг\tотзывов\tналичие\tссылка\n")
QUERY = "https://goldapple.ru/catalogsearch/result?q=%D1%88%D0%B0%D0%BC%D0%BF%D1%83%D0%BD%D1%8C"


class GoldAppleSearchTests(unittest.TestCase):
    def search(self, answer, **kw):
        tab = MagicMock()
        with patch.object(goldapple, "tab_for", return_value=tab), patch.object(goldapple, "capture", return_value=answer) as capture, \
                patch.object(goldapple, "log") as log:
            return goldapple.search("шампунь", **kw), capture, tab, log

    def test_whole_answer(self):
        got, capture, tab, _ = self.search({"s": SEARCH})
        self.assertEqual(got, f"Золотое яблоко · 2000+ найдено · страница 1 (по 24) · {QUERY}\n" + SEARCH_HEAD +
                         "1\t19000163536\t2150\t3070\tBrand A\tКушон\tтональный кушон\t7.5 г (вариантов: 9)\t4.6\t7274\t\t/19000163536-cushion\n"
                         "2\t19000000001\t500\t\tBrand B\tШампунь\tшампунь\t250 мл\t\t\tнет в наличии\t/19000000001-shampoo\n"
                         "3\t19000000002\tNone\t\t\t\t\t\t\t\tнет в наличии\t")
        self.assertEqual(capture.call_args.args, (tab, "goldapple", QUERY, {"s": ["/front/api/catalog/search-products"]}))
        tab.close.assert_called_once()

    def test_sort_price_and_page_go_into_the_url(self):
        got, capture, _, _ = self.search({"s": {"data": {"products": []}}}, price_max=1000, sort="priceAsc", page=3)
        url = QUERY + "&sort=priceAsc&calculatedprices=0-1000&p=3"
        self.assertEqual(capture.call_args.args[2], url)
        self.assertEqual(got, f"Золотое яблоко · 0 найдено · страница 3 (по 24) · {url}\n" + SEARCH_HEAD + "(пусто)")
        self.assertTrue(self.search({"s": {}}, price_min=300)[1].call_args.args[2].endswith("&calculatedprices=300-10000000"))

    def test_count_of_the_rows_when_the_site_gives_none(self):
        got, _, _, _ = self.search({"s": {"data": {"products": SEARCH["data"]["products"]}}}, limit=2)
        self.assertTrue(got.startswith("Золотое яблоко · 2 найдено"))
        self.assertEqual(len(got.splitlines()), 5)

    def test_unknown_sort(self):
        self.assertEqual(goldapple.search("шампунь", sort="cheap"),
                         "sort: одно из relevance, priceAsc, priceDesc, discountAmount, byRating, byNewest")

    def test_blocked(self):
        got, _, tab, log = self.search({})
        self.assertEqual(got, goldapple.BLOCKED)
        self.assertEqual(log.warning.call_args.args, ("goldapple search %s: no search-products response", QUERY))
        tab.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
