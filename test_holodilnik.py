"""Холодильник.ру: what its server-rendered pages hold (read by tab.js) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_holodilnik"""
import unittest
from unittest.mock import MagicMock, patch

import holodilnik
import pace

OLD, NEW = 1000.5, 2000.5       # performance.timeOrigin of the previous and of the loaded document


def run(fn, pages, *args, **kw):
    """fn(*args) with a tab whose page reads return pages one by one; -> (text, tab, log)."""
    tab = MagicMock()
    queue = list(pages)
    tab.js.side_effect = lambda expr, timeout=60: OLD if expr == "performance.timeOrigin" else queue.pop(0)
    with patch.object(holodilnik, "tab_for", return_value=tab), patch.object(holodilnik, "log") as log:
        return fn(*args, **kw), tab, log


def urls(tab):
    return [c.args[0] for c in tab.goto.call_args_list]


KETTLE = {"href": "/kitchen/kettles/brand/a1_black/", "code": "100", "name": "Чайник A1, чёрный", "price": "6\xa0779\xa0₽",
          "old": "8\xa0099\xa0₽", "rating": "4.9•7 отзывов", "count": "•7 отзывов", "delivery": ["c 16 ноября"],
          "badges": ["Еще 11% скидка", "Баллы"], "button": "В\xa0корзину"}
CABLE = {"href": "/digital/cables/b2/", "code": "200", "name": "Кабель B2", "price": "300 ₽", "old": "", "rating": "", "count": "",
         "delivery": [], "badges": [], "button": "Сообщить о поступлении"}


def listing(cards, found="2385", info=True, origin=NEW):
    return {"origin": origin, "info": info, "found": found, "cards": cards}


Q = "https://www.holodilnik.ru/search/?search=%D1%87%D0%B0%D0%B9%D0%BD%D0%B8%D0%BA"
HEAD = ("цены и наличие — для города из профиля на сайте; ссылки относительно https://www.holodilnik.ru\n"
        "#\tкод\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tналичие\tпометки\tссылка\n")


class SearchTests(unittest.TestCase):
    def search(self, pages, **kw):
        return run(holodilnik.search, pages, "чайник", **kw)

    def test_table(self):
        got, tab, _ = self.search([listing([KETTLE, CABLE])])
        self.assertEqual(got, f"Холодильник.ру · 2385 найдено · страница 1 (по 24) · {Q}\n" + HEAD +
                         "1\t100\t6779\t8099\tЧайник A1, чёрный\t4.9\t7\tc 16 ноября\tЕще 11% скидка, Баллы\t/kitchen/kettles/brand/a1_black/\n"
                         "2\t200\t300\t\tКабель B2\t\t\tСообщить о поступлении\t\t/digital/cables/b2/")
        self.assertEqual(urls(tab), [Q])
        self.assertEqual(tab.goto.call_args.args[1], "holodilnik")
        self.assertEqual(tab.goto.call_args.kwargs["wait_js"],
                         "performance.timeOrigin !== 1000.5 && !!document.querySelector('.site-footer')")
        tab.close.assert_called_once()

    def test_sort_and_page_go_into_the_url(self):
        _, tab, _ = self.search([listing([])], sort="price_asc", page=3)
        self.assertEqual(urls(tab), [Q + "&sort=price&page=3"])
        _, tab, _ = self.search([listing([])], sort="discount")
        self.assertEqual(urls(tab), [Q + "&sort=bestprice"])

    def test_unknown_sort(self):
        self.assertEqual(holodilnik.search("чайник", sort="cheap"),
                         "sort: одно из popular, price_asc, price_desc, discount, rating, stock")

    def test_price_filter_is_said_to_be_missing(self):
        with patch.object(holodilnik, "tab_for") as tab_for:
            for kw in ({"price_min": 100}, {"price_max": 900}):
                self.assertEqual(holodilnik.search("чайник", **kw), holodilnik.NO_PRICE)
        tab_for.assert_not_called()

    def test_nothing_found(self):
        got = self.search([listing([], found="")])[0]
        self.assertEqual(got, f"Холодильник.ру · 0 найдено · страница 1 (по 24) · {Q}\n" + HEAD + "(пусто)")

    def test_limit(self):
        self.assertEqual(len(self.search([listing([KETTLE, CABLE, KETTLE])], limit=2)[0].splitlines()), 5)

    def test_a_page_without_the_search_block_or_the_old_page_is_blocked(self):
        for page in (listing([], info=False), listing([KETTLE], origin=OLD), None):
            got, tab, log = self.search([page])
            self.assertEqual(got, holodilnik.BLOCKED)
            self.assertEqual(log.warning.call_args.args, ("holodilnik: no page at %s", Q))
            tab.close.assert_called_once()

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = MagicMock()
        tab.js.return_value = OLD
        tab.goto.side_effect = pace.Refused("⏸")
        with patch.object(holodilnik, "tab_for", return_value=tab):
            self.assertRaises(pace.Refused, holodilnik.search, "чайник")
        tab.close.assert_called_once()


DESCRIPTION = '<div class="h2">Описание</div> <br>Чайник&nbsp;<b>стальной</b>.<br>' + "Долго. " * 500
CARD = {"origin": NEW, "name": "Чайник A1, чёрный", "code": "100", "price": "6\xa0779\xa0₽", "old": "8\xa0099\xa0₽", "discount": " -16% ",
        "availability": "https://schema.org/InStock", "state": "В наличии", "rating": "4.90", "reviews": "7",
        "delivery": [["\n Самовывоз из магазина\n »\n", "c 15 ноября"], ["Доставка <span>»</span><SCRIPT>let x = 1;\n</SCRIPT>", "c 16 ноября"],
                     ["Пусто", ""]],
        "labels": ["Еще 11% скидка"],
        "specs": [["Высота, см\xa0", " <span>27</span> "], ["Дисплей\xa0", '<img width="18" src="/img/pres_ico.png">'],
                  ["Хаб\xa0", '<img src="/img/default.png">'], ["<a>Гарантия</a>\xa0", "<span>2 года</span>"]],
        "photos": ["//holod.ru/pics/watermark/big/1/0.jpg"] + [f"//holod.ru/pics/clean/big/1/{i}.jpg" for i in range(9)] +
                  ["/3d/get3dimg/1/a.jpg", "", "/3d/get3dimg/1/b.jpg"], "description": DESCRIPTION}
CARD_URL = "https://www.holodilnik.ru/kitchen/kettles/brand/a1_black/"
TEXT = "Чайник стальной . " + " ".join(["Долго."] * 500)


class ItemTests(unittest.TestCase):
    def item(self, pages, url=CARD_URL + "comments/r-d/?page=2#reviews", **kw):
        return run(holodilnik.item, pages, url, **kw)

    def test_full_card(self):
        got, tab, _ = self.item([CARD])
        self.assertEqual(got, "Чайник A1, чёрный\n" + CARD_URL + "\nкод товара: 100\n"
                              "цена: 6779 ₽ (было 8099, −16%)\n"
                              "наличие: В наличии\n"
                              "получение: Самовывоз из магазина — c 15 ноября; Доставка — c 16 ноября\n"
                              "рейтинг 4.9, отзывов 7\n"
                              "пометки: Еще 11% скидка\n"
                              "характеристики: Высота, см: 27; Дисплей: да; Хаб: нет; Гарантия: 2 года\n"
                              "фото (shop_images): " + " ".join(f"https://holod.ru/pics/clean/big/1/{i}.jpg" for i in range(9)) +
                              " https://www.holodilnik.ru/3d/get3dimg/1/a.jpg\n"
                              "отзывы: holodilnik_reviews\n\n" + TEXT[:2500])
        self.assertEqual(urls(tab), [CARD_URL])
        tab.close.assert_called_once()

    def test_full_description(self):
        self.assertTrue(self.item([CARD], full=True)[0].endswith("\n\n" + TEXT))

    def test_bare_card(self):
        got = self.item([{"origin": NEW, "name": "Кабель", "code": "200", "price": "300 ₽", "availability": "https://schema.org/OutOfStock"}],
                        url="holodilnik.ru/digital/cables/b2")[0]
        self.assertEqual(got, "Кабель\nhttps://www.holodilnik.ru/digital/cables/b2/\nкод товара: 200\nцена: 300 ₽\n"
                              "наличие: нет в наличии\nрейтинг —, отзывов 0\nотзывы: holodilnik_reviews\n\n")

    def test_a_code_is_found_by_search_first(self):
        got, tab, _ = self.item([listing([CABLE, KETTLE], found="2"), CARD], url=" 100 ")
        self.assertEqual(urls(tab), ["https://www.holodilnik.ru/search/?search=100", CARD_URL])
        self.assertTrue(got.startswith("Чайник A1, чёрный\n"))
        tab.close.assert_called_once()

    def test_a_code_search_does_not_find(self):
        got, tab, _ = self.item([listing([CABLE], found="1")], url="100")
        self.assertEqual(got, "Холодильник.ру не нашёл товар с кодом 100: нужна ссылка из holodilnik_search")
        self.assertEqual(self.item([None], url="100")[0], holodilnik.BLOCKED)

    def test_not_a_product(self):
        for bad in ("https://www.ozon.ru/a/b/", "/search/?search=x", "/kitchen/", "чайник"):
            self.assertEqual(holodilnik.item(bad), holodilnik.NO_ID, bad)

    def test_no_card_on_the_page(self):
        for page in ({"origin": NEW, "name": ""}, dict(CARD, origin=OLD)):
            got, tab, log = self.item([page])
            self.assertEqual(got, holodilnik.BLOCKED)
            self.assertEqual(log.warning.call_args.args, ("holodilnik: no page at %s", CARD_URL))
            tab.close.assert_called_once()


def review(n, rows, time="04.03.2026, 11:44", stars="5,00", yes="3", no="1"):
    return {"time": time, "stars": stars, "yes": yes, "no": no, "rows": [["Рейтинг:", f'<div class="rating_number">{stars}</div>']] + rows}


REVIEWS = [review(1, [["Преимущества:", "Тихий,<br> быстрый"], ["Недостатки: ", " Шнур&nbsp;короткий"], ["Комментарий: ", "Хороший."]]),
           review(2, [["Комментарий: ", "Так себе"]], time="01.02.2025, 10:00", stars="2,50", yes="", no="")]


def opinions(items, count="22", rating="4,80", pager="Страницы: [1] 2 3 4", box=True, origin=NEW):
    return {"origin": origin, "box": box, "name": "Чайник A1, чёрный", "rating": rating, "count": count, "pager": pager, "items": items}


REV_URL = CARD_URL + "comments/"
REV_HEAD = ("Холодильник.ру · Чайник A1, чёрный: рейтинг 4.8, отзывов 22\n"
            "страница 1 из 4 (по 7), сортировка new; фото в отзывах сайт не показывает\n"
            "дата\t★\tполезно (да/нет)\tтекст\n")


class ReviewsTests(unittest.TestCase):
    def reviews(self, pages, url=CARD_URL, **kw):
        return run(holodilnik.reviews, pages, url, **kw)

    def test_page(self):
        got, tab, _ = self.reviews([opinions(REVIEWS)])
        self.assertEqual(got, REV_HEAD + "04.03.2026 11:44\t5\t3/1\t+ Тихий, быстрый | − Шнур короткий | Хороший.\n"
                                         "01.02.2025 10:00\t2.5\t0/0\tТак себе")
        self.assertEqual(urls(tab), [REV_URL])
        tab.close.assert_called_once()

    def test_sort_and_page_go_into_the_url(self):
        for sort, part in (("old", "date-a/"), ("high", "r-d/"), ("low", "r-a/")):
            got, tab, _ = self.reviews([opinions([], pager="Страницы: 1 [2]")], sort=sort, page=2)
            self.assertEqual(urls(tab), [REV_URL + part + "?page=2"])
            self.assertIn(f"страница 2 из 2 (по 7), сортировка {sort};", got)

    def test_what_the_site_does_not_do(self):
        self.assertEqual(holodilnik.reviews(CARD_URL, sort="useful"),
                         "Холодильник.ру не сортирует отзывы по полезности: sort одно из new, old, high, low")
        self.assertEqual(holodilnik.reviews(CARD_URL, sort="x"), "sort: одно из new, old, high, low")
        self.assertEqual(holodilnik.reviews(CARD_URL, with_media=True),
                         "Холодильник.ру не показывает фото в отзывах и не отбирает отзывы с ними: повтори без with_media")
        self.assertEqual(holodilnik.reviews("чайник"), holodilnik.NO_ID)

    def test_no_reviews(self):
        got = self.reviews([opinions([], count="", rating="", pager="")])[0]
        self.assertEqual(got, "Холодильник.ру · Чайник A1, чёрный: рейтинг —, отзывов 0\n"
                              "страница 1 из 1 (по 7), сортировка new; фото в отзывах сайт не показывает\n"
                              "дата\t★\tполезно (да/нет)\tтекст\n(отзывов нет)")

    def test_limit(self):
        self.assertEqual(len(self.reviews([opinions(REVIEWS)], limit=1)[0].splitlines()), 4)

    def test_by_code(self):
        _, tab, _ = self.reviews([listing([KETTLE], found="1"), opinions(REVIEWS)], url="100", sort="high")
        self.assertEqual(urls(tab), ["https://www.holodilnik.ru/search/?search=100", REV_URL + "r-d/"])

    def test_blocked(self):
        for page in (opinions([], box=False), opinions(REVIEWS, origin=OLD)):
            got, tab, log = self.reviews([page])
            self.assertEqual(got, holodilnik.BLOCKED)
            self.assertEqual(log.warning.call_args.args, ("holodilnik: no page at %s", REV_URL))
            tab.close.assert_called_once()


class PathTests(unittest.TestCase):
    def test_paths(self):
        for s in ("https://www.holodilnik.ru/a/b/c/", "http://holodilnik.ru/a/b/c", "www.holodilnik.ru/a/b/c/#reviews",
                  "/a/b/c/comments/date-a/?page=3", " /a/b/c/?utm=1 "):
            self.assertEqual(holodilnik._path(s), "/a/b/c/", s)
        self.assertEqual(holodilnik._path("/a/b"), "/a/b/")
        for s in ("/search/x/", "/a/", "https://www.holodilnik.ru/", "123", "", "https://evil.ru/holodilnik.ru/a/b/"):
            self.assertIsNone(holodilnik._path(s), s)


if __name__ == "__main__":
    unittest.main()
