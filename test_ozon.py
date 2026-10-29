"""Ozon read paths: the site's composer JSON (widgetStates) -> the text the tools return.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_ozon"""
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
        ozon._last_call = last_call
        with patch.object(ozon.time, "sleep") as sleep, patch.object(ozon, "dump", return_value="logs/bodies/x.html"), \
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
        ozon._last_call = 0.0
        with patch.object(ozon.time, "sleep"):
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


if __name__ == "__main__":
    unittest.main()
