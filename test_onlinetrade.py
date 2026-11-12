"""ОНЛАЙН ТРЕЙД.РУ: what the site's pages show (read by the module's JS) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_onlinetrade"""
import unittest
from unittest.mock import MagicMock, patch

import onlinetrade
import pace

QUERY = "https://www.onlinetrade.ru/sitesearch.html?force_items=1&query=%ED%E0%F3%F8%ED%E8%EA%E8+a1"     # «наушники a1» in cp1251
HEAD = ("ссылки относительно https://www.onlinetrade.ru; цены — для города из профиля на сайте; "
        "наличие, доставка и старая цена — в onlinetrade_item\n"
        "#\tкод\tцена ₽\tскидка\tназвание\tрейтинг\tоценок\tпометки\tссылка\n")
EARBUDS = {"href": "/catalogue/naushniki-c1/brand/naushniki_a1-100.html", "name": " Наушники  A1, белый ", "price": " 1 849 ₽",
           "marks": [["mark mark__discount", "-10%"], ["mark mark__new", "Новинка"]], "stars": "4 звезды по 12 оценкам", "votes": " 12"}
CABLE = {"href": "/catalogue/kabeli-c2/x/kabel-200.html", "name": "Кабель", "price": "300 ₽", "marks": [], "stars": "Нет оценок", "votes": "0"}


def tab_with(data, origin=1.5):
    """A tab whose page answers the module's JS with data (performance.timeOrigin with origin)."""
    tab = MagicMock()
    tab.js.side_effect = lambda expr: origin if expr == "performance.timeOrigin" else data
    return tab


class SearchTests(unittest.TestCase):
    def search(self, data, query="наушники a1", **kw):
        tab = tab_with(data)
        with patch.object(onlinetrade, "tab_for", return_value=tab) as tab_for, patch.object(onlinetrade, "log") as log:
            got = onlinetrade.search(query, **kw)
        return got, tab, tab_for, log

    def test_a_page_of_results(self):
        got, tab, tab_for, _ = self.search({"listing": True, "count": "Показано: 1–30 из 37", "cards": [EARBUDS, CABLE]})
        self.assertEqual(got, f"ОНЛАЙН ТРЕЙД.РУ · 37 найдено · страница 1 (по 30) · {QUERY}\n" + HEAD +
                         "1\t100\t1849\t−10%\tНаушники A1, белый\t4\t12\tНовинка\t/catalogue/naushniki-c1/brand/naushniki_a1-100.html\n"
                         "2\t200\t300\t\tКабель\t\t\t\t/catalogue/kabeli-c2/x/kabel-200.html")
        tab_for.assert_called_once_with("onlinetrade.ru")
        tab.goto.assert_called_once_with(QUERY, "onlinetrade", wait_js="performance.timeOrigin !== 1.5 && document.readyState === 'complete'")
        tab.close.assert_called_once()

    def test_sort_and_page_go_into_the_url(self):
        got, tab, _, _ = self.search({"listing": True, "count": "", "cards": []}, sort="price_asc", page=3)
        url = QUERY + "&sort=price-asc&page=2"            # the site counts pages from 0
        self.assertEqual(tab.goto.call_args.args[0], url)
        self.assertEqual(got, f"ОНЛАЙН ТРЕЙД.РУ · 0 найдено · страница 3 (по 30) · {url}\n" + HEAD + "(пусто)")

    def test_without_a_pager_the_cards_are_counted(self):
        got = self.search({"listing": True, "count": "", "cards": [CABLE]})[0]
        self.assertTrue(got.startswith("ОНЛАЙН ТРЕЙД.РУ · 1 найдено ·"))

    def test_limit(self):
        self.assertEqual(len(self.search({"listing": True, "count": "", "cards": [EARBUDS, CABLE]}, limit=1)[0].splitlines()), 4)

    def test_a_query_outside_cp1251_still_goes(self):
        self.assertEqual(self.search({"listing": True, "cards": []}, query="ёж 🦔")[1].goto.call_args.args[0],
                         "https://www.onlinetrade.ru/sitesearch.html?force_items=1&query=%B8%E6+%3F")

    def test_bad_arguments(self):
        self.assertEqual(onlinetrade.search("x", sort="cheap"), "sort: одно из popular, price_asc, price_desc, new, reviews")
        for kw in ({"price_min": 100}, {"price_max": 900}):
            self.assertEqual(onlinetrade.search("x", **kw),
                             "ОНЛАЙН ТРЕЙД.РУ не фильтрует поиск по цене: повтори без price_min и price_max (sort=price_asc — от дешёвых)")

    def test_blocked(self):
        for data in (None, {"listing": False, "cards": []}):
            got, tab, _, log = self.search(data)
            self.assertEqual(got, onlinetrade.BLOCKED)
            self.assertEqual(log.warning.call_args.args, ("onlinetrade search %s: no listing", QUERY))
            tab.close.assert_called_once()

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = tab_with(None)
        tab.goto.side_effect = pace.Refused("⏸")
        with patch.object(onlinetrade, "tab_for", return_value=tab):
            self.assertRaises(pace.Refused, onlinetrade.search, "x")
            self.assertRaises(pace.Refused, onlinetrade.item, "100")
            self.assertRaises(pace.Refused, onlinetrade.reviews, "100")
        self.assertEqual(tab.close.call_count, 3)


DESCRIPTION = "<h2>Наушники A1</h2><p>Звук&nbsp;<b>чистый</b>.</p>" + "Долго. " * 500
PHOTOS = ["https://static.x/img/items/b/a_1.jpg", "https://static.x/img/items/m/a_1.jpg", "https://static.x/img/items/s/a_2.jpg", None,
          "/templates/desktop/img/zoom.png"] + [f"https://static.x/img/items/m/a_{i}.jpg" for i in range(3, 13)]
CARD = {"code": "100", "name": "Наушники A1, белый", "url": "https://www.onlinetrade.ru/catalogue/naushniki-c1/brand/naushniki_a1-100.html",
        "price": "1849", "old": "2 050 ₽", "discount": "-10%", "avail": " в наличии  > 10 шт.", "rating": "4.0", "votes": "12",
        "short": [["Тип:", "вкладыши\xa0"], ["Цвет:", "белый "]], "specs": [["Тип:", "вкладыши"], ["Цвет:", "белый"], ["Вес:", "5 г"]],
        "text": DESCRIPTION, "photos": PHOTOS, "pickups": "Показать все 12 магазинов",
        "rows": [[False, "Доставка курьером, ", "завтра (13.11, пятница)", " 400 ₽ "],
                 [True, "Центральный", "сегодня, через 1 час ", "бесплатно"], [True, "Северный", "завтра (13.11, пятница) c 10:00", "бесплатно"]],
        "tab": "2", "reviews": []}
BY_CODE = "https://www.onlinetrade.ru/catalogue/x-c1/x/x-100.html"      # the site sends any such address to the card's own


class ItemTests(unittest.TestCase):
    def item(self, card, url="https://www.onlinetrade.ru/catalogue/naushniki-c1/brand/naushniki_a1-100.html?utm=x#tabs", **kw):
        tab = tab_with(card)
        with patch.object(onlinetrade, "tab_for", return_value=tab), patch.object(onlinetrade, "log") as log:
            return onlinetrade.item(url, **kw), tab, log

    def test_full_card(self):
        got, tab, _ = self.item(CARD)
        self.assertEqual(got, "Наушники A1, белый\n" + CARD["url"] + "\nкод товара: 100\n"
                              "цена: 1849 ₽ (было 2050, −10%)\n"
                              "наличие: в наличии > 10 шт.\n"
                              "доставка: Доставка курьером — завтра (13.11, пятница), 400 ₽\n"
                              "самовывоз (12 магазинов): Центральный — сегодня, через 1 час, бесплатно; "
                              "Северный — завтра (13.11, пятница) c 10:00, бесплатно\n"
                              "рейтинг 4.0, оценок 12\n"
                              "характеристики: Тип: вкладыши; Цвет: белый\n"
                              "фото (shop_images): " + " ".join(f"https://static.x/img/items/b/a_{i}.jpg" for i in range(1, 11)) + "\n"
                              "отзывы: onlinetrade_reviews\n\n" + onlinetrade._text(DESCRIPTION)[:2500])
        tab.goto.assert_called_once_with(BY_CODE, "onlinetrade", wait_js="performance.timeOrigin !== 1.5 && document.readyState === 'complete'")
        tab.close.assert_called_once()

    def test_full_description_and_specs(self):
        got = self.item(CARD, full=True)[0]
        self.assertIn("\nхарактеристики: Тип: вкладыши; Цвет: белый; Вес: 5 г\n", got)
        self.assertTrue(got.endswith("\n\n" + onlinetrade._text(DESCRIPTION)))

    def test_bare_card_by_its_code(self):
        got, tab, _ = self.item({"code": "100", "name": "Кабель", "url": BY_CODE}, url=" 100 ")
        self.assertEqual(tab.goto.call_args.args[0], BY_CODE)
        self.assertEqual(got, f"Кабель\n{BY_CODE}\nкод товара: 100\nцена: —\nналичие: —\nрейтинг —, оценок 0\n"
                              "отзывы: onlinetrade_reviews\n\n")

    def test_not_a_link(self):
        for s in ("наушники", "https://www.onlinetrade.ru/basket.html?add=100", "https://example.com/catalogue/x-100.html", ""):
            self.assertEqual(onlinetrade.item(s), "нужна ссылка на товар ОНЛАЙН ТРЕЙД.РУ или его код из onlinetrade_search")

    def test_blocked_or_another_card(self):
        for card in (None, {**CARD, "code": "999"}):
            got, tab, log = self.item(card)
            self.assertEqual(got, onlinetrade.BLOCKED)
            self.assertEqual(log.warning.call_args.args, ("onlinetrade %s: no product card", BY_CODE))
            tab.close.assert_called_once()


def review(date, stars, plus="0", minus="0", of="", parts=(("Достоинства:", " удобные"), ("Недостатки:", " шнур "), ("Комментарий:", " Звук\nнорм"))):
    return {"date": date, "stars": f"Оценка: {stars}", "of": of, "parts": [list(p) for p in parts], "plus": plus, "minus": minus}


REVIEWS = [review("2025-05-04", 3, "6", "1"), review("2024-01-02", 5, None, "2", of="Наушники A1, чёрный", parts=()),
           review("2026-02-03", 4, "9", parts=(("Комментарий:", "ок"),))]
COLUMNS = "дата\t★\tполезно\tдостоинства\tнедостатки\tтекст\tдругой вариант\n"
NOTE = "все отзывы — со страницы товара, сортирует и делит на страницы этот инструмент; фото к отзывам сайт не показывает\n"


class ReviewsTests(unittest.TestCase):
    def reviews(self, card, id_or_url="100", **kw):
        tab = tab_with(card)
        with patch.object(onlinetrade, "tab_for", return_value=tab), patch.object(onlinetrade, "log") as log:
            return onlinetrade.reviews(id_or_url, **kw), tab, log

    def test_most_useful_first(self):
        got, tab, _ = self.reviews({**CARD, "tab": "3", "reviews": REVIEWS})
        self.assertEqual(got, "ОНЛАЙН ТРЕЙД.РУ · товар 100: рейтинг 4.0, оценок 12, отзывов 3\n"
                              "страница 1 из 1 (по 20), сортировка useful; " + NOTE + COLUMNS +
                              "2026-02-03\t4\t+9 −0\t\t\tок\t\n"
                              "2025-05-04\t3\t+6 −1\tудобные\tшнур\tЗвук норм\t\n"
                              "2024-01-02\t5\t+0 −2\t\t\t\tНаушники A1, чёрный")
        self.assertEqual(tab.goto.call_args.args[0], BY_CODE)
        tab.close.assert_called_once()

    def test_sorts_and_pages(self):
        card = {**CARD, "reviews": REVIEWS}
        dates = lambda got: [line.split("\t")[0] for line in got.splitlines()[3:]]
        self.assertEqual(dates(self.reviews(card, sort="new")[0]), ["2026-02-03", "2025-05-04", "2024-01-02"])
        self.assertEqual(dates(self.reviews(card, sort="old")[0]), ["2024-01-02", "2025-05-04", "2026-02-03"])
        self.assertEqual(dates(self.reviews(card, sort="high")[0]), ["2024-01-02", "2026-02-03", "2025-05-04"])
        self.assertEqual(dates(self.reviews(card, sort="low")[0]), ["2025-05-04", "2026-02-03", "2024-01-02"])
        no_votes = {**CARD, "reviews": [review("2020-01-01", 5, "0"), review("2021-01-01", 5, None)]}     # no «+» counts as 0
        self.assertEqual(dates(self.reviews(no_votes)[0]), ["2020-01-01", "2021-01-01"])
        got = self.reviews(card, sort="new", page=2, limit=2)[0]
        self.assertEqual(got.splitlines()[1], "страница 2 из 2 (по 2), сортировка new; " + NOTE.strip())
        self.assertEqual(dates(got), ["2024-01-02"])

    def test_fewer_on_the_page_than_the_site_counts(self):
        got = self.reviews({**CARD, "tab": "40", "reviews": REVIEWS[:1]})[0]
        self.assertEqual(got.splitlines()[0], "ОНЛАЙН ТРЕЙД.РУ · товар 100: рейтинг 4.0, оценок 12, отзывов 40 (на странице только 1)")

    def test_no_reviews_yet(self):
        got = self.reviews({"code": "100", "name": "Кабель"})[0]
        self.assertEqual(got, "ОНЛАЙН ТРЕЙД.РУ · товар 100: рейтинг —, оценок 0, отзывов 0\n"
                              "страница 1 из 1 (по 20), сортировка useful; " + NOTE + COLUMNS + "(отзывов нет)")

    def test_blocked(self):
        got, tab, log = self.reviews({**CARD, "code": "7"})
        self.assertEqual(got, onlinetrade.BLOCKED)
        self.assertEqual(log.warning.call_args.args, ("onlinetrade %s: no product card", BY_CODE))
        tab.close.assert_called_once()

    def test_bad_arguments(self):
        self.assertEqual(onlinetrade.reviews("наушники"), "нужна ссылка на товар ОНЛАЙН ТРЕЙД.РУ или его код из onlinetrade_search")
        self.assertEqual(onlinetrade.reviews("100", sort="best"), "sort: одно из useful, new, old, high, low")
        self.assertEqual(onlinetrade.reviews("100", with_media=True),
                         "ОНЛАЙН ТРЕЙД.РУ не прикрепляет фото к отзывам (фото покупателей — в галерее на странице товара): повтори без with_media")


class HelperTests(unittest.TestCase):
    def test_code_from_a_link_or_a_code(self):
        for s in ("https://www.onlinetrade.ru/catalogue/naushniki-c92/sony/naushniki_x-149729.html?x=1#y", "onlinetrade.ru/catalogue/a-c1/b-149729.html",
                  "/catalogue/naushniki-c92/sony/naushniki_x-149729.html", " 149729 ", 149729):
            self.assertEqual(onlinetrade._code(s), "149729")
        for s in ("наушники", "https://www.onlinetrade.ru/sitesearch.html?query=1", "/basket.html?add=149729", "12a", None):
            self.assertIsNone(onlinetrade._code(s))

    def test_rub(self):
        self.assertEqual([onlinetrade._rub(x) for x in (" 1 849 ₽", "", None, "₽")], ["1849", "", "", ""])

    def test_text_from_markup(self):
        self.assertEqual(onlinetrade._text("<p>Звук&nbsp;<b>чистый</b></p>\n "), "Звук чистый")
        self.assertEqual(onlinetrade._text(None), "")

    def test_photos_largest_once_each(self):
        self.assertEqual(onlinetrade._photos(PHOTOS[:5]), ["https://static.x/img/items/b/a_1.jpg", "https://static.x/img/items/b/a_2.jpg"])
        self.assertEqual(onlinetrade._photos(None), [])

    def test_stars(self):
        self.assertEqual([onlinetrade._stars(s) for s in ("5 звезд по 27 оценкам", "4.5 звезды по 2 оценкам", "Нет оценок", None, "Оценка: 3")],
                         ["5", "4.5", "", "", "3"])


if __name__ == "__main__":
    unittest.main()
