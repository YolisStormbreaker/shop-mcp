"""Технопарк: the site's page data (search, product card) and GraphQL answers (delivery, reviews) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_technopark"""
import unittest
from unittest.mock import MagicMock, call, patch

import pace
import technopark


def product(pid, slug, name, price, status="В наличии", rating=4.5):
    return {"id": pid, "slug": slug, "name": {"full": name}, "price": price, "status": {"name": status}, "rating": {"average": rating}}


EARBUDS = product("500", "naushniki-a1-500", "Наушники A1", {"default": 9000, "marketing": None, "old": 12000})
CABLE = product("600", "kabel-usb-c", "Кабель USB-C", {"default": 900, "marketing": 800, "old": None}, "На витрине", None)
BOX = product("700", "korobka-700", "Коробка", {"default": None, "marketing": None, "old": None}, "Нет в наличии", 0)
QUERY = "https://www.technopark.ru/search/?q=%D0%BD%D0%B0%D1%83%D1%88%D0%BD%D0%B8%D0%BA%D0%B8"
SEARCH_HEAD = ("ссылки относительно https://www.technopark.ru; цены и наличие — для города из профиля на сайте; "
               "technopark_item и technopark_reviews берут ссылку, не код\n"
               "#\tкод\tцена ₽\tбез скидки\tназвание\tрейтинг\tналичие\tссылка\n")


class TechnoparkSearchTests(unittest.TestCase):
    def search(self, page_data, **kw):
        tab = MagicMock()
        tab.js.side_effect = [None, page_data]
        with patch.object(technopark, "tab_for", return_value=tab), patch.object(technopark, "log") as log:
            return technopark.search("наушники", **kw), tab, log

    def test_page(self):
        got, tab, _ = self.search({"query": "наушники", "currentPage": 1, "total": 938, "products": [EARBUDS, CABLE, BOX]})
        self.assertEqual(got, f"Технопарк · 938 найдено · страница 1 (по 24) · {QUERY}\n" + SEARCH_HEAD +
                         "1\t500\t9000\t12000\tНаушники A1\t4.5\tВ наличии\t/naushniki-a1-500/\n"
                         "2\t600\t800\t900\tКабель USB-C\t\tНа витрине\t/kabel-usb-c/\n"
                         "3\t700\t\t\tКоробка\t\tНет в наличии\t/korobka-700/")
        tab.goto.assert_called_once_with(QUERY, "technopark", wait_js=technopark.FRESH)
        self.assertEqual(tab.js.call_args_list[0], call("window.__shopStale = true"))
        self.assertEqual(tab.js.call_args_list[1], call(technopark.SEARCH_JS))
        tab.close.assert_called_once()

    def test_sort_price_and_page_go_into_the_url(self):
        got = self.search({"query": "наушники", "currentPage": 3, "total": 0, "products": []}, price_max=1000, sort="price_asc",
                          page=3, limit=5)[0]
        url = QUERY + "&order=price&dir=asc&filter_%D0%A6%D0%B5%D0%BD%D0%B0_min=0&filter_%D0%A6%D0%B5%D0%BD%D0%B0_max=1000&p=3"
        self.assertEqual(got, f"Технопарк · 0 найдено · страница 3 (по 24) · {url}\n" + SEARCH_HEAD + "(пусто)")
        got = self.search({"query": "наушники", "currentPage": 1, "products": []}, price_min=500, sort="rating")[0]
        self.assertIn("&order=rating&dir=desc&filter_%D0%A6%D0%B5%D0%BD%D0%B0_min=500&filter_%D0%A6%D0%B5%D0%BD%D0%B0_max=10000000\n",
                      got)
        self.assertIn(" 0 найдено", got)

    def test_limit(self):
        got = self.search({"query": "наушники", "currentPage": 1, "total": 3, "products": [EARBUDS, CABLE, BOX]}, limit=2)[0]
        self.assertEqual(len(got.splitlines()), 5)

    def test_unknown_sort(self):
        self.assertEqual(technopark.search("наушники", sort="cheap"), "sort: одно из relevance, price_asc, price_desc, rating")

    def test_no_page_data_or_another_page(self):
        for data in (None, {"query": "чайник", "currentPage": 1, "products": [EARBUDS]}, {"query": "наушники", "currentPage": 2}):
            got, tab, log = self.search(data)
            self.assertEqual(got, technopark.BLOCKED)
            self.assertEqual(log.warning.call_args.args, ("technopark search %s: no search data", QUERY))
            tab.close.assert_called_once()

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = MagicMock()
        tab.goto.side_effect = pace.Refused("⏸")
        with patch.object(technopark, "tab_for", return_value=tab):
            self.assertRaises(pace.Refused, technopark.search, "наушники")
        tab.close.assert_called_once()


DESCRIPTION = "<style>body{margin:0}</style><p>Звук&nbsp;чистый.</p><script>x()</script> " + "Долго. " * 500
TEXT = "Звук чистый. " + ("Долго. " * 500).strip()
CARD = {"id": "500", "slug": "naushniki-a1-500", "name": "Наушники A1", "price": {"default": 9000, "marketing": None, "old": 12000},
        "status": "В наличии", "rating": 4.8, "reviews": 6, "description": DESCRIPTION,
        "short": [{"name": "Тип", "value": "вкладыши"}, {"name": "Вес", "value": "5 г"}],
        "gallery": [f"https://cdn/{i}.jpg" for i in range(12)]}
LOGISTICS = {"productV2": {"id": "500", "logistics": {
    "delivery": [{"name": "Технопарк", "price": 0, "date": "2026-11-13T00:00:00+0300"},
                 {"name": "СДЭК", "price": 390, "date": "2026-11-15T00:00:00+0300"}],
    "pickup": [{"name": "Забрать в магазине Технопарк", "price": 0, "date": "2026-11-12T00:00:00+0300"}]}}}
CARD_URL = "https://www.technopark.ru/naushniki-a1-500/"


def answers(*data):
    return {f"g{i}": d if d is None or "data" in d else {"data": d} for i, d in enumerate(data)}


class TechnoparkItemTests(unittest.TestCase):
    def item(self, card, got=(), url=CARD_URL + "otzyvy/?utm=x", **kw):
        tab = MagicMock()
        tab.js.return_value = card
        with patch.object(technopark, "tab_for", return_value=tab), \
                patch.object(technopark, "capture", return_value=answers(*got)) as capture, patch.object(technopark, "log") as log:
            return technopark.item(url, **kw), capture, tab, log

    def test_full_card(self):
        got, capture, tab, _ = self.item(CARD, [{"events": {}}, None, {"errors": []}, LOGISTICS])
        self.assertEqual(got, "Наушники A1\n" + CARD_URL + "\nкод товара: 500\n"
                              "цена: 9000 ₽ (было 12000, −25%)\n"
                              "наличие: В наличии\n"
                              "доставка: Технопарк — 2026-11-13, бесплатно; СДЭК — 2026-11-15, 390 ₽\n"
                              "самовывоз: Забрать в магазине Технопарк — 2026-11-12, бесплатно\n"
                              "рейтинг 4.8, отзывов 6\n"
                              "характеристики: Тип: вкладыши; Вес: 5 г\n"
                              "фото (shop_images): " + " ".join(f"https://cdn/{i}.jpg" for i in range(10)) + "\n"
                              "отзывы: technopark_reviews\n\n" + TEXT[:2500])
        args, kw = capture.call_args
        self.assertEqual(args[:3], (tab, "technopark", CARD_URL))
        self.assertEqual(set(map(tuple, args[3].values())), {("/graphql/",)})
        self.assertEqual(len(args[3]) - len(kw["optional"]), 6)
        self.assertEqual(kw["optional"], list(args[3])[:len(kw["optional"])])   # capture fills the last names first
        self.assertEqual(tab.js.call_args, call(technopark.ITEM_JS))
        tab.close.assert_called_once()

    def test_full_description(self):
        self.assertTrue(self.item(CARD, [LOGISTICS], full=True)[0].endswith("\n\n" + TEXT))

    def test_bare_card_by_its_address(self):
        bare = {"slug": "kabel-usb-c", "name": "Кабель", "price": {}, "status": None}
        got, capture, _, _ = self.item(bare, [{"productV2": {"logistics": {"delivery": [], "pickup": []}}}], url=" kabel-usb-c ")
        self.assertEqual(capture.call_args.args[2], "https://www.technopark.ru/kabel-usb-c/")
        self.assertEqual(got, "Кабель\nhttps://www.technopark.ru/kabel-usb-c/\nкод товара: None\nцена: не указана\nналичие: —\n"
                              "рейтинг —, отзывов 0\nотзывы: technopark_reviews\n\n")

    def test_an_answer_without_terms_is_no_delivery_line(self):
        got = self.item(CARD, [{"productV2": {"id": "500", "logistics": None}}])[0]
        self.assertIn("\nналичие: В наличии\nрейтинг", got)

    def test_delivery_not_caught_is_said(self):
        got = self.item(CARD, [{"productV2": {"id": "500", "bonus": {}}}])[0]
        self.assertIn("\nналичие: В наличии\nполучение: сроки не пришли, повтори позже\nрейтинг", got)

    def test_not_a_link(self):
        for s in ("наушники белые", "123456", "https://www.technopark.ru/search/?q=x"):
            self.assertEqual(technopark.item(s), technopark.NO_SLUG)

    def test_blocked_or_another_card(self):
        for card in (None, {**CARD, "slug": "naushniki-b2-501"}):
            got, _, tab, log = self.item(card)
            self.assertEqual(got, technopark.BLOCKED)
            self.assertEqual(log.warning.call_args.args, ("technopark item %s: no product card", CARD_URL))
            tab.close.assert_called_once()

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = MagicMock()
        with patch.object(technopark, "tab_for", return_value=tab), patch.object(technopark, "capture", side_effect=pace.Refused("⏸")):
            self.assertRaises(pace.Refused, technopark.item, CARD_URL)
        tab.close.assert_called_once()


def review(**kw):
    return {"date": "2026-05-04T08:00:00+0300", "rating": 5, "userName": "Покупатель К.", "likes": 3, "pros": "", "cons": "",
            "comment": "", "isRecommendation": False, "wasBoughtInTechnopark": False, "isPartnerReview": False, "period": None,
            "product": {"id": "500", "slug": "naushniki-a1-500"}, **kw}


LISTING = {"productV2": {"id": "500", "rating": {"average": 4.8, "total": {"all": 13, "value1": 1, "value2": 0, "value3": 0,
                                                                            "value4": 2, "value5": 10}},
                         "reviews": {"total": 13, "totalRecommendations": 9, "list": {"data": [
                             review(pros="удобные", cons="громкость", comment="Звук&nbsp;норм", isRecommendation=True,
                                    wasBoughtInTechnopark=True, period="менее месяца"),
                             review(rating=4, userName=None, likes=0, isPartnerReview=True,
                                    product={"id": "501", "slug": "naushniki-a1-chernye-501"})]}}}}
COUNT = {"productV2": {"id": "500", "rating": {"average": 4.8}, "reviews": {"total": 13, "totalRecommendations": 9}}}
REVIEWS_URL = "https://www.technopark.ru/naushniki-a1-500/otzyvy/"
REVIEWS_HEAD = "дата\t★\tполезно\tавтор\tтекст\tпометки\tдругой вариант\n"


class TechnoparkReviewsTests(unittest.TestCase):
    def reviews(self, *loads, id_or_url=CARD_URL, **kw):
        tab = MagicMock()
        with patch.object(technopark, "tab_for", return_value=tab), \
                patch.object(technopark, "capture", side_effect=[answers(*got) for got in loads]) as capture, \
                patch.object(technopark, "log") as log:
            return technopark.reviews(id_or_url, **kw), capture, tab, log

    def test_first_page(self):
        got, capture, tab, _ = self.reviews([COUNT, {"events": {}}, LISTING])
        self.assertEqual(got, "Технопарк · товар 500: рейтинг 4.8, отзывов 13, рекомендуют 9 · 5★ 10, 4★ 2, 1★ 1\n"
                              "страница 1 из 2 (по 10), сортировка useful; фото в отзывах сайт не отдаёт; счёт и список — по всем вариантам товара (столбец «другой вариант»)\n" + REVIEWS_HEAD +
                              "2026-05-04\t5\t3\tПокупатель К.\t+ удобные | − громкость | Звук норм\t"
                              "куплен в Технопарке, рекомендует, срок использования: менее месяца\t\n"
                              "2026-05-04\t4\t\t\t\tотзыв партнёра\tnaushniki-a1-chernye-501")
        args, kw = capture.call_args
        self.assertEqual(args[:3], (tab, "technopark", REVIEWS_URL))
        self.assertEqual(len(args[3]) - len(kw["optional"]), 6)
        self.assertIsNone(kw.get("js"))
        tab.close.assert_called_once()

    def test_another_page_or_sort_asks_the_page_itself(self):
        second = {"productV2": {**LISTING["productV2"], "reviews": {**LISTING["productV2"]["reviews"],
                                                                     "list": {"data": [review(comment="позже")]}}}}
        got, capture, tab, _ = self.reviews([LISTING], [{"events": {}}, second], id_or_url="naushniki-a1-500", sort="new", page=2)
        self.assertEqual(got.splitlines()[1], "страница 2 из 2 (по 10), сортировка new; фото в отзывах сайт не отдаёт; счёт и список — по всем вариантам товара (столбец «другой вариант»)")
        self.assertEqual(got.splitlines()[3:], ["2026-05-04\t5\t3\tПокупатель К.\tпозже\t\t"])
        first, then = capture.call_args_list
        self.assertEqual(first.args[2], REVIEWS_URL)
        self.assertEqual(then.args[:3], (tab, "technopark", None))
        self.assertEqual(then.kwargs["js"], technopark._reviews_js("new", 2))
        self.assertEqual(len(then.args[3]) - len(then.kwargs["optional"]), 1)
        self.assertIn("{field: \"DATE\", order: \"DESC\"}", then.kwargs["js"])
        self.assertIn("loadReviews(2, false)", then.kwargs["js"])
        self.assertEqual(self.reviews([LISTING], [LISTING], page=3)[1].call_args.kwargs["js"], technopark._reviews_js("useful", 3))
        tab.close.assert_called_once()

    def test_the_page_did_not_give_another_page(self):
        got, _, tab, log = self.reviews([LISTING], [{"events": {}}], page=2)
        self.assertEqual(got, technopark.NO_OTHER_PAGE)
        self.assertEqual(log.warning.call_args.args, ("technopark reviews %s: no answer to page %s, sort %s", REVIEWS_URL, 2, "useful"))
        tab.close.assert_called_once()

    def test_limit_and_no_reviews(self):
        self.assertEqual(len(self.reviews([LISTING], limit=1)[0].splitlines()), 4)
        empty = {"productV2": {"id": "500", "rating": {"average": 0, "total": {"all": 0}}, "reviews": {"total": 0, "list": {"data": []}}}}
        self.assertEqual(self.reviews([empty])[0], "Технопарк · товар 500: рейтинг —, отзывов 0\n"
                                                   "страница 1 из 1 (по 10), сортировка useful; фото в отзывах сайт не отдаёт; счёт и список — по всем вариантам товара (столбец «другой вариант»)\n"
                                                   + REVIEWS_HEAD + "(отзывов нет)")

    def test_blocked(self):
        got, _, tab, log = self.reviews([COUNT, {"events": {}}])
        self.assertEqual(got, technopark.BLOCKED)
        self.assertEqual(log.warning.call_args.args, ("technopark reviews %s: no reviews answer", REVIEWS_URL))
        tab.close.assert_called_once()

    def test_bad_arguments(self):
        self.assertEqual(technopark.reviews("наушники"), technopark.NO_SLUG)
        self.assertEqual(technopark.reviews(CARD_URL, sort="low"), "sort: одно из useful, new")
        self.assertEqual(technopark.reviews(CARD_URL, with_media=True),
                         "Технопарк не отбирает отзывы с фото и не отдаёт их фото: повтори без with_media")

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = MagicMock()
        with patch.object(technopark, "tab_for", return_value=tab), patch.object(technopark, "capture", side_effect=pace.Refused("⏸")):
            self.assertRaises(pace.Refused, technopark.reviews, CARD_URL, page=2)
        tab.close.assert_called_once()


class TechnoparkHelperTests(unittest.TestCase):
    def test_slug_from_a_link_or_an_address(self):
        for s, slug in (("https://www.technopark.ru/naushniki-a1-500/otzyvy/?x=1", "naushniki-a1-500"),
                        ("technopark.ru/naushniki-a1-500", "naushniki-a1-500"), ("/kabel-usb-c/", "kabel-usb-c"),
                        (" kabel-usb-c ", "kabel-usb-c"), ("http://technopark.ru/naushniki-a1-500#reviews", "naushniki-a1-500")):
            self.assertEqual(technopark._slug(s), slug)
        for s in ("наушники", "123456", 123456, "https://www.technopark.ru/search/?q=x", "", "https://www.technopark.ru/",
                  "https://www.citilink.ru/product/kabel-1/", "sony"):
            self.assertIsNone(technopark._slug(s))

    def test_prices_as_the_site_shows_them(self):
        """The page shows marketing, else default, else old; crossed out old, else default."""
        self.assertEqual(technopark._prices({"default": 9000, "old": 12000}), (9000, 12000))
        self.assertEqual(technopark._prices({"default": 900, "marketing": 800}), (800, 900))
        self.assertEqual(technopark._prices({"default": 900, "marketing": None, "old": None}), (900, None))
        self.assertEqual(technopark._prices({"old": 500}), (500, None))
        self.assertEqual(technopark._prices(None), (None, None))

    def test_price_line(self):
        self.assertEqual(technopark._price({"default": 9000, "old": 12000}), "цена: 9000 ₽ (было 12000, −25%)")
        self.assertEqual(technopark._price({"default": 1000, "old": 1999}), "цена: 1000 ₽ (было 1999, −50%)")
        self.assertEqual(technopark._price({"default": 900}), "цена: 900 ₽")
        self.assertEqual(technopark._price({}), "цена: не указана")

    def test_text_from_markup(self):
        self.assertEqual(technopark._text("<style>\na{b:c}\n</style><p>Звук&nbsp;<b>чистый</b></p>\n<SCRIPT>y()</SCRIPT> "),
                         "Звук чистый")
        self.assertEqual(technopark._text(None), "")


if __name__ == "__main__":
    unittest.main()
