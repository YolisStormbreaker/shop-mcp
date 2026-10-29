"""Wildberries read paths: search, item and reviews from the JSON the page captured (capture, tab_for)
and the public CDN/feedback JSON (_get), all patched.  Today is fixed to 29 Oct 2026.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_wb"""
import datetime
import fnmatch
import types
import unittest
from unittest.mock import MagicMock, patch

import wb


class Today(datetime.date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 29)


def price(rub, basic):
    return [{"price": {"product": rub * 100, "basic": basic * 100}}]


A = {"id": 101, "root": 5001, "name": "Кабель A", "brand": "Бренд", "reviewRating": 4.8, "feedbacks": 120, "supplier": "Продавец 1",
     "supplierRating": 4.1, "totalQuantity": 5, "time1": 10, "time2": 30, "pics": 12, "sizes": price(299, 599)}
B = {"id": 102, "name": "Кабель B", "totalQuantity": 0, "sizes": price(199, 199)}
C = {"id": 103, "name": "Кабель C", "brand": "X", "supplier": "S", "totalQuantity": 3, "sizes": []}
D = {"id": 104, "name": "Кабель D", "totalQuantity": 1, "time1": 0}

HEAD = ("товар: https://www.wildberries.ru/catalog/<id>/detail.aspx; «привезут» — оценка по сроку доставки на адрес из профиля\n"
        "цена без скидки WB Кошелька: сайт показывает цену с ней, она на несколько процентов ниже\n"
        "#\tid\tцена ₽\tбез скидки\tназвание\tбренд\tрейтинг\tотзывов\tпродавец\tпривезут\n")
SEARCH = "https://www.wildberries.ru/catalog/0/search.aspx?search=usb+c"
# the shape of the catalog request the search page sent on 2026-10-29 (values made up)
CATALOG = ("https://www.wildberries.ru/__internal/u-search/exactmatch/ru/common/v18/search?ab_daily_autotest=x&appType=1&curr=rub"
           "&dest=-1&hide_vflags=0&inheritFilters=false&lang=ru&locale=ru&query=usb%20c&resultset=catalog&sort=popular&spp=30"
           "&suppressSpellcheck=false")

BASE = "https://basket-01.wbbasket.ru/vol1/part101"
DESC = "Описание. " * 300
CARD = {"grouped_options": [{"options": [{"name": "Цвет", "value": "белый"}, {"name": "Длина", "value": "1 м"}]}, {"options": []}, {}],
        "description": DESC}
WEEK, JUL5 = 7 * 86400, 1783252800   # 5 Jul 2026 12:00 UTC: the same date in any Russian time zone
HISTORY = [{"dt": JUL5 + k * WEEK, "price": {"RUB": rub * 100}} for k, rub in enumerate((200, 150, 180, 250, 220, 210, 240, 230, 260))]
SELLER = {"valuation": 4.7, "saleItemQuantity": 1500, "registrationDate": "2019-05-01T00:00:00"}

F1 = {"createdDate": "2026-09-01T10:00:00Z", "productValuation": 5, "votes": {"pluses": 3, "minuses": 1}, "color": "белый", "size": "0",
      "wbUserDetails": {"name": "Покупатель"}, "pros": "прочный", "cons": "короткий", "text": "в целом  хорошо\nспасибо",
      "answer": {"text": "Спасибо!"}, "photos": [{"key": "5/aaa"}, {"key": "bad"}], "video": {"id": "3/vvv", "durationSec": 12}}
F2 = {"createdDate": "2026-10-01T10:00:00Z", "productValuation": 1, "size": "M", "text": "плохо", "photos": []}
F3 = {"createdDate": "2026-08-01T10:00:00Z", "productValuation": 4, "votes": {"pluses": 3, "minuses": 1}, "text": "норм", "video": {"id": "x"}}
FEEDBACKS = {"valuation": "4.6", "feedbackCount": 10, "feedbackCountWithText": 5, "feedbackCountWithPhoto": 2, "feedbackCountWithVideo": 1,
             "valuationDistributionPercent": {"1": 5, "5": 80, "4": 15}, "feedbacks": [F1, F2, F3]}
ROW1 = ("2026-09-01\t5\t+3/−1\tбелый\tПокупатель\t+ прочный | − короткий | в целом хорошо спасибо | ответ продавца: Спасибо!\t"
        "https://feedback-05.wbbasket.ru/aaa/fs.webp видео 12 с: https://videofeedback03.wbbasket.ru/vvv/index.m3u8 "
        "превью https://videofeedback03.wbbasket.ru/vvv/preview.webp")
ROW2 = "2026-10-01\t1\t+0/−0\tM\t\tплохо\t"
ROW3 = "2026-08-01\t4\t+3/−1\t\t\tнорм\t"
COLUMNS = "дата\t★\tполезно +/−\tцвет, размер\tавтор\tтекст\tфото (shop_images), видео"


class WbTest(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(wb, "datetime", types.SimpleNamespace(date=Today, timedelta=datetime.timedelta)),
                  patch.dict(wb._imt, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.log = self.patch("log")
        self.tab = MagicMock()
        self.tab_for = self.patch("tab_for", return_value=self.tab)
        self.capture = self.patch("capture")
        self.get = self.patch("_get")

    def patch(self, name, **kw):
        p = patch.object(wb, name, **kw)
        self.addCleanup(p.stop)
        return p.start()

    def captured(self, d):
        self.capture.return_value = d


class SearchTests(WbTest):
    def search(self, products, total=None, **kw):
        self.captured({"s": {"products": products, "total": total}})
        return wb.search("usb c", **kw)

    def test_rows_of_the_first_page(self):
        got = self.search([A, B, C, D], 250, limit=3)
        self.assertEqual(got, f"Wildberries · 250 найдено · страница 1 из 3 (по 100) · {SEARCH}&sort=popular\n" + HEAD +
                         "1\t101\t299\t599\tКабель A\tБренд\t4.8\t120\tПродавец 1\t≈30 окт\n"
                         "2\t102\t199\t199\tКабель B\t\t\t\t\tнет в наличии\n"
                         "3\t103\t0\t0\tКабель C\tX\t\t\tS\t")
        self.tab_for.assert_called_once_with("wildberries.ru")
        self.capture.assert_called_once_with(self.tab, "wb", f"{SEARCH}&sort=popular", {"s": ["/exactmatch/", "resultset=catalog"]},
                                             rewrite=None)
        self.tab.close.assert_called_once()

    def test_price_sort_is_redone_by_price(self):
        got = self.search([A, B, C, D], sort="priceup", price_min=100)
        self.assertEqual(got, f"Wildberries · 4 найдено · страница 1 из 1 (по 100) · {SEARCH}&sort=priceup&priceU=10000%3B1000000000\n" + HEAD +
                         "1\t103\t0\t0\tКабель C\tX\t\t\tS\t\n"
                         "2\t104\t0\t0\tКабель D\t\t\t\t\t\n"
                         "3\t102\t199\t199\tКабель B\t\t\t\t\tнет в наличии\n"
                         "4\t101\t299\t599\tКабель A\tБренд\t4.8\t120\tПродавец 1\t≈30 окт")
        got = self.search([C, A, D, B], sort="pricedown")
        self.assertEqual([row.split("\t")[1] for row in got.split("\n")[4:]], ["101", "102", "103", "104"])

    def test_page_n_rewrites_the_pages_own_request(self):
        got = self.search([], 250, page=2, price_max=500)
        self.assertTrue(got.startswith(f"Wildberries · 250 найдено · страница 2 из 3 (по 100) · {SEARCH}&sort=popular&priceU=0%3B50000\n"))
        glob, fn = self.capture.call_args.kwargs["rewrite"]
        self.assertTrue(fnmatch.fnmatchcase(CATALOG, glob))
        self.assertEqual(fn("https://x/search?query=a&page=1&resultset=catalog"), "https://x/search?query=a&page=2&resultset=catalog")
        self.assertEqual(fn("https://x/search?query=a&resultset=catalog"), "https://x/search?query=a&resultset=catalog&page=2")

    def test_nothing_found(self):
        self.assertEqual(self.search([]), f"Wildberries · 0 найдено · страница 1 из 1 (по 100) · {SEARCH}&sort=popular\n" + HEAD + "(пусто)")

    def test_no_answer_from_the_site(self):
        self.captured({})
        self.assertEqual(wb.search("usb c"), wb.BLOCKED)
        self.log.warning.assert_called_once_with("wb search %s: no catalog response", f"{SEARCH}&sort=popular")
        self.tab.close.assert_called_once()

    def test_unknown_sort(self):
        self.assertEqual(wb.search("usb c", sort="cheap"), "sort: одно из popular, rate, priceup, pricedown, newly, benefit")
        self.tab_for.assert_not_called()


class ItemTests(WbTest):
    def item(self, product, seller=None, base=BASE, card=CARD, history=HISTORY, id_or_url="101", **kw):
        detail = {"detail": {"products": [{"id": 999}, product]}}
        self.captured({**detail, "seller": seller} if seller is not None else detail)
        self.tab.js.return_value = base
        self.get.side_effect = lambda url: card if url.endswith("/card.json") else history
        return wb.item(id_or_url, **kw)

    def test_full_card(self):
        got = self.item(A, SELLER, id_or_url="https://www.wildberries.ru/catalog/101/detail.aspx?size=1")
        photos = " ".join(f"{BASE}/101/images/big/{i}.webp" for i in range(1, 11))
        self.assertEqual(got, "\n".join([
            "Кабель A — 299 ₽ без WB Кошелька (с ним на сайте на несколько % ниже), до скидок 599 ₽ (−50%)",
            "https://www.wildberries.ru/catalog/101/detail.aspx",
            "бренд: Бренд · рейтинг 4.8 (120 отзывов) · в наличии: 5 шт",
            "привезут ≈30 окт (оценка по сроку доставки на адрес из профиля)",
            "продавец: Продавец 1, рейтинг 4.7, продаж 1500, на WB с 2019",
            "история цены, ₽ по неделям: мин 150 (12 июл 26), макс 260 (30 авг 26); последние: 12 июл 26 150, 19 июл 26 180, "
            "26 июл 26 250, 2 авг 26 220, 9 авг 26 210, 16 авг 26 240, 23 авг 26 230, 30 авг 26 260",
            "фото (shop_images): " + photos,
            "отзывы: wb_reviews",
            "характеристики: Цвет: белый; Длина: 1 м",
            "\n" + DESC[:2500]]))
        self.capture.assert_called_once_with(self.tab, "wb", "https://www.wildberries.ru/catalog/101/detail.aspx",
                                             {"detail": ["/cards/v4/detail", "nm=101"], "seller": ["/api/v1/suppliers/"]},
                                             optional=("seller",))
        self.assertEqual([c.args[0] for c in self.get.call_args_list],
                         [f"{BASE}/101/info/ru/card.json", f"{BASE}/101/info/price-history.json"])
        self.tab.close.assert_called_once()
        self.assertEqual(wb._imt, {"101": 5001})

    def test_full_description(self):
        self.assertTrue(self.item(A, SELLER, full=True).endswith("; Длина: 1 м\n\n" + DESC))

    def test_out_of_stock_without_cdn_folder(self):
        got = self.item({"id": 101, "name": "Кабель B", "supplier": "S2", "sizes": [{"price": {}}]}, base="")
        self.assertEqual(got, "Кабель B — цены нет: товара нет в наличии (последние цены — в истории ниже)\n"
                              "https://www.wildberries.ru/catalog/101/detail.aspx\n"
                              "бренд: — · рейтинг — (0 отзывов) · нет в наличии\n"
                              "продавец: S2, рейтинг —\n"
                              "отзывы: wb_reviews\n\n")
        self.get.assert_not_called()
        self.assertEqual(wb._imt, {})

    def test_card_and_history_unavailable(self):
        def fail(url):
            raise OSError("404")
        p = {"id": 101, "name": "Кабель C", "supplier": "S3", "supplierRating": 4.1, "totalQuantity": 2, "sizes": price(100, 100)}
        self.captured({"detail": {"products": [p]}, "seller": {"valuation": 0}})
        self.tab.js.return_value = BASE
        self.get.side_effect = fail
        self.assertEqual(wb.item("101"), "Кабель C — 100 ₽ без WB Кошелька (с ним на сайте на несколько % ниже)\n"
                                         "https://www.wildberries.ru/catalog/101/detail.aspx\n"
                                         "бренд: — · рейтинг — (0 отзывов) · в наличии: 2 шт\n"
                                         "продавец: S3, рейтинг 4.1\n"
                                         "фото (shop_images): \n"
                                         "отзывы: wb_reviews\n\n")
        self.assertEqual(self.log.warning.call_args.args[:2], ("wb item %s: card.json: %s", "101"))

    def test_empty_price_history(self):
        self.assertNotIn("история цены", self.item(A, SELLER, history=[]))

    def test_no_product_in_the_answer(self):
        self.captured({"detail": {"products": [{"id": 999}]}})
        self.assertEqual(wb.item("101"), wb.BLOCKED)
        self.log.warning.assert_called_once_with("wb item %s: no detail response, got %s", "101", ["detail"])

    def test_not_an_id(self):
        self.assertEqual(wb.item("кабель"), "нужен артикул WB или ссылка вида https://www.wildberries.ru/catalog/<id>/detail.aspx")
        self.tab_for.assert_not_called()


class ReviewsTests(WbTest):
    def reviews(self, d=FEEDBACKS, **kw):
        wb._imt["101"] = 5001
        self.get.side_effect = lambda url: {"https://feedback-bt.wildberries.ru/feedback/api/v2/host?imt=5001": ["https://fb.test"],
                                            "https://fb.test/feedbacks/v2/5001": d}[url]
        return wb.reviews("101", **kw)

    def head(self, shown, page=1, pages=1, limit=20, sort="useful"):
        return ("Wildberries · артикул 101 (карточка 5001): рейтинг 4.6, отзывов 10 (с текстом 5, с фото 2, с видео 1) · 5★ 80% 4★ 15% 1★ 5%\n"
                f"WB отдаёт до ~1000 отзывов с текстом, сортировка и страницы — по ним: {shown}, страница {page} из {pages} по {limit}, "
                f"сортировка {sort}. Отзывы на все цвета и размеры карточки.\n" + COLUMNS + "\n")

    def test_most_useful_first(self):
        self.assertEqual(self.reviews(), self.head(3) + "\n".join([ROW1, ROW3, ROW2]))
        self.capture.assert_not_called()

    def test_sorts(self):
        self.assertEqual(self.reviews(sort="new"), self.head(3, sort="new") + "\n".join([ROW2, ROW1, ROW3]))
        self.assertEqual(self.reviews(sort="low"), self.head(3, sort="low") + "\n".join([ROW2, ROW3, ROW1]))

    def test_page_of_the_highest(self):
        self.assertEqual(self.reviews(sort="high", page=2, limit=1), self.head(3, 2, 3, 1, "high") + ROW3)

    def test_with_media_only(self):
        self.assertEqual(self.reviews(with_media=True),
                         self.head("2 с фото или видео") + "\n".join([ROW1, ROW3]))

    def test_no_reviews(self):
        self.assertEqual(self.reviews({}), "Wildberries · артикул 101 (карточка 5001): рейтинг —, отзывов 0 "
                                           "(с текстом 0, с фото 0, с видео 0) · \n"
                                           "WB отдаёт до ~1000 отзывов с текстом, сортировка и страницы — по ним: 0, страница 1 из 1 по 20, "
                                           "сортировка useful. Отзывы на все цвета и размеры карточки.\n" + COLUMNS + "\n(отзывов нет)")

    def test_card_id_is_taken_from_the_product_page_once(self):
        self.captured({"detail": {"products": [A]}})
        self.tab.js.return_value = ""
        self.get.side_effect = lambda url: ["https://fb.test"] if "host" in url else {}
        self.assertTrue(wb.reviews("https://www.wildberries.ru/catalog/101/detail.aspx").startswith("Wildberries · артикул 101 (карточка 5001)"))
        self.capture.assert_called_once_with(self.tab, "wb", "https://www.wildberries.ru/catalog/101/detail.aspx",
                                             {"detail": ["/cards/v4/detail", "nm=101"]}, optional=())
        wb.reviews("101")
        self.capture.assert_called_once()

    def test_no_card_id(self):
        self.captured({})
        self.tab.js.return_value = ""
        self.assertEqual(wb.reviews("101"), wb.BLOCKED)
        self.get.assert_not_called()

    def test_bad_arguments(self):
        self.assertEqual(wb.reviews("101", sort="best"), "sort: одно из useful, new, high, low")
        self.assertEqual(wb.reviews("x"), "нужен артикул WB или ссылка вида https://www.wildberries.ru/catalog/<id>/detail.aspx")
        self.capture.assert_not_called()


class HelperTests(unittest.TestCase):
    def test_media_urls(self):
        self.assertEqual(wb._media({"photos": [{"key": "12/p1"}, {"key": None}, {}], "video": {"id": "7/v"}}), [
            "https://feedback-12.wbbasket.ru/p1/fs.webp",
            "видео ? с: https://videofeedback07.wbbasket.ru/v/index.m3u8 превью https://videofeedback07.wbbasket.ru/v/preview.webp"])
        self.assertEqual(wb._media({}), [])

    def test_article_from_id_or_url(self):
        self.assertEqual([wb._nm(x) for x in ("https://www.wildberries.ru/catalog/123/detail.aspx", " 456 ", 789, "abc", "12a")],
                         ["123", "456", "789", None, None])


if __name__ == "__main__":
    unittest.main()
