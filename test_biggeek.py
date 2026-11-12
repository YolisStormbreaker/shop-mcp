"""Biggeek: the page's Diginetica search answer and the card's own JSON -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_biggeek"""
import unittest
from unittest.mock import MagicMock, patch

import biggeek
import digi
import pace

CASE = {"id": "100000011", "available": True, "name": "Чехол A для наушников", "brand": "Brand", "price": "1990.0", "oldPrice": "2490.0",
        "link_url": "/products/chekhol-a"}
PHONE = {"id": "100000012", "available": False, "name": "Смартфон X 256 ГБ", "price": "90000.0", "link_url": "/products/smartfon-x"}
ANSWER = {"totalHits": 51, "correction": "чехол", "zeroQueries": False, "products": [CASE, PHONE]}
URL = "https://biggeek.ru/?digiSearch=true&term=%D1%87%D0%B5%D1%85%D0%BE%D0%BB&params=%7Csort%3DDEFAULT"


class BiggeekSearchTests(unittest.TestCase):
    def search(self, answer, **kw):
        tab = MagicMock()
        tab.visible.return_value = True
        with patch.object(digi, "tab_for", return_value=tab) as tab_for, \
                patch.object(digi, "capture", return_value={"s": answer}) as capture:
            return biggeek.search("чехол", **kw), capture, tab, tab_for

    def test_table(self):
        got, capture, tab, tab_for = self.search(ANSWER)
        self.assertEqual(got, f"Biggeek · 51 найдено · страница 1 (по 20) · {URL}\n"
                              "ссылки относительно https://biggeek.ru; цены и наличие — как в поиске сайта, без привязки к городу\n"
                              "#\tid\tцена ₽\tбез скидки\tназвание\tналичие\tссылка\n"
                              "1\t100000011\t1990\t2490\tЧехол A для наушников\t\t/products/chekhol-a\n"
                              "2\t100000012\t90000\t\tСмартфон X 256 ГБ\tнет в наличии\t/products/smartfon-x")
        tab_for.assert_called_once_with("biggeek.ru")
        self.assertEqual(capture.call_args.args, (tab, "biggeek", URL, {"s": ["sort.diginetica.net/search"]}))
        tab.close.assert_called_once()

    def test_sort_and_price_go_into_the_url(self):
        url = self.search(ANSWER, sort="price_desc", price_min=1000, price_max=5000)[1].call_args.args[2]
        self.assertTrue(url.endswith("&params=%7Csort%3DPRICE_DESC%7Cfilter%3Dprice%3A1000%3B5000"), url)


DESCRIPTION = "Абзац  первый.\nАбзац второй. " + "Долго. " * 500
PICKER = {"selectedVariantId": 901, "price": 90000, "comparePrice": 100000, "characteristics": [{"name": "SIM-карта", "values": [
    {"label": "eSIM", "price": 90000, "isSelected": True, "isAvailable": True},
    {"label": "nano-SIM и eSIM", "price": 95000, "isSelected": False, "isAvailable": False}]}]}
SPECS = {"Общие характеристики": [{"name": "Артикул", "value": "500"}, {"name": "Модель", "value": "X"}],
         "Экран": [{"name": "Экран", "value": "6.3\""}] + [{"name": f"Свойство {i}", "value": str(i)} for i in range(25)]}
CARD = {"path": "/products/smartfon-x", "h1": "Смартфон X 256 ГБ (Серебристый)", "subtitle": "Без предустановки RuStore",
        "photos": [f"//images.example/{i}.jpg" for i in range(12)], "overview": DESCRIPTION,
        "ld": {"@type": "Product", "name": "X", "description": "Коротко", "image": "https://img/ld.jpg",
               "offers": {"price": 90000, "availability": "https://schema.org/InStock"}},
        "props": {"productId": 500, "featureGroups": SPECS, "variantsFeatureGroups": {"901": {"Питание": [{"name": "Аккумулятор", "value": "4000 мАч"}]}},
                  "variantCharacteristicPicker": PICKER, "equipment": ["Смартфон", "Кабель"]}}
CARD_URL = "https://biggeek.ru/products/smartfon-x"


class BiggeekItemTests(unittest.TestCase):
    def item(self, card, url=CARD_URL + "?utm=1#tab", **kw):
        tab = MagicMock()
        tab.js.return_value = card
        with patch.object(biggeek, "tab_for", return_value=tab), patch.object(biggeek, "log") as log:
            return biggeek.item(url, **kw), tab, log

    def test_full_card(self):
        got, tab, _ = self.item(CARD)
        specs = ["Модель: X", "Экран: 6.3\""] + [f"Свойство {i}: {i}" for i in range(18)]
        self.assertEqual(got, "Смартфон X 256 ГБ (Серебристый)\n" + CARD_URL + "\nартикул: 500, вариант 901\n"
                              "цена: 90000 ₽ (было 100000, −10%)\n"
                              "наличие: есть\n"
                              "получение: доставку и самовывоз карточка не показывает\n"
                              "примечание: Без предустановки RuStore\n"
                              "SIM-карта: eSIM — 90000 ₽ (этот); nano-SIM и eSIM — 95000 ₽, нет в наличии\n"
                              "характеристики: " + "; ".join(specs) + " … ещё 8 (full=True)\n"
                              "комплектация: Смартфон, Кабель\n"
                              "фото (shop_images): " + " ".join(f"https://images.example/{i}.jpg" for i in range(10)) + "\n"
                              "отзывы: на Biggeek их нет (biggeek_reviews)\n\n" + biggeek._text(DESCRIPTION)[:2500])
        self.assertEqual(tab.goto.call_args.args, (CARD_URL, "biggeek"))
        self.assertEqual(tab.goto.call_args.kwargs, {"wait_js": "document.getElementById('product-properties-json')"})
        tab.close.assert_called_once()

    def test_full(self):
        got = self.item(CARD, full=True)[0]
        self.assertTrue(got.endswith("\n\n" + biggeek._text(DESCRIPTION)))
        self.assertIn("; Свойство 24: 24; Аккумулятор: 4000 мАч\n", got)

    def test_bare_card_falls_back_to_its_json_ld(self):
        card = {"path": "/products/kabel", "ld": {"name": "Кабель", "description": "Длинный <b>кабель</b>", "image": "https://img/k.jpg",
                                                   "offers": {"price": 990, "availability": "https://schema.org/OutOfStock"}},
                "props": {"productId": 7, "featureGroups": [], "variantsFeatureGroups": [], "variantCharacteristicPicker": None}}
        got = self.item(card, url="/products/kabel")[0]
        self.assertEqual(got, "Кабель\nhttps://biggeek.ru/products/kabel\nартикул: 7\nцена: 990 ₽\nналичие: нет в наличии\n"
                              "получение: доставку и самовывоз карточка не показывает\nфото (shop_images): https://img/k.jpg\n"
                              "отзывы: на Biggeek их нет (biggeek_reviews)\n\nДлинный кабель")

    def test_old_price_equal_to_the_price_is_dropped(self):
        card = {**CARD, "props": {**CARD["props"], "variantCharacteristicPicker": {**PICKER, "comparePrice": 90000}}}
        self.assertIn("\nцена: 90000 ₽\n", self.item(card)[0])

    def test_specs_cut_only_past_twenty(self):
        for n, tail in ((20, "Свойство 19: 19\n"), (21, "Свойство 19: 19 … ещё 1 (full=True)\n")):
            props = {**CARD["props"], "featureGroups": {"Все": [{"name": f"Свойство {i}", "value": str(i)} for i in range(n)]},
                     "variantsFeatureGroups": {}}
            self.assertIn("; " + tail, self.item({**CARD, "props": props})[0])

    def test_preorder_and_unknown_stock(self):
        for availability, said in (("https://schema.org/PreOrder", "предзаказ"), (None, "—")):
            card = {**CARD, "ld": {"offers": {"availability": availability}}}
            self.assertIn(f"\nналичие: {said}\n", self.item(card)[0])

    def test_blocked_or_another_card(self):
        for card in (None, {**CARD, "path": "/products/other"}):
            got, tab, log = self.item(card)
            self.assertEqual(got, "⚠️ Biggeek не показал карточку https://biggeek.ru/products/smartfon-x: "
                                  "нет такого товара или проверка на бота (shop-chrome show, открыть сайт, повторить).")
            self.assertEqual(log.warning.call_args.args, ("biggeek item %s: no product card", CARD_URL))
            tab.close.assert_called_once()

    def test_not_a_link(self):
        for s in ("100069294", "iphone 17", "https://biggeek.ru/catalog/apple"):
            self.assertEqual(biggeek.item(s), "нужна ссылка на товар Biggeek (biggeek.ru/products/…) из biggeek_search")

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = MagicMock()
        tab.goto.side_effect = pace.Refused("⏸")
        with patch.object(biggeek, "tab_for", return_value=tab):
            self.assertRaises(pace.Refused, biggeek.item, CARD_URL)
        tab.close.assert_called_once()


class BiggeekReviewsTests(unittest.TestCase):
    def test_the_site_has_none(self):
        with patch.object(biggeek, "tab_for") as tab_for:
            got = biggeek.reviews(CARD_URL, sort="new", with_media=True, page=2)
        self.assertEqual(got, "На Biggeek нет отзывов покупателей о товарах: на карточке только «Вопросы и ответы». "
                              "Отзывы о модели — на маркетплейсах (ozon_reviews, wb_reviews, ym_reviews).")
        tab_for.assert_not_called()


class BiggeekHelperTests(unittest.TestCase):
    def test_slug(self):
        for s, slug in (("https://biggeek.ru/products/smartfon-x?x=1", "smartfon-x"), ("www.biggeek.ru/products/a-b/", "a-b"),
                        ("/products/kabel", "kabel"), (" /products/smartfon-x ", "smartfon-x")):
            self.assertEqual(biggeek._slug(s), slug)
        for s in ("100069294", "iphone 17", "airpods", "", "https://pitergsm.ru/products/x", "https://biggeek.ru/catalog/apple"):
            self.assertIsNone(biggeek._slug(s))


if __name__ == "__main__":
    unittest.main()
