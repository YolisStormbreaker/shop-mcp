"""Ozon: the site's composer JSON (widgetStates) -> the text the tools return, and what the cart tools send.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_ozon"""
import calendar
import json
import time
import unittest
from unittest.mock import MagicMock, patch

import ozon


def answer(body, status=200):
    return {"s": status, "b": body if isinstance(body, str) else json.dumps(body)}


class FetchTests(unittest.TestCase):
    def fetch(self, *answers, last_call=0.0):
        tab = MagicMock()
        tab.js.side_effect = list(answers)
        with patch.object(ozon, "_last_call", last_call), patch.object(ozon.time, "sleep") as sleep, \
                patch.object(ozon, "dump", return_value="logs/bodies/x.html"), \
                patch.object(ozon, "log") as log:
            try:
                return ozon._page(tab, "/search/?text=usb c"), tab, sleep, log
            except RuntimeError as e:
                return e, tab, sleep, log

    def test_json_answer_through_the_page_api(self):
        got, tab, sleep, _ = self.fetch(answer({"widgetStates": {}}))
        self.assertEqual(got, {"widgetStates": {}})
        self.assertEqual(tab.js.call_args.args[0],
                         'fetch("/api/entrypoint-api.bx/page/json/v2?url=%2Fsearch%2F%3Ftext%3Dusb%20c", '
                         '{"method": "GET", "credentials": "include"}).then(async r => ({s: r.status, b: await r.text()}))')
        sleep.assert_not_called()

    def test_waits_out_the_gap_since_the_last_call(self):
        _, _, sleep, _ = self.fetch(answer({}), last_call=time.time())
        self.assertGreater(sleep.call_args.args[0], 1.0)
        self.assertLessEqual(sleep.call_args.args[0], 1.5)

    def test_post_sends_json_body(self):
        tab = MagicMock()
        tab.js.return_value = answer({"ok": 1})
        with patch.object(ozon, "_last_call", 0.0), patch.object(ozon.time, "sleep"):
            self.assertEqual(ozon._fetch(tab, "/api/x", "POST", {"pageType": "pdp"}), {"ok": 1})
        self.assertIn('{"method": "POST", "credentials": "include", "headers": {"Content-Type": "application/json"}, '
                      '"body": "{\\"pageType\\": \\"pdp\\"}"}', tab.js.call_args.args[0])

    def test_non_json_reloads_the_tab_and_retries(self):
        got, tab, sleep, log = self.fetch(answer("<html>antibot</html>", 403), answer({"widgetStates": {"a": "{}"}}))
        self.assertEqual(got, {"widgetStates": {"a": "{}"}})
        tab.goto.assert_called_once_with("https://www.ozon.ru/", "ozon", wait_js="document.readyState === 'complete'")
        self.assertEqual(sleep.call_args_list[0].args, (3,))        # then the retry waits out its own gap
        self.assertEqual(log.warning.call_args.args[3:], (403, "logs/bodies/x.html"))

    def test_non_json_twice_raises_with_the_saved_body(self):
        got, tab, _, log = self.fetch(answer("<html>1</html>", 403), answer("<html>2</html>", 403))
        self.assertIsInstance(got, RuntimeError)
        self.assertEqual(str(got), "Ozon ответил 403 не-JSON и после перезагрузки вкладки "
                                   "(вероятно, проверка на бота: shop-chrome show). Ответ целиком: logs/bodies/x.html")
        self.assertEqual(tab.goto.call_count, 1)
        log.error.assert_called_once()


def page(widgets=None, next_page=None):
    """A composer page: every widget state is a JSON string under its id."""
    p = {"widgetStates": {k: json.dumps(v) for k, v in (widgets or {}).items()}}
    if next_page:
        p["nextPage"] = next_page
    return p


def tile(sku, title, price, old=None, labels=(), delivery=None):
    main = [{"type": "textDS", "textDS": {"text": "Оригинал"}},           # a badge before the name
            {"type": "textDS", "id": "name", "textDS": {"text": title}},
            {"type": "textDS", "textDS": {"text": "Осталось 3 шт"}},
            {"type": "priceV2", "priceV2": {"price": [{"text": f"{price} ₽", "textStyle": "PRICE"}]
                                            + ([{"text": f"{old} ₽", "textStyle": "ORIGINAL_PRICE"}] if old else [])
                                            + [{"text": "−56%", "textStyle": "DISCOUNT"}]}},
            {"type": "labelListV2", "labelListV2": {"items": [{"type": "text", "text": {"text": x}} for x in labels]
                                                    + [{"type": "icon", "image": "star"}]}}]
    it = {"sku": sku, "mainState": main, "action": {"link": f"/product/kabel-{sku}/?advert=xyz"}}
    if delivery:
        # what _texts skips (action, common, trackingInfo) holds dates too; a nested text node and a list do not stop it
        it["multiButton"] = {"common": {"text": "Сегодня"}, "trackingInfo": {"title": "Завтра"},
                             "ozonButton": {"items": [{"title": "В корзину", "action": {"text": "Сегодня"}},
                                                      {"text": {"text": delivery}}, {"text": "Завтра"}]}}
    return it


PAGE1 = page({"tileGrid2-1": {"items": [
    tile(1002731400, "hoco Кабель USB Type-A/USB Type-C, 1 м", "149", "340", ["4.9", "336 096 отзывов"], "Послезавтра"),
    tile(None, "Кабель без sku", "10"),
    tile(1393105636, "Кабель " + "очень длинный " * 10, "991", labels=["Хит продаж"])]},
    "infiniteVirtualPaginator-2": {"nextPage": "/search/?text=usb&page=2"}})
PAGE2 = page({"tileGrid2-1": {"items": [tile(1002731400, "дубль", "1"), tile(3070669820, "Кабель type c", "190", "650",
                                                                              ["4.8", "70 485 отзывов"], "29 октября")]},
              "paginator-3": {"nextPage": ""}}, next_page="/search/?text=usb&page=3")
PAGE3 = page({"tileGrid2-1": {"items": []}})
HEAD = "товар: https://www.ozon.ru/product/<sku>\n#\tsku\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tпривезут"


class SearchTests(unittest.TestCase):
    def search(self, pages, query="кабель usb-c", **kw):
        tab = MagicMock()
        with patch.object(ozon, "_tab", return_value=tab), patch.object(ozon, "_page", side_effect=pages) as get:
            out = ozon.search(query, **kw)
        tab.close.assert_called_once()
        return out, [c.args[1] for c in get.call_args_list]

    def test_rows_across_pages(self):
        out, urls = self.search([PAGE1, PAGE2, PAGE3])
        self.assertEqual(urls, ["/search/?text=%D0%BA%D0%B0%D0%B1%D0%B5%D0%BB%D1%8C+usb-c&sorting=score",
                                "/search/?text=usb&page=2", "/search/?text=usb&page=3"])
        self.assertEqual(out, "Ozon · https://www.ozon.ru/search/?text=%D0%BA%D0%B0%D0%B1%D0%B5%D0%BB%D1%8C+usb-c&sorting=score\n"
                         + HEAD + "\n"
                         "1\t1002731400\t149\t340\thoco Кабель USB Type-A/USB Type-C, 1 м\t4.9\t336096\tПослезавтра\n"
                         "2\t1393105636\t991\t\t" + ("Кабель " + "очень длинный " * 10)[:110] + "\t\t\t\n"
                         "3\t3070669820\t190\t650\tКабель type c\t4.8\t70485\t29 октября")

    def test_price_range_and_sort_go_into_the_url(self):
        out, urls = self.search([PAGE3], "usb", price_max=500, sort="price")
        self.assertEqual(urls, ["/search/?text=usb&sorting=price&currency_price=0.000%3B500.000"])
        self.assertTrue(out.startswith("Ozon · https://www.ozon.ru/search/?text=usb&sorting=price&currency_price=0.000%3B500.000\n"))
        self.assertTrue(out.endswith(HEAD + "\n(пусто)"))
        self.assertEqual(self.search([PAGE3], "usb", price_min=100)[1],
                         ["/search/?text=usb&sorting=score&currency_price=100.000%3B100000000.000"])

    def test_limit_stops_reading_pages(self):
        out, urls = self.search([PAGE1, PAGE2], limit=1)
        self.assertEqual(len(urls), 1)
        self.assertEqual(out.splitlines()[-1], "1\t1002731400\t149\t340\thoco Кабель USB Type-A/USB Type-C, 1 м\t4.9\t336096\tПослезавтра")

    def test_reads_at_most_eight_pages(self):
        pages = [page({"tileGrid2-1": {"items": [tile(n, f"товар {n}", "1")]}}, next_page=f"/p{n + 1}") for n in range(1, 11)]
        out, urls = self.search(pages, limit=100)
        self.assertEqual(len(urls), 8)
        self.assertEqual(out.splitlines()[-1], "8\t8\t1\t\tтовар 8\t\t\t")

    def test_unknown_sort(self):
        with self.assertRaisesRegex(ValueError, "sort: одно из"):
            ozon.search("usb", sort="cheap")


SKU = 1002731400
GALLERY = [f"https://ir.ozone.ru/s3/multimedia-1-a/{n}.jpg" for n in range(1, 12)]
CARD = page({
    "webProductHeading-1": {"title": "Кабель Тест USB-C, 1 м"},
    "webPrice-2": {"cardPrice": "149 ₽", "price": "165 ₽", "originalPrice": "340 ₽", "pricePerUnit": "149 ₽",
                   "measurePerUnit": "за 1 шт", "isAvailable": False},
    "webSale-3": {"offer": {"isAvailable": True}},
    "webReviewProductScore-4": {"totalScore": 4.9, "reviewsCount": 336097},
    "webCurrentSeller-5": {"sellerCell": {"centerBlock": {"title": {"text": "Тест-Шоп"}},
                                          "rightBlock": {"action": {"params": {"sellerId": "123456"}}}}},
    "paginator-6": {"nextPage": f"/product/{SKU}/?layout_container=pdpPage2column&layout_page_index=2&sh=k1"},
    "webPriceDecreasedCompact-7": {"title": "Стало дешевле"},
    "webGallery-8": {"images": [{"src": u} for u in GALLERY] + [{"alt": "без картинки"}]}})
CARD2 = page({
    "webDescription-1": {
        "richAnnotation": "<p>Кабель &quot;Тест&quot; для зарядки.</p><br/><ul><li>Длина 1&nbsp;м</li><li>Ток 3 А &amp; быстро</li></ul>",
        "richAnnotationJson": {"content": [{"img": {"src": "https://ir.ozone.ru/s3/rich-1/9.jpg"}},
                                           {"img": {"src": GALLERY[0]}},                       # already among the photos
                                           {"img": {"src": "https://cdn1.ozone.ru/s3/rich-2/10.png"}},
                                           {"img": {"src": "https://cdn1.ozone.ru/s3/rich-2/10.png"}}]},
        "characteristics": [{"title": "Комплектация", "content": "кабель\nинструкция\n"}, {"title": "Пусто", "content": ""}]},
    "webCharacteristics-2": {"characteristics": [
        {"title": "Общие", "short": [{"key": "Type", "name": "Тип", "values": [{"text": "Кабель"}]},
                                     {"key": "Sku", "name": "Артикул", "values": [{"text": str(SKU)}]}],
         "long": [{"key": "Color", "name": "Цвет", "values": [{"text": "Черный"}, {"text": "Белый"}]}]}]}})
DATES = {"buttons": [{"text": "В корзину"}, {"text": "Доставим послезавтра"}]}
SELLER = page({"cellList-1": {"title": "О магазине"},
               "textBlock-2": {"body": [{"text": "ООО «Тест»<br>ОГРН 1234567890123<br>Работает с Ozon с 2020"}]},
               "textBlock-3": {"body": [{"text": "другое<br>юрлицо"}]}})
LOWER = page({"webPriceDecreasedFullView-1": {"lines": [
    {"textRs": [{"type": "text", "content": "Цена сейчас"}, {"type": "icon", "content": "arrow"}, {"type": "text", "content": "165 ₽"}],
     "iconText": "12%"},
    {"textRs": [{"type": "text", "content": "Средняя за месяц"}, {"type": "text", "content": "188 ₽"}]}]}})


class ItemTests(unittest.TestCase):
    def item(self, pages, dates=None, sku_or_url=SKU, **kw):
        tab = MagicMock()
        with patch.object(ozon, "_tab", return_value=tab), patch.object(ozon, "_page", side_effect=lambda t, url: pages[url]), \
                patch.object(ozon, "_fetch", return_value=dates or {}) as fetch:
            out = ozon.item(sku_or_url, **kw)
        tab.close.assert_called_once()
        self.assertEqual(fetch.call_args.args[1:], (f"/api/composer-api.bx/_action/pdpGetButtonTexts?product_id={ozon._sku(sku_or_url)}",
                                                    "POST", {"pageType": "pdp"}))
        return out

    def test_full_card(self):
        out = self.item({f"/product/{SKU}/": CARD, f"/product/{SKU}/?layout_container=pdpPage2column&layout_page_index=2&sh=k1": CARD2,
                         "/modal/shop-in-shop-info?seller_id=123456": SELLER,
                         f"/modal/web_pdp_lower_price?product_id={SKU}": LOWER}, DATES)
        self.assertEqual(out, "\n".join([
            "Кабель Тест USB-C, 1 м", f"https://www.ozon.ru/product/{SKU}/",
            "цена: 149 ₽ с картой Ozon, 165 ₽ без неё, без скидки 340 ₽ (−51%), 149 ₽ за 1 шт",
            "в наличии: да",
            "привезут: Доставим послезавтра",
            "рейтинг: 4.9, отзывов 336097",
            "продавец: Тест-Шоп · ООО «Тест» · ОГРН 1234567890123 · Работает с Ozon с 2020",
            "стало дешевле: Цена сейчас 165 ₽ (−12%); Средняя за месяц 188 ₽ — "
            "Ozon сравнивает цену без банков-партнёров со средней за прошлый месяц",
            "фото (shop_images): " + " ".join(GALLERY[:10]),
            "картинки из описания (shop_images; на них часто комплектация и размеры): "
            "https://ir.ozone.ru/s3/rich-1/9.jpg https://cdn1.ozone.ru/s3/rich-2/10.png",
            "отзывы с фото и видео: ozon_reviews",
            "характеристики:\n  Тип: Кабель\n  Цвет: Черный, Белый",
            'описание:\nКабель "Тест" для зарядки.\nДлина 1 м\nТок 3 А & быстро',
            "Комплектация:\n  кабель\n  инструкция"]))

    def test_bare_card(self):
        out = self.item({"/product/42424242/": page(),
                         "/product/42424242/?layout_container=pdpPage2column&layout_page_index=2": page()}, sku_or_url="42424242")
        self.assertEqual(out, "?\nhttps://www.ozon.ru/product/42424242/\n"
                              "цена: ? с картой Ozon, ? без неё\nв наличии: ⛔ нет\nпривезут: ?\nрейтинг: ?, отзывов ?\n"
                              "продавец: ? (юрлицо не нашёл)\nотзывы с фото и видео: ozon_reviews\nхарактеристики:\n  (нет)")

    def test_foreign_seller_from_a_product_url(self):
        card = page({"webPrice-1": {"price": "500 ₽", "originalPrice": "400 ₽", "isAvailable": True},
                     "webCurrentSeller-2": {"sellerCell": {"centerBlock": {"title": {"text": "Test Store"}}}, "sellerId": "777"}})
        seller = page({"textBlock-1": {"text": "Shenzhen Test Technology Co., Ltd.<br>Китай, Шэньчжэнь"}})
        out = self.item({"/product/123456789/": card, "/product/123456789/?layout_container=pdpPage2column&layout_page_index=2": page(),
                         "/modal/shop-in-shop-info?seller_id=777": seller},
                        sku_or_url="https://www.ozon.ru/product/kabel-test-123456789/?at=abc").splitlines()
        self.assertEqual(out[2:4], ["цена: 500 ₽ с картой Ozon, 500 ₽ без неё", "в наличии: да"])
        self.assertEqual(out[6], "продавец: Test Store · Shenzhen Test Technology Co., Ltd. · Китай, Шэньчжэнь · ⚠️ из-за рубежа")

    def test_description_is_cut_unless_full(self):
        pages = {"/product/42424242/": page(),
                 "/product/42424242/?layout_container=pdpPage2column&layout_page_index=2":
                     page({"webDescription-1": {"richAnnotation": "а" * 2600 + "КОНЕЦ"}})}
        self.assertEqual(self.item(pages, sku_or_url="42424242").split("описание:\n")[1], "а" * 2500)
        self.assertEqual(self.item(pages, sku_or_url="42424242", full=True).split("описание:\n")[1], "а" * 2600 + "КОНЕЦ")

    def test_no_sku_in_the_link(self):
        with self.assertRaisesRegex(ValueError, "не нашёл sku"):
            ozon.item("https://www.ozon.ru/category/kabeli/")


def review(comment, score=5, item_id=111, day=1, **content):
    """A review as the list widget gives it; created at noon UTC so the date is the same in any time zone."""
    return {"content": {"comment": comment, "score": score, **content}, "itemId": item_id,
            "createdAt": calendar.timegm((2026, 6, day, 12, 0, 0))}


def reviews_page(reviews, paging=None, score=None, next_page=None, products=None):
    w = {"webListReviews-1": {"reviews": reviews, "paging": paging or {}, "products": products or {}}}
    if score:
        w["webReviewProductScore-2"] = score
    return page(w, next_page)


RICH = review("в целом  хорошо\nберу ещё", 4, positive="быстро заряжает", negative="коротковат",
              photos=[{"url": "https://ir.ozone.ru/r/1.jpg"}, {"id": "без url"}],
              videos=[{"url": "https://v.ozone.ru/v/1.mp4", "duration": "0:12", "previewUrl": "https://ir.ozone.ru/r/p.jpg"},
                      {"duration": "0:05"}])
RICH.update(usefulness={"useful": 3, "unuseful": 1}, author={"firstName": "Анна"})
RICH_ROW = ("2026-06-01\t4\t+3/−1\tчерный, 1 м\tАнна\t+ быстро заряжает | − коротковат | в целом хорошо беру ещё\t"
            "https://ir.ozone.ru/r/1.jpg видео 0:12: https://v.ozone.ru/v/1.mp4 превью https://ir.ozone.ru/r/p.jpg")
PLAIN = {"content": {"comment": "норм", "score": 5}, "itemId": 222, "publishedAt": calendar.timegm((2026, 6, 2, 12, 0, 0))}
VIDEO_ONLY = review("видео", videos=[{"url": "https://v.ozone.ru/v/2.mp4"}], day=3)
PRODUCTS = {"111": {"variants": [{"value": "черный"}, {"value": "1 м"}]}}
SCORE = {"totalScore": 4.9, "reviewsCount": 336097, "score": [{"title": "5 звёзд", "value": 312142}, {"title": "4 звезды", "value": 18612}]}
REVIEWS_HEAD = "дата\t★\tполезно +/−\tвариант\tавтор\tтекст\tфото (shop_images), видео"
BASE = f"/product/{SKU}/reviews/?sort=usefulness_desc&reviewsVariantMode=2"


class ReviewsTests(unittest.TestCase):
    def reviews(self, pages, **kw):
        tab = MagicMock()
        with patch.object(ozon, "_tab", return_value=tab), patch.object(ozon, "_page", side_effect=pages) as get:
            out = ozon.reviews(SKU, **kw)
        tab.close.assert_called_once()
        return out, [c.args[1] for c in get.call_args_list]

    def test_one_page_of_all_variants(self):
        out, urls = self.reviews([reviews_page([RICH, PLAIN], {"total": 95}, SCORE, products=PRODUCTS)])
        self.assertEqual(urls, [BASE])
        self.assertEqual(out, f"Ozon · sku {SKU}: рейтинг 4.9, отзывов 336097 · 5 звёзд: 312142 4 звезды: 18612\n"
                              "все варианты товара: 95 отзывов, страница 1 из 4 (по 30), сортировка useful\n"
                              f"{REVIEWS_HEAD}\n{RICH_ROW}\n2026-06-02\t5\t+0/−0\t\t\tнорм\t")

    def test_this_variant_with_media_lowest_first(self):
        out, urls = self.reviews([reviews_page([RICH, PLAIN, VIDEO_ONLY], {"total": 3}, products=PRODUCTS)],
                                 sort="low", with_media=True, this_variant=True)
        self.assertEqual(urls, [f"/product/{SKU}/reviews/?sort=score_asc&reviewsVariantMode=1"])
        self.assertEqual(out.splitlines(), [
            f"Ozon · sku {SKU}: рейтинг ?, отзывов ? · ",
            "только этот вариант: 3 отзывов, страница 1 из 1 (по 30), сортировка low; только с фото или видео — из этой страницы",
            REVIEWS_HEAD, RICH_ROW, "2026-06-03\t5\t+0/−0\tчерный, 1 м\t\tвидео\tвидео : https://v.ozone.ru/v/2.mp4 превью "])

    def test_later_page_uses_the_page_key_from_page_one(self):
        first = reviews_page([PLAIN], {"total": 95, "nextPage": f"/product/{SKU}/reviews/?page=2&page_key=K2xyz&sort=usefulness_desc"})
        out, urls = self.reviews([first, reviews_page([RICH], products=PRODUCTS)], page=3)
        self.assertEqual(urls, [BASE, BASE + "&page=3&page_key=K2xyz"])
        self.assertEqual(out.splitlines()[1:], ["все варианты товара: 95 отзывов, страница 3 из 4 (по 30), сортировка useful",
                                                REVIEWS_HEAD, RICH_ROW])

    def test_later_page_without_a_page_key(self):
        out, urls = self.reviews([reviews_page([PLAIN], score={"reviewsCount": 40})], page=2)
        self.assertEqual(urls, [BASE])
        self.assertEqual(out.splitlines()[1:], ["все варианты товара: 40 отзывов, страница 2 из 2 (по 30), сортировка useful",
                                                REVIEWS_HEAD, "(отзывов нет)"])

    def test_query_matches_the_variant_until_the_last_page(self):
        out, urls = self.reviews([reviews_page([RICH, PLAIN], products=PRODUCTS, next_page="/p2"),
                                  reviews_page([review("не тот", item_id=222)])], query="черный")
        self.assertEqual(urls, [BASE, "/p2"])
        self.assertEqual(out.splitlines()[1:], ["все варианты товара: 0 отзывов, страницы 1–2: «черный» нашлось в 1 из 3, сортировка useful",
                                                REVIEWS_HEAD, RICH_ROW])

    def test_query_stops_at_30_rows(self):
        out, urls = self.reviews([reviews_page([review("ок")] * 30, next_page="/p2")], query="ок")
        self.assertEqual(len(urls), 1)
        self.assertIn("страница 1: «ок» нашлось в 30 из 30", out)

    def test_query_reads_at_most_ten_pages(self):
        out, urls = self.reviews([reviews_page([review("ок")], next_page=f"/p{n}") for n in range(2, 14)], query="ок")
        self.assertEqual(len(urls), ozon.QUERY_PAGES)
        self.assertIn("страницы 1–10: «ок» нашлось в 10 из 10", out)

    def test_later_page_failing_reaches_the_caller(self):
        tab = MagicMock()
        with patch.object(ozon, "_tab", return_value=tab), \
                patch.object(ozon, "_page", side_effect=[reviews_page([PLAIN], next_page="/p2"), RuntimeError("Ozon ответил 403")]):
            with self.assertRaisesRegex(RuntimeError, "403"):
                ozon.reviews(SKU, query="ок")
        tab.close.assert_called_once()

    def test_unknown_sort(self):
        with patch.object(ozon, "_tab") as tab:
            self.assertEqual(ozon.reviews(SKU, sort="new"),
                             "sort: одно из useful, high, low (сортировки по дате на Ozon нет: useful — «новые и полезные»)")
        tab.assert_not_called()


def cart_line(titles, prices, qty=None, post_body=None):
    """One cart line: the texts of its title and price columns, its quantity control and its delete button's request."""
    controls = {"quantity": {"current": qty}} if qty is not None else {}
    if post_body is not None:
        controls["deleteButton"] = {"common": {"action": {"params": {"postBody": post_body}}}}
    return {"product": {"titleColumn": [{"type": "textAtom", "textAtom": {"text": t}} for t in titles],
                        "priceColumn": [{"type": "priceV2", "priceV2": {"price": [{"text": t} for t in prices]}}]},
            "controls": controls}


def deletes(*items):
    """The delete button's postBody: the sku list is JSON inside JSON."""
    return json.dumps({"name": "deleteItems", "params": json.dumps({"items": list(items)})})


LONG = "Кабель " + "очень длинный " * 10
CART = page({
    "cartSplit-1": {"header": {"title": "Доставка Ozon", "subtitle": {"text": "завтра"}}, "cartItems": [
        cart_line(["Оригинал", "Осталось 15 шт.", "hoco Кабель USB Type-A/USB Type-C, 1 м", "Цвет: черный"],
                  ["−56%", "149 ₽", "340 ₽"], 2, deletes(str(SKU))),
        cart_line([LONG], ["1 234 ₽"], 1, deletes())]},              # no sku in the button's request
    "cartSplit-2": {"cartItems": [
        cart_line(["Короткое"], ["нет в наличии"], post_body="не JSON"),       # no quantity, title or price
        cart_line(["Продавец Тест-Шоп из Китая"], ["990 ₽"], 1)]},            # no delete button
    "total-3": {"summary": {"header": {"info": "4 товара · 1,2 кг"}, "footer": {"price": "2 373 ₽"}}}})
CART_ROWS = ("sku\tшт\tцена\tназвание\tгруппа\n"
             f"{SKU}\t2\t149 ₽\thoco Кабель USB Type-A/USB Type-C, 1 м\tДоставка Ozon\n"
             f"\t1\t1 234 ₽\t{LONG[:110]}\tДоставка Ozon\n"
             "\t\t\t\t\n"
             "\t1\t990 ₽\tПродавец Тест-Шоп из Китая\t")


class CartTests(unittest.TestCase):
    def call(self, fn, *args, answer=None):
        tab = MagicMock()
        with patch.object(ozon, "_tab", return_value=tab), patch.object(ozon, "_page", return_value=answer) as get, \
                patch.object(ozon, "_fetch", return_value=answer) as fetch:
            out = fn(*args)
        tab.close.assert_called_once()
        return out, tab, get, fetch

    def test_cart_lines_and_total(self):
        out, tab, get, fetch = self.call(ozon.cart, answer=CART)
        get.assert_called_once_with(tab, "/cart")
        fetch.assert_not_called()
        self.assertEqual(out, "корзина Ozon: 4 товара · 1,2 кг, итого 2 373 ₽\n" + CART_ROWS)

    def test_nothing_selected_has_no_total(self):
        out, *_ = self.call(ozon.cart, answer=page({"cartSplit-1": {"cartItems": []}, "total-2": {"summary": {"footer": {}}}}))
        self.assertEqual(out, "корзина Ozon, итого не посчитан: ни один товар не отмечен к оформлению\n"
                              "sku\tшт\tцена\tназвание\tгруппа\n")

    def test_no_total_widget(self):
        out, *_ = self.call(ozon.cart, answer=page({"cartSplit-1": {"cartItems": [cart_line([LONG], ["1 ₽"], 3)]}}))
        self.assertEqual(out.splitlines(), ["корзина Ozon, итого не посчитан: ни один товар не отмечен к оформлению",
                                            "sku\tшт\tцена\tназвание\tгруппа", f"\t3\t1 ₽\t{LONG[:110]}\t"])

    def test_empty_cart(self):
        out, *_ = self.call(ozon.cart, answer=page({"emptyCart-1": {}, "total-2": {"summary": {"footer": {"price": "0 ₽"}}}}))
        self.assertEqual(out, "корзина Ozon пуста")

    def test_add_by_link(self):
        out, tab, get, fetch = self.call(ozon.add_to_cart, f"https://www.ozon.ru/product/kabel-{SKU}/?at=x",
                                         answer={"success": True, "cart": {"cartItems": [{"id": 111, "qty": 1}, {"id": SKU, "qty": 3}]}})
        fetch.assert_called_once_with(tab, "/api/composer-api.bx/_action/addToCart", "POST", [{"id": SKU, "quantity": 1}])
        get.assert_not_called()
        self.assertEqual(out, f"добавлено: sku {SKU}, в корзине этого товара 3 шт.")

    def test_add_without_the_line_in_the_answer(self):
        out, tab, _, fetch = self.call(ozon.add_to_cart, str(SKU), 2, answer={"success": True})
        self.assertEqual(fetch.call_args.args[3], [{"id": SKU, "quantity": 2}])
        self.assertEqual(out, f"добавлено: sku {SKU}, в корзине этого товара ? шт.")

    def test_site_refuses_to_add(self):
        out, *_ = self.call(ozon.add_to_cart, SKU, answer={"success": False, "message": "Товар закончился", "details": "д" * 300})
        self.assertEqual(out, f"Ozon не добавил {SKU}: " + '{"success": false, "message": "Товар закончился", "details": "' + "д" * 238)

    def test_remove_sends_the_sku_and_shows_the_cart_left(self):
        left = page({"cartSplit-1": {"cartItems": [cart_line([LONG], ["1 ₽"], 1, deletes("42424242"))]},
                     "total-2": {"summary": {"header": {"info": "1 товар"}, "footer": {"price": "1 ₽"}}}})
        out, tab, get, fetch = self.call(ozon.remove_from_cart, f"https://www.ozon.ru/product/kabel-{SKU}/", answer=left)
        fetch.assert_called_once_with(tab, "/api/entrypoint-api.bx/page/json/v2?url=%2Fcart", "POST",
                                      {"name": "deleteItems", "params": '{"items": ["1002731400"]}'})
        get.assert_not_called()
        self.assertEqual(out, "удалено. корзина Ozon: 1 товар, итого 1 ₽\nsku\tшт\tцена\tназвание\tгруппа\n"
                              f"42424242\t1\t1 ₽\t{LONG[:110]}\t")

    def test_remove_the_last_line(self):
        out, *_ = self.call(ozon.remove_from_cart, SKU, answer=page({"emptyCart-1": {}}))
        self.assertEqual(out, "удалено. корзина Ozon пуста")

    def test_no_sku_in_the_link(self):
        with patch.object(ozon, "_tab") as tab:
            for fn in (ozon.add_to_cart, ozon.remove_from_cart):
                with self.assertRaisesRegex(ValueError, "не нашёл sku"):
                    fn("https://www.ozon.ru/category/kabeli/")
        tab.assert_not_called()


if __name__ == "__main__":
    unittest.main()
