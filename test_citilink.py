"""Ситилинк: the site's JSON (search, product card, delivery, reviews) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_citilink"""
import unittest
from unittest.mock import MagicMock, patch

import citilink
import pace


def sources(name):
    return {"sources": [{"url": f"https://cdn/{name}/55.jpg", "size": "SM"}, {"url": f"https://cdn/{name}/250.jpg", "size": "MD"},
                        {"url": f"https://cdn/{name}/1200.jpg", "size": "XL"}]}


DAYS = {"self": {"availabilityByDays": [{"deliveryTime": "2026-11-16T00:00:00.000Z", "storeCount": 40},
                                        {"deliveryTime": "2026-11-14T00:00:00.000Z", "storeCount": 1}]}}
HEADPHONES = {"id": "100", "name": "Наушники A1 [a1/b]", "slug": "naushniki-a1", "isAvailable": True,
              "price": {"current": "5000", "old": "6000", "club": "4800", "discount": {"percent": 17}},
              "rating": "4.8", "counters": {"opinions": 6, "reviews": 1}, "isCrossBorder": True,
              "labels": [{"type": "INSTALLMENT", "title": "Рассрочка 0-0-6"}, {"type": "DISCOUNT", "title": "Уценка"}],
              "stock": {"countInStores": "9", "maxCountInStock": ">50"}, "delivery": DAYS}
CABLE = {"id": "M200", "name": "Кабель", "slug": "kabel", "isAvailable": True, "price": {"current": "300", "old": "", "club": ""},
         "rating": "0.0", "counters": {"opinions": 0}, "labels": [], "stock": {"countInStores": "0"}, "delivery": {"self": None}}
GONE = {"id": "300", "name": "Старый", "slug": "staryi", "isAvailable": False, "price": {"current": "100", "old": "0"}}


def record(products, offset, total=922):
    return {"data": {"fullSearchFilter": {"record": {"products": products, "partialPageInfo": {"limit": 12, "offset": offset},
                                                     "pageInfo": {"perPage": 36, "page": 1, "totalItems": total}}, "error": None}}}


QUERY = "https://www.citilink.ru/search/?text=%D0%BD%D0%B0%D1%83%D1%88%D0%BD%D0%B8%D0%BA%D0%B8"
SEARCH_HEAD = ("ссылки относительно https://www.citilink.ru; цены и наличие — для города из профиля на сайте\n"
               "#\tкод\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tналичие\tпометки\tссылка\n")


class CitilinkSearchTests(unittest.TestCase):
    def search(self, answers, **kw):
        tab = MagicMock()
        got = {f"g{i}": a for i, a in enumerate(answers)}
        with patch.object(citilink, "tab_for", return_value=tab), patch.object(citilink, "capture", return_value=got) as capture, \
                patch.object(citilink, "log") as log:
            return citilink.search("наушники", **kw), capture, tab, log

    def test_both_parts_of_the_page_in_their_order(self):
        got, capture, tab, _ = self.search([{"data": {"notification": None}}, record([CABLE, GONE], 12), record([HEADPHONES], 0), ["x"]])
        self.assertEqual(got, f"Ситилинк · 922 найдено · страница 1 (по 36) · {QUERY}\n" + SEARCH_HEAD +
                         "1\t100\t5000\t6000\tНаушники A1 [a1/b]\t4.8\t6\tв магазинах сегодня: 9, самовывоз с 2026-11-14\t"
                         "Уценка, клубная цена 4800, из-за рубежа\t/product/naushniki-a1-100/\n"
                         "2\tM200\t300\t\tКабель\t\t\t\t\t/product/kabel-M200/\n"
                         "3\t300\t100\t\tСтарый\t\t\tнет в наличии\t\t/product/staryi-300/")
        args, kw = capture.call_args
        self.assertEqual(args[:3], (tab, "citilink", QUERY))
        self.assertEqual(set(map(tuple, args[3].values())), {("/graphql/",)})   # every answer comes to one address
        self.assertEqual(len(args[3]) - len(kw["optional"]), 10)
        self.assertEqual(kw["optional"], list(args[3])[:len(kw["optional"])])  # capture fills the last names first
        tab.close.assert_called_once()

    def test_sort_price_and_page_go_into_the_url(self):
        got, capture, _, _ = self.search([record([], 0, 0)], price_max=1000, sort="price_asc", page=3, limit=5)
        url = QUERY + "&sorting=price_asc&r=price_filter_group_id%3A0-1000&p=3"
        self.assertEqual(capture.call_args.args[2], url)
        self.assertEqual(got, f"Ситилинк · 0 найдено · страница 3 (по 36) · {url}\n" + SEARCH_HEAD + "(пусто)")
        self.assertIn("&sorting=opinions_desc&r=price_filter_group_id%3A500-10000000",
                      self.search([record([], 0)], price_min=500, sort="reviews")[1].call_args.args[2])

    def test_a_missed_part_of_the_page_is_said(self):
        got = self.search([record([HEADPHONES], 0, 40)])[0]
        self.assertEqual(got.splitlines()[1], "⚠️ пришла не вся страница: 1 карточек из 36, повтори позже")
        self.assertNotIn("⚠️", self.search([record([HEADPHONES], 0, 1)])[0])
        # page 2 starts after card 36: one card of 40 is short of the 4 it has, one of 37 is the whole page
        self.assertIn("⚠️", self.search([record([HEADPHONES], 0, 40)], page=2)[0])
        self.assertNotIn("⚠️", self.search([record([HEADPHONES], 0, 37)], page=2)[0])

    def test_an_answer_without_its_part_counts_as_the_first(self):
        first = record([CABLE], 0)
        del first["data"]["fullSearchFilter"]["record"]["partialPageInfo"]
        got = self.search([first, record([HEADPHONES], 0)])[0]
        self.assertLess(got.index("\tM200\t"), got.index("\t100\t"))
        first = record([CABLE], 0)
        first["data"]["fullSearchFilter"]["record"]["partialPageInfo"]["offset"] = None      # a null offset sorts, as the first
        got = self.search([first, record([HEADPHONES], 0)])[0]
        self.assertLess(got.index("\tM200\t"), got.index("\t100\t"))

    def test_limit(self):
        self.assertEqual(len(self.search([record([HEADPHONES, CABLE, GONE], 0, 3)], limit=2)[0].splitlines()), 5)

    def test_unknown_sort(self):
        self.assertEqual(citilink.search("наушники", sort="cheap"),
                         "sort: одно из relevance, price_asc, price_desc, discount, rating, reviews")

    def test_blocked(self):
        got, _, tab, log = self.search([{"data": {"fullSearchFilter": {"record": None, "error": {"message": "x"}}}}, {"errors": []}])
        self.assertEqual(got, citilink.BLOCKED)
        self.assertEqual(log.warning.call_args.args, ("citilink search %s: no fullSearchFilter answer", QUERY))
        tab.close.assert_called_once()

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = MagicMock()
        with patch.object(citilink, "tab_for", return_value=tab), patch.object(citilink, "capture", side_effect=pace.Refused("⏸")):
            self.assertRaises(pace.Refused, citilink.search, "наушники")
        tab.close.assert_called_once()


DESCRIPTION = "<p>Звук&nbsp;<b>чистый</b>.</p> " + "Долго. " * 500
CARD = {"id": "100", "name": "Наушники A1 [a1/b]", "slug": "naushniki-a1", "isAvailable": True, "maxCountInStock": "18",
        "price": {"current": "5000", "old": "6000", "club": "0", "discount": {"percent": 17}}, "rating": 4.8,
        "counters": {"opinions": 6, "reviews": 0}, "description": DESCRIPTION,
        "properties": [{"name": "Тип", "value": "вкладыши", "measure": ""}, {"name": "Вес", "value": "5", "measure": "г"}],
        "variants": [{"name": "Цвет", "variants": [{"label": "белый", "product": {"id": "100", "isAvailable": True}},
                                                   {"label": "чёрный", "product": {"id": "101", "isAvailable": False}}]}],
        "images": [sources(i) for i in range(12)]}
CARD_DELIVERY = {"data": {"product": {"delivery": {
    **DAYS, "courier": {"variants": [{"deliveryTime": "2026-11-15T00:00:00.000Z", "type": "STANDARD", "price": "1200"},
                                     {"deliveryTime": "2026-11-13T00:00:00.000Z", "type": "EXPRESS", "price": "0"}]}}}}}
CARD_URL = "https://www.citilink.ru/product/naushniki-a1-100/"


class CitilinkItemTests(unittest.TestCase):
    def item(self, card, answers=(), url=CARD_URL + "otzyvy/?utm=x", **kw):
        tab = MagicMock()
        tab.js.return_value = card
        with patch.object(citilink, "tab_for", return_value=tab), \
                patch.object(citilink, "capture", return_value={f"g{i}": a for i, a in enumerate(answers)}) as capture, \
                patch.object(citilink, "log") as log:
            return citilink.item(url, **kw), capture, tab, log

    def test_full_card(self):
        got, capture, tab, _ = self.item(CARD, [{"data": {"viewer": {}}}, CARD_DELIVERY])
        self.assertEqual(got, "Наушники A1 [a1/b]\n" + CARD_URL + "\nкод товара: 100\n"
                              "цена: 5000 ₽ (было 6000, −17%)\n"
                              "наличие: есть, на складе 18\n"
                              "получение: самовывоз — с 2026-11-14; курьер — 2026-11-15, 1200 ₽; курьер — 2026-11-13, бесплатно\n"
                              "рейтинг 4.8, отзывов 6\n"
                              "характеристики: Тип: вкладыши; Вес: 5 г\n"
                              "Цвет: белый (код 100); чёрный (код 101, нет в наличии)\n"
                              "фото (shop_images): " + " ".join(f"https://cdn/{i}/1200.jpg" for i in range(10)) + "\n"
                              "отзывы: citilink_reviews\n\n" + citilink._text(DESCRIPTION)[:2500])
        self.assertEqual(capture.call_args.args[:3], (tab, "citilink", CARD_URL))
        tab.close.assert_called_once()

    def test_full_description(self):
        self.assertTrue(self.item(CARD, full=True)[0].endswith("\n\n" + citilink._text(DESCRIPTION)))

    def test_bare_card_by_its_code(self):
        got, capture, _, _ = self.item({"id": "M200", "name": "Кабель", "slug": "kabel", "price": {"old": ""}}, url=" M200 ")
        self.assertEqual(capture.call_args.args[2], "https://www.citilink.ru/product/M200/")
        self.assertEqual(got, "Кабель\nhttps://www.citilink.ru/product/kabel-M200/\nкод товара: M200\nцена: None ₽\n"
                              "наличие: нет в наличии\nрейтинг —, отзывов 0\nотзывы: citilink_reviews\n\n")

    def test_relative_link(self):
        self.assertEqual(self.item(CARD, url="/product/naushniki-a1-100")[1].call_args.args[2], CARD_URL)

    def test_not_a_link(self):
        self.assertEqual(citilink.item("наушники белые"), "нужна ссылка на товар Ситилинка или его код из citilink_search")

    def test_blocked_or_another_card(self):
        for card in (None, {**CARD, "id": "999"}):
            got, _, tab, log = self.item(card)
            self.assertEqual(got, citilink.BLOCKED)
            self.assertEqual(log.warning.call_args.args, ("citilink item %s: no product card", CARD_URL))
            tab.close.assert_called_once()


def opinion(**kw):
    return {"displayedDate": "2026-05-04T08:00:00.000Z", "rating": 5, "authorNickname": "Покупатель К.", "product": {"id": "100"},
            "voteInfo": {"info": {"counters": {"likes": 3}}}, **kw}


SUMMARY = {"data": {"product": {"opinions": {"payload": {"summary": {"rating": 4.8, "ratingCounters": [
    {"rating": 5, "percentage": 83}, {"rating": 4, "percentage": 17}, {"rating": 1, "percentage": 0}]}, "totalOpinionsForProduct": 6}}}}}
LISTING = {"data": {"product": {"opinions": {"payload": {"items": [
    opinion(pros="удобные", cons="громкость", text="Звук&nbsp;норм", source={"sourceType": "YAMARKET", "description": "Отзыв из открытых источников"}),
    opinion(rating=4, text="", authorNickname=None, voteInfo=None, product={"id": "101", "shortName": "Наушники A1, чёрный"})],
    "totalOpinionsForProduct": 6}, "pageInfo": {"page": 1, "perPage": 5, "totalItems": 6, "totalPages": 2}}}}}
REVIEWS_HEAD = "дата\t★\tполезно\tавтор\tтекст\tисточник\tдругой вариант\n"


class CitilinkReviewsTests(unittest.TestCase):
    def reviews(self, answers, id_or_url="100", **kw):
        tab = MagicMock()
        with patch.object(citilink, "tab_for", return_value=tab), \
                patch.object(citilink, "capture", return_value={f"g{i}": a for i, a in enumerate(answers)}) as capture:
            return citilink.reviews(id_or_url, **kw), capture, tab

    def test_page_with_reviews(self):
        got, capture, tab = self.reviews([SUMMARY, {"data": {"notification": None}}, LISTING])
        self.assertEqual(got, "Ситилинк · товар 100: рейтинг 4.8, отзывов 6 · 5★ 83% 4★ 17%\n"
                              "страница 1 из 2 (по 5), сортировка useful; фото в отзывах сайт не отдаёт\n" + REVIEWS_HEAD +
                              "2026-05-04\t5\t3\tПокупатель К.\t+ удобные | − громкость | Звук норм\tОтзыв из открытых источников\t\n"
                              "2026-05-04\t4\t\t\t\t\tНаушники A1, чёрный")
        self.assertEqual(capture.call_args.args[:3], (tab, "citilink", "https://www.citilink.ru/product/100/otzyvy/"))
        tab.close.assert_called_once()

    def test_sort_and_page_go_into_the_url(self):
        got, capture, _ = self.reviews([LISTING], "https://www.citilink.ru/product/naushniki-a1-100/otzyvy/?page=1",
                                       sort="low", page=2, limit=1)
        self.assertEqual(capture.call_args.args[2], "https://www.citilink.ru/product/naushniki-a1-100/otzyvy/?sort=WORST&page=2")
        self.assertEqual(got.splitlines()[:2], ["Ситилинк · товар 100: рейтинг —, отзывов 6",
                                                "страница 2 из 2 (по 5), сортировка low; фото в отзывах сайт не отдаёт"])
        self.assertEqual(len(got.splitlines()), 4)

    def test_no_reviews_yet(self):
        got = self.reviews([{"data": {"product": {"opinions": {"payload": {"items": [], "totalOpinionsForProduct": 0}, "pageInfo": {}}}}}])[0]
        self.assertEqual(got, "Ситилинк · товар 100: рейтинг —, отзывов 0\n"
                              "страница 1 из 1 (по 5), сортировка useful; фото в отзывах сайт не отдаёт\n" + REVIEWS_HEAD + "(отзывов нет)")

    def test_count_with_the_other_variants(self):
        listing = {"data": {"product": {"opinions": {"payload": {"items": [], "totalOpinionsForProduct": 19},
                                                     "pageInfo": {"totalItems": 62, "totalPages": 13}}}}}
        self.assertEqual(self.reviews([listing])[0].splitlines()[0], "Ситилинк · товар 100: рейтинг —, отзывов 62 (этого варианта 19)")
        own_only = {"data": {"product": {"opinions": {"payload": {"items": [], "totalOpinionsForProduct": 3}, "pageInfo": {}}}}}
        self.assertEqual(self.reviews([own_only])[0].splitlines()[0], "Ситилинк · товар 100: рейтинг —, отзывов 3")

    def test_blocked(self):
        got, _, tab = self.reviews([{"data": {"product": {"opinions": None}}}])
        self.assertEqual(got, citilink.BLOCKED)
        tab.close.assert_called_once()

    def test_bad_arguments(self):
        self.assertEqual(citilink.reviews("наушники"), "нужна ссылка на товар Ситилинка или его код из citilink_search")
        self.assertEqual(citilink.reviews("100", sort="best"), "sort: одно из useful, new, old, high, low")
        self.assertEqual(citilink.reviews("100", with_media=True), "Ситилинк не отбирает отзывы с фото и не отдаёт их фото: повтори без with_media")


class CitilinkHelperTests(unittest.TestCase):
    def test_slug_from_a_link_or_a_code(self):
        for s, slug in (("https://www.citilink.ru/product/naushniki-a1-100/otzyvy/?x=1", "naushniki-a1-100"),
                        ("citilink.ru/product/naushniki-a1-100", "naushniki-a1-100"), ("/product/kabel-M200/", "kabel-M200"),
                        (" 100 ", "100"), (100, "100")):
            self.assertEqual(citilink._slug(s), slug)
        for s in ("наушники", "https://www.citilink.ru/search/?text=x", "", "sony"):   # a code has a digit
            self.assertIsNone(citilink._slug(s))

    def test_rub(self):
        self.assertEqual([citilink._rub(x) for x in ("5000", "", "0", None, 0)], ["5000", "", "", "", ""])

    def test_text_from_markup(self):
        self.assertEqual(citilink._text("<p>Звук&nbsp;<b>чистый</b></p>\n "), "Звук чистый")
        self.assertEqual(citilink._text(None), "")

    def test_photo_takes_the_largest_size(self):
        self.assertEqual(citilink._photos({"citilink": [sources("a"), {"sources": []}, {}]}), ["https://cdn/a/1200.jpg"])
        self.assertEqual(citilink._photos(None), [])
        self.assertEqual(citilink._photos([sources("b")]), ["https://cdn/b/1200.jpg"])   # the card's form


if __name__ == "__main__":
    unittest.main()
