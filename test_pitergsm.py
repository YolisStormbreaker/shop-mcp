"""PiterGSM: the page's Diginetica search answer and the card read off its page -> the tools' text. The search edge
cases of digi.py (shared with Biggeek) are here too.  No requests to shops.
Run: .venv/bin/python -B -m unittest -v test_pitergsm"""
import unittest
from unittest.mock import MagicMock, patch

import digi
import pace
import pitergsm

PODS = {"id": "120001", "available": True, "name": "Наушники Z Pro", "price": "21990.0", "link_url": "/catalog/audio/naushniki/z-pro/120001/"}
FREE = {"id": "120002", "available": True, "name": "Подарок", "price": "0.0", "oldPrice": None, "link_url": "/catalog/x/120002/"}
ANSWER = {"totalHits": 25, "correction": "наушники z", "zeroQueries": False, "products": [PODS, FREE]}
URL = "https://pitergsm.ru/?digiSearch=true&term=%D0%BD%D0%B0%D1%83%D1%88%D0%BD%D0%B8%D0%BA%D0%B8+z&params=%7Csort%3DDEFAULT"
HEAD = ("ссылки относительно https://pitergsm.ru; цены и наличие — как в поиске сайта, без привязки к городу\n"
        "#\tid\tцена ₽\tбез скидки\tназвание\tналичие\tссылка\n")


class PitergsmSearchTests(unittest.TestCase):
    def search(self, answer, visible=True, **kw):
        tab = MagicMock()
        tab.visible.return_value = visible
        got = {} if answer is None else {"s": answer}
        with patch.object(digi, "tab_for", return_value=tab) as tab_for, patch.object(digi, "capture", return_value=got) as capture, \
                patch.object(digi, "log") as log:
            return pitergsm.search("наушники z", **kw), capture, tab, tab_for, log

    def test_table(self):
        got, capture, tab, tab_for, _ = self.search(ANSWER)
        self.assertEqual(got, f"PiterGSM · 25 найдено · страница 1 (по 20) · {URL}\n" + HEAD +
                         "1\t120001\t21990\t\tНаушники Z Pro\t\t/catalog/audio/naushniki/z-pro/120001/\n"
                         "2\t120002\t\t\tПодарок\t\t/catalog/x/120002/")
        tab_for.assert_called_once_with("pitergsm.ru")
        self.assertEqual(capture.call_args.args[:3], (tab, "pitergsm", URL))
        tab.close.assert_called_once()

    def test_price_filter_from_one_side(self):
        self.assertTrue(self.search(ANSWER, price_min=500, sort="price_asc")[1].call_args.args[2]
                        .endswith("%7Csort%3DPRICE_ASC%7Cfilter%3Dprice%3A500%3B10000000"))
        self.assertTrue(self.search(ANSWER, price_max=900)[1].call_args.args[2].endswith("%7Csort%3DDEFAULT%7Cfilter%3Dprice%3A0%3B900"))

    def test_limit_and_empty(self):
        self.assertEqual(len(self.search(ANSWER, limit=1)[0].splitlines()), 4)
        got = self.search({"totalHits": 0, "products": []})[0]
        self.assertEqual(got, f"PiterGSM · 0 найдено · страница 1 (по 20) · {URL}\n" + HEAD + "(пусто)")

    def test_what_the_site_did_with_the_query(self):
        got = self.search({**ANSWER, "correction": "наушники"})[0].splitlines()[1]
        self.assertEqual(got, "сайт искал «наушники»")
        got = self.search({**ANSWER, "zeroQueries": True, "correction": ""})[0].splitlines()[1]
        self.assertEqual(got, "точных совпадений нет — сайт показал похожие товары")
        self.assertNotIn("сайт искал", self.search({**ANSWER, "correction": "Наушники Z"})[0])   # the same query, other case

    def test_hidden_tab(self):
        got, capture, tab, _, _ = self.search(ANSWER, visible=False)
        self.assertEqual(got, "⚠️ Поиск PiterGSM работает только в видимой вкладке: сайт запускает его, когда вкладка на экране. "
                              "Попроси пользователя выполнить shop-chrome show (вкладку инструмент выведет вперёд сам) и повтори; "
                              "карточки (pitergsm_item) открываются и в скрытом браузере.")
        capture.assert_not_called()

    def test_the_tab_is_brought_to_the_front_before_its_visibility_is_asked(self):
        """In a shown Chrome that makes the site's tab the active one, as ym does for its clicks."""
        _, _, tab, _, _ = self.search(ANSWER)
        self.assertEqual([c[0] for c in tab.mock_calls if c[0] in ("call", "visible")][:2], ["call", "visible"])
        tab.call.assert_any_call("Page.bringToFront")
        tab.close.assert_called_once()

    def test_no_answer(self):
        for answer in (None, {"error": "x"}):
            got, _, tab, _, log = self.search(answer)
            self.assertEqual(got, "⚠️ PiterGSM не отдал результаты поиска (проверка на бота или сайт не успел): "
                                  "shop-chrome show, открыть сайт, повторить.")
            self.assertEqual(log.warning.call_args.args, ("%s search %s: no diginetica answer", "pitergsm", URL))
            tab.close.assert_called_once()

    def test_next_pages_are_not_reachable(self):
        with patch.object(digi, "tab_for") as tab_for:
            self.assertEqual(pitergsm.search("наушники", page=2),
                             "⚠️ PiterGSM подгружает следующие страницы поиска только прокруткой, их здесь нет: "
                             "уточни запрос или задай price_min / price_max / sort.")
        tab_for.assert_not_called()

    def test_unknown_sort(self):
        self.assertEqual(pitergsm.search("x", sort="rating"), "sort: одно из relevance, price_asc, price_desc")

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = MagicMock()
        tab.visible.return_value = True
        with patch.object(digi, "tab_for", return_value=tab), patch.object(digi, "capture", side_effect=pace.Refused("⏸")):
            self.assertRaises(pace.Refused, pitergsm.search, "x")
        tab.close.assert_called_once()

    def test_rub(self):
        self.assertEqual([digi._rub(x) for x in ("21990.0", "0.0", None, "", 1234567)], ["21990", "", "", "", "1234567"])


DESCRIPTION = "Знакомьтесь: Z Pro\n Шумоподавление. " + "Долго. " * 500
CARD = {"path": "/catalog/audio/naushniki/z-pro/120001/", "name": "Наушники Z Pro (белые)",
        "price": " 21 990 ₽ ", "old": " 24 990 ₽ ", "avail": "В наличии в магазине",
        "delivery": ["Доставка курьером сегодня от 500 ₽", "Доставка по Городу от 500 ₽", "Самовывоз из магазина бесплатно"],
        "variants": [{"name": " Цвет ", "values": [{"label": "Белый", "active": True}, {"label": "Чёрный", "active": False}]}],
        "specs": [{"name": "Тип", "val": " вставные "}, {"name": "Bluetooth", "val": "5.3"}, {"name": "Тип", "val": "вставные"}], "about": DESCRIPTION,
        "ld": {"sku": 120001, "image": [f"https://pitergsm.ru/upload/{i}.jpg" for i in range(12)],
               "offers": {"price": 21990, "availability": "https://schema.org/InStock"}}}
CARD_URL = "https://pitergsm.ru/catalog/audio/naushniki/z-pro/120001/"


class PitergsmItemTests(unittest.TestCase):
    def item(self, card, url=CARD_URL + "?x=1", **kw):
        tab = MagicMock()
        tab.js.return_value = card
        with patch.object(pitergsm, "tab_for", return_value=tab), patch.object(pitergsm, "log") as log:
            return pitergsm.item(url, **kw), tab, log

    def test_full_card(self):
        got, tab, _ = self.item(CARD)
        self.assertEqual(got, "Наушники Z Pro (белые)\n" + CARD_URL + "\nартикул: 120001\n"
                              "цена: 21990 ₽ (было 24990, −12%)\n"
                              "наличие: В наличии в магазине\n"
                              "получение: Доставка курьером сегодня от 500 ₽; Доставка по Городу от 500 ₽; Самовывоз из магазина бесплатно\n"
                              "Цвет: Белый (этот); Чёрный\n"
                              "характеристики: Тип: вставные; Bluetooth: 5.3\n"
                              "фото (shop_images): " + " ".join(f"https://pitergsm.ru/upload/{i}.jpg" for i in range(10)) + "\n"
                              "отзывы: на PiterGSM их нет (pitergsm_reviews)\n\n" + pitergsm._text(DESCRIPTION)[:2500])
        self.assertEqual(tab.goto.call_args.args, (CARD_URL, "pitergsm"))
        self.assertEqual(tab.goto.call_args.kwargs, {"wait_js": "document.querySelector('h1[data-product-name]')"})
        tab.close.assert_called_once()

    def test_full_description(self):
        self.assertTrue(self.item(CARD, full=True)[0].endswith("\n\n" + pitergsm._text(DESCRIPTION)))

    def test_bare_card(self):
        card = {"path": "/catalog/x/120002/", "name": "Подарок", "price": "", "old": None, "avail": None, "delivery": [],
                "variants": [], "specs": [], "about": "", "ld": {"image": "https://pitergsm.ru/upload/g.jpg", "offers": {}}}
        got = self.item(card, url="/catalog/x/120002")[0]
        self.assertEqual(got, "Подарок\nhttps://pitergsm.ru/catalog/x/120002/\nартикул: 120002\nцена: — ₽\nналичие: —\n"
                              "фото (shop_images): https://pitergsm.ru/upload/g.jpg\nотзывы: на PiterGSM их нет (pitergsm_reviews)\n\n")

    def test_the_price_is_json_ld_s_else_the_page_s(self):
        self.assertIn("\nцена: 21990 ₽ (было 24990, −12%)\n", self.item({**CARD, "price": "25 000 ₽"})[0])
        self.assertIn("\nцена: 25000 ₽\n", self.item({**CARD, "price": "25 000 ₽", "old": None, "ld": {}})[0])

    def test_specs_cut_only_past_twenty(self):
        for n, tail in ((20, "С 19: 19\n"), (21, "С 19: 19 … ещё 1 (full=True)\n")):
            got = self.item({**CARD, "specs": [{"name": f"С {i}", "val": str(i)} for i in range(n)]})[0]
            self.assertIn("; " + tail, got)
        self.assertIn("; С 24: 24\n", self.item({**CARD, "specs": [{"name": f"С {i}", "val": str(i)} for i in range(25)]}, full=True)[0])

    def test_old_price_not_above_the_price_is_dropped(self):
        self.assertIn("\nцена: 21990 ₽\n", self.item({**CARD, "old": "21 990 ₽"})[0])

    def test_blocked_or_another_card(self):
        for card in (None, {**CARD, "path": "/catalog/audio/naushniki/z-pro/120009/"}):
            got, tab, log = self.item(card)
            self.assertEqual(got, f"⚠️ PiterGSM не показал карточку {CARD_URL}: нет такого товара или проверка на бота "
                                  "(shop-chrome show, открыть сайт, повторить).")
            self.assertEqual(log.warning.call_args.args, ("pitergsm item %s: no product card", CARD_URL))
            tab.close.assert_called_once()

    def test_not_a_link(self):
        for s in ("120001", "наушники", "https://pitergsm.ru/catalog/audio/"):
            self.assertEqual(pitergsm.item(s), "нужна ссылка на товар PiterGSM (pitergsm.ru/catalog/…/<id>/) из pitergsm_search")

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = MagicMock()
        tab.goto.side_effect = pace.Refused("⏸")
        with patch.object(pitergsm, "tab_for", return_value=tab):
            self.assertRaises(pace.Refused, pitergsm.item, CARD_URL)
        tab.close.assert_called_once()


class PitergsmReviewsTests(unittest.TestCase):
    def test_the_site_has_none(self):
        with patch.object(pitergsm, "tab_for") as tab_for:
            got = pitergsm.reviews(CARD_URL, sort="low", with_media=True)
        self.assertEqual(got, "На PiterGSM нет отзывов покупателей о товарах: на сайте только ссылка на отзывы о магазине "
                              "на Яндекс Картах. Отзывы о модели — на маркетплейсах (ozon_reviews, wb_reviews, ym_reviews).")
        tab_for.assert_not_called()


class PitergsmHelperTests(unittest.TestCase):
    def test_path(self):
        for s, path in (("https://pitergsm.ru/catalog/audio/naushniki/z-pro/120001/?x=1#y", "/catalog/audio/naushniki/z-pro/120001/"),
                        ("pitergsm.ru/catalog/x/2", "/catalog/x/2/"), (" /catalog/phones/iphone/5/ ", "/catalog/phones/iphone/5/")):
            self.assertEqual(pitergsm._path(s), path)
        for s in ("120001", "", "https://pitergsm.ru/catalog/audio/", "https://biggeek.ru/catalog/x/1/"):
            self.assertIsNone(pitergsm._path(s))

    def test_rub(self):
        self.assertEqual([pitergsm._rub(x) for x in (" 21 990 ₽ ", "", None, "нет")], [21990, None, None, None])


if __name__ == "__main__":
    unittest.main()
