"""Wildberries: search, item and reviews from the JSON the page captured (capture, tab_for)
and the public CDN/feedback JSON (_get), all patched; the cart with what its syncs and the page script
would send.  Today is fixed to 29 Oct 2026, the clock to 1700000000.
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
                  patch.object(wb, "time", types.SimpleNamespace(time=lambda: 1700000000.9)),
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


P1 = {"id": 101, "name": "Кабель A", "sizes": [{"name": "0", "origName": "0", "optionId": 555}]}
P2 = {"id": 102, "name": "Футболка B", "sizes": [{"name": "S", "origName": "42", "optionId": 556}, {"name": "M", "optionId": 557}]}
L1 = {"cod1S": 101, "id": 555, "quantity": 2, "priceWithCouponAndSpp": 299, "price": 350, "includeInOrder": True,
      "brandName": "Бренд", "goodsName": "Кабель A", "sizeName": "0", "canBeOrdered": True}
L2 = {"cod1S": 102, "id": 556, "quantity": 1, "price": 199, "goodsName": "Футболка B", "sizeName": "42", "canBeOrdered": False}
L3 = {"cod1S": 102, "id": 557, "quantity": 1, "priceWithCouponAndSpp": 0, "price": 189, "includeInOrder": False,
      "goodsName": "Футболка B", "sizeName": ""}
R1 = "101\t555\t2\t299\t✓\tБренд\tКабель A\t\t"
R2 = "102\t556\t1\t199\t\t\tФутболка B\t42\tнельзя заказать"
R3 = "102\t557\t1\t189\t\t\tФутболка B\t\t"
CART_HEAD = ("корзина Wildberries (✓ — выбрано к оформлению; цена за штуку без WB Кошелька)\n"
             "артикул\tchrt\tшт\tцена ₽\t✓\tбренд\tназвание\tразмер\tзаметки\n")
# the shape of the page's own cart sync (values made up); every WB page load sends one
SYNC_URL = "https://www.wildberries.ru/__internal/cart-storage-api/api/basket/sync?device_id=d1&ts=1761000000123"
VIEW = (wb.CART, {"cart": ["basket/data_v2"]}, SYNC_URL.replace("ts=1761000000123", "ts=0"), SYNC_URL)


def view(*lines):
    return {"cart": {"value": {"data": {"basket": {"basketItems": list(lines)}}}}}


def detail(nm, *products):
    return ([{"detail": {"products": list(products)}}],
            [(f"https://www.wildberries.ru/catalog/{nm}/detail.aspx", {"detail": ["/cards/v4/detail", f"nm={nm}"]})])


def sync(body):
    return wb.CART, {"sync": ["basket/sync"]}, (SYNC_URL, body), SYNC_URL


def add(chrt, nm, quantity):
    return {"chrt_id": chrt, "quantity": quantity, "cod_1s": nm, "client_ts": 1700000000, "op_type": 1, "target_url": "",
            "meta_json": None, "analytics_json": None}


class CartTests(WbTest):
    def answers(self, *answers):
        self.capture.side_effect = list(answers)

    def sent(self):
        """Every capture() as (url, patterns), and with a rewrite also what the page's first and second sync go out as."""
        out = []
        for c in self.capture.call_args_list:
            tab, site, url, patterns = c.args
            self.assertEqual((tab, site), (self.tab, "wb"))
            self.assertLessEqual(set(c.kwargs), {"rewrite"})
            if "rewrite" not in c.kwargs:
                out.append((url, patterns))
                continue
            glob, fn = c.kwargs["rewrite"]
            self.assertEqual(glob, wb.SYNC)
            self.assertTrue(fnmatch.fnmatchcase(SYNC_URL, glob))
            out.append((url, patterns, fn(SYNC_URL), fn(SYNC_URL)))
        return out

    def assertClosed(self):
        self.tab_for.assert_called_once_with("wildberries.ru")
        self.tab.close.assert_called_once()


class CartViewTests(CartTests):
    def test_lines_as_the_server_has_them(self):
        self.answers(view(L1, L2, L3))
        self.assertEqual(wb.cart(), CART_HEAD + f"{R1}\n{R2}\n{R3}")
        self.assertEqual(self.sent(), [VIEW])
        self.assertClosed()

    def test_ts_is_zeroed_wherever_it_stands(self):
        self.answers(view())
        wb.cart()
        fn = self.capture.call_args.kwargs["rewrite"][1]
        self.assertEqual(fn("https://x/basket/sync?ts=17&ts2=5"), "https://x/basket/sync?ts=0&ts2=5")
        self.assertEqual(fn("https://x/basket/sync?ts=18"), "https://x/basket/sync?ts=18")

    def test_empty(self):
        self.answers(view(), {"cart": {}}, {"cart": {"value": {"data": None}}})
        self.assertEqual([wb.cart() for _ in range(3)], ["корзина Wildberries пуста"] * 3)

    def test_no_answer(self):
        self.answers({})
        self.assertEqual(wb.cart(), wb.BLOCKED)
        self.assertClosed()

    def test_line_without_size_name(self):
        self.answers(view({"cod1S": 1, "id": 2, "quantity": 1, "price": 5}, {"cod1S": 3, "id": 4, "quantity": 1, "price": 6, "sizeName": 0}))
        self.assertEqual(wb.cart(), CART_HEAD + "1\t2\t1\t5\t\t\t\t\t\n3\t4\t1\t6\t\t\t\t\t")


class AddToCartTests(CartTests):
    def add(self, answers, calls, *args, **kw):
        products, opened = answers
        self.answers(*products, *calls)
        got = wb.add_to_cart(*args, **kw)
        self.assertClosed()
        return got, opened

    def test_adds_the_size_asked_for(self):
        got, opened = self.add(detail(102, P2), [view(L1), {"sync": {"state": 0}}, view(L1, L3)],
                               "https://www.wildberries.ru/catalog/102/detail.aspx", size=" m ", quantity=2)
        self.assertEqual(got, "добавлено: Футболка B, 2 шт\n" + CART_HEAD + f"{R1}\n{R3}")
        self.assertEqual(self.sent(), opened + [VIEW, sync('[{"chrt_id": 557, "quantity": 2, "cod_1s": 102, "client_ts": 1700000000, '
                                                           '"op_type": 1, "target_url": "", "meta_json": null, "analytics_json": null}]'), VIEW])
        self.log.warning.assert_not_called()

    def test_size_by_its_original_name(self):
        got, _ = self.add(detail(102, P2), [view(), {"sync": {"state": 0}}, view(L2)], "102", size=42, quantity="3")
        self.assertEqual(got, "добавлено: Футболка B, 3 шт\n" + CART_HEAD + R2)
        self.assertEqual(self.sent()[2], sync('[{"chrt_id": 556, "quantity": 3, "cod_1s": 102, "client_ts": 1700000000, '
                                              '"op_type": 1, "target_url": "", "meta_json": null, "analytics_json": null}]'))

    def test_one_size_needs_no_size_and_the_site_did_not_confirm(self):
        got, _ = self.add(detail(101, P1), [view(L2), {"sync": {"state": 0}}, view(L2)], "101")
        self.assertEqual(got, "⚠️ Wildberries не подтвердил добавление: Кабель A, 1 шт\n" + CART_HEAD + R2)
        self.assertEqual(self.sent()[2], sync('[{"chrt_id": 555, "quantity": 1, "cod_1s": 101, "client_ts": 1700000000, '
                                              '"op_type": 1, "target_url": "", "meta_json": null, "analytics_json": null}]'))

    def test_already_in_the_cart(self):
        got, opened = self.add(detail(101, P1), [view(L1, L2)], "101", quantity=5)
        self.assertEqual(got, "уже в корзине, ничего не менял\n" + CART_HEAD + f"{R1}\n{R2}")
        self.assertEqual(self.sent(), opened + [VIEW])

    def test_sizes_to_choose_from(self):
        got, opened = self.add(detail(102, P2), [], "102")
        self.assertEqual(got, "у товара несколько размеров, укажи size: 42, M")
        self.assertEqual(self.sent(), opened)

    def test_unknown_size(self):
        got, opened = self.add(detail(102, P2), [], "102", size="XL")
        self.assertEqual(got, "нет размера «XL»; есть: 42, M")
        self.assertEqual(self.sent(), opened)

    def test_no_product_in_the_answer(self):
        for answer in ([{}], [{"detail": None}], detail(101, P2)[0]):
            with self.subTest(answer):
                self.tab_for.reset_mock()
                self.tab.close.reset_mock()
                got, _ = self.add((answer, []), [], "101")
                self.assertEqual(got, wb.BLOCKED)

    def test_cart_not_answered(self):
        got, opened = self.add(detail(101, P1), [{}], "101")
        self.assertEqual(got, wb.BLOCKED)
        self.assertEqual(self.sent(), opened + [VIEW])

    def test_sync_refused_or_unanswered(self):
        for answer, r in (({"sync": {"state": 1}}, {"state": 1}), ({}, None)):
            with self.subTest(answer):
                self.tab_for.reset_mock()
                self.tab.close.reset_mock()
                self.log.reset_mock()
                got, _ = self.add(detail(101, P1), [view(), answer], "101")
                self.assertEqual(got, wb.BLOCKED)
                self.log.warning.assert_called_once_with("wb cart sync %s: %s", [add(555, 101, 1)], r)

    def test_cart_after_the_sync_not_answered(self):
        got, _ = self.add(detail(101, P1), [view(), {"sync": {"state": 0}}, {}], "101")
        self.assertEqual(got, wb.BLOCKED)
        self.assertEqual(len(self.sent()), 4)

    def test_not_an_id(self):
        self.assertEqual(wb.add_to_cart("abc"), "нужен артикул WB или ссылка на товар")
        self.tab_for.assert_not_called()

    def test_product_without_sizes(self):
        for p, size in (({"id": 101, "name": "x", "sizes": []}, None), ({"id": 101, "name": "x"}, None),
                        ({"id": 101, "name": "x", "sizes": []}, "M")):
            with self.subTest(p=p, size=size):
                self.capture.reset_mock()
                self.tab_for.reset_mock()
                self.tab.close.reset_mock()
                got, opened = self.add(detail(101, p), [], "101", size=size)
                self.assertEqual(got, "у товара нет размеров, которые можно заказать: в корзину не положить")
                self.assertEqual(self.sent(), opened)

    def test_quantity_below_one(self):
        self.assertEqual([wb.add_to_cart("101", quantity=q) for q in (0, -2, "0")], ["quantity: целое число от 1"] * 3)
        self.tab_for.assert_not_called()


class RemoveFromCartTests(CartTests):
    def remove(self, key, *answers, found=True):
        self.answers(*answers)
        self.tab.js.return_value = found
        got = wb.remove_from_cart(key)
        self.assertClosed()
        return got

    def test_removes_the_line_of_an_article(self):
        got = self.remove("https://www.wildberries.ru/catalog/101/detail.aspx", view(L1, L2), view(L2))
        self.assertEqual(got, "удалено: Кабель A\n" + CART_HEAD + R2)
        self.tab.js.assert_called_once_with(wb.REMOVE_JS + "(555, 2)")
        self.assertEqual(self.sent(), [VIEW, VIEW])

    def test_one_size_by_chrt(self):
        got = self.remove("557", view(L1, L2, L3), view(L1, L2))
        self.assertEqual(got, "удалено: Футболка B\n" + CART_HEAD + f"{R1}\n{R2}")
        self.tab.js.assert_called_once_with(wb.REMOVE_JS + "(557, 1)")

    def test_site_did_not_confirm(self):
        got = self.remove("101", view(L1), view(L1))
        self.assertEqual(got, "⚠️ Wildberries не подтвердил удаление: Кабель A\n" + CART_HEAD + R1)

    def test_several_sizes_of_the_article(self):
        got = self.remove("102", view(L1, L2, L3))
        self.assertEqual(got, "в корзине несколько размеров этого товара, укажи chrt\n" + CART_HEAD + f"{R2}\n{R3}")
        self.tab.js.assert_not_called()

    def test_not_in_the_cart(self):
        got = self.remove("999", view(L1))
        self.assertEqual(got, "такого товара в корзине нет\n" + CART_HEAD + R1)
        self.tab.js.assert_not_called()

    def test_no_cart_in_the_browser(self):
        got = self.remove("101", view(L1), found=False)
        self.assertEqual(got, "⚠️ не нашёл корзину Wildberries в браузере, ничего не удалил")
        self.assertEqual(self.sent(), [VIEW])

    def test_cart_not_answered_before(self):
        self.assertEqual(self.remove("101", {}), wb.BLOCKED)
        self.tab.js.assert_not_called()

    def test_cart_not_answered_after(self):
        self.assertEqual(self.remove("101", view(L1), {}), wb.BLOCKED)
        self.tab.js.assert_called_once_with(wb.REMOVE_JS + "(555, 2)")

    def test_not_an_id(self):
        self.assertEqual(wb.remove_from_cart("abc"), "нужен артикул WB, chrt из wb_cart или ссылка на товар")
        self.tab_for.assert_not_called()


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
