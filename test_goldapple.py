"""Золотое яблоко: the site's JSON (search, product card, delivery, reviews) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_goldapple"""
import unittest

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


if __name__ == "__main__":
    unittest.main()
