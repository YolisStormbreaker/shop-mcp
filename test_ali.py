"""AliExpress: the site's API JSON and the pages' text -> the text the tools return, and what the cart tools do.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_ali"""
import datetime
import json
import time
import unittest
from unittest.mock import MagicMock, patch

import ali


def answer(body, status=200):
    return {"s": status, "b": body if isinstance(body, str) else json.dumps(body)}


class FetchTests(unittest.TestCase):
    def fetch(self, *answers, last_call=0.0, call=lambda tab: ali._fetch(tab, "/aer-webapi/v1/search", {"page": 1})):
        tab = MagicMock()
        tab.js.side_effect = list(answers)
        with patch.object(ali, "_last_call", last_call), patch.object(ali.time, "sleep") as sleep, \
                patch.object(ali, "dump", return_value="logs/bodies/x.html"), \
                patch.object(ali, "log") as log:
            try:
                return call(tab), tab, sleep, log
            except RuntimeError as e:
                return e, tab, sleep, log

    def test_post_with_json_body(self):
        got, tab, sleep, _ = self.fetch(answer({"data": {}}))
        self.assertEqual(got, {"data": {}})
        self.assertEqual(tab.js.call_args.args[0],
                         'Promise.race([fetch("/aer-webapi/v1/search", {"method": "POST", "credentials": "include", '
                         '"headers": {"Content-Type": "application/json"}, "body": "{\\"page\\": 1}"})'
                         '.then(async r => ({s: r.status, b: await r.text()})), new Promise(res => setTimeout(() => res(null), 25000))])')
        self.assertEqual(tab.js.call_args.kwargs, {"timeout": 40})
        sleep.assert_not_called()

    def test_product_data_is_a_get_without_body(self):
        got, tab, _, _ = self.fetch(answer({"data": {"reviews": 5}}), call=lambda tab: ali._product_data(tab, "1005006043702745"))
        self.assertEqual(got, {"data": {"reviews": 5}})
        self.assertIn('fetch("/aer-jsonapi/v1/bx/pdp/web/productData?productId=1005006043702745&sourceId=0&sku_id=0", '
                      '{"method": "GET", "credentials": "include", "headers": {"Content-Type": "application/json"}})',
                      tab.js.call_args.args[0])

    def test_waits_out_the_gap_since_the_last_call(self):
        _, _, sleep, _ = self.fetch(answer({}), last_call=time.time())
        self.assertGreater(sleep.call_args.args[0], 1.0)
        self.assertLessEqual(sleep.call_args.args[0], 1.5)

    def test_slider_check_holding_the_request(self):
        got, tab, _, _ = self.fetch(None, True)
        self.assertEqual(str(got), "⚠️ AliExpress показал проверку на бота (слайдер) и держит запросы: shop-chrome show, "
                                   "пройти её во вкладке aliexpress.ru, shop-chrome hide")
        self.assertEqual(tab.js.call_args.args[0], "!!document.querySelector('.baxia-dialog-content')")

    def test_no_answer_in_25_seconds(self):
        got, _, _, _ = self.fetch(None, False)
        self.assertEqual(str(got), "AliExpress не ответил за 25 с на /aer-webapi/v1/search")

    def test_non_json_reloads_the_tab_and_retries(self):
        got, tab, sleep, log = self.fetch(answer("<html>antibot</html>", 403), answer({"data": {"ok": 1}}))
        self.assertEqual(got, {"data": {"ok": 1}})
        tab.goto.assert_called_once_with("https://aliexpress.ru/", "ali", wait_js="document.readyState === 'complete'")
        self.assertEqual(sleep.call_args_list[0].args, (3,))        # then the retry waits out its own gap
        self.assertEqual(log.warning.call_args.args[1:], ("POST", "/aer-webapi/v1/search", 403, "logs/bodies/x.html"))

    def test_non_json_twice_raises_with_the_saved_body(self):
        got, tab, _, log = self.fetch(answer("<html>1</html>", 403), answer("<html>2</html>", 403))
        self.assertEqual(str(got), "AliExpress ответил 403 не-JSON и после перезагрузки вкладки "
                                   "(вероятно, проверка на бота: shop-chrome show). Ответ целиком: logs/bodies/x.html")
        self.assertEqual(tab.goto.call_count, 1)
        log.error.assert_called_once()


def by(days):
    return (datetime.date.today() + datetime.timedelta(days=days)).strftime("%d.%m")


def product(pid, title, price, delivery=(), exp=None, sold="950 купили", store="Test Store"):
    """One productsV2 entry: the item sits deep in the tile, the delivery snippet in its layout areas."""
    item = {"properties": {"id": pid, "preselectSkuId": f"12000{pid}"},
            "pdpInfo": {"preloadedData": {"price": {"value": price}, "title": title, "rating": "4.7", "salesCount": sold,
                                          "store": {"name": store}}},
            "trackingInfo": {"utLogMap": [{"exp_attribute": exp}] if exp else []}}
    areas = [{"id": {"name": "priceArea"}, "blocks": [{"text": f"{price} ₽"}]}]
    if delivery:
        areas.append({"id": {"name": "deliverySnippet"}, "blocks": [{"text": t} for t in delivery]})
    return {"type": "product", "widgets": [{"data": {"itemData": item}}], "layoutAreas": areas}


BANNER = {"type": "banner", "widgets": [{"data": {"image": "x.jpg"}}], "layoutAreas": []}
P1 = product("1005008606048009", "Toocki USB Type C Кабель 100 Вт", 209, ["до 14 дней", "бесплатно"])
P2 = product("1005008364835496", "PD 60 Вт USB C кабель " + "длинное название " * 8, 289,
             exp={"snippet_delivery_eta": "11-14", "delivery_price": "20"}, sold="18 906 купили")
P3 = product("1005006043702745", "Кабель Essager", 131, ["Доставка 5 ноября"], exp={"snippet_delivery_eta": "7-9"})
P4 = product("1005009405736390", "Кабель без доставки", 88, exp={"snippet_delivery_eta": "10-12"})
P5 = product("1005001111111111", "Кабель без срока", 99, store="")
SEARCH_HEAD = ("AliExpress · товар: https://aliexpress.ru/item/<id>.html\n"
               "«привезут до» = сегодня + максимальный срок из карточки; точная дата — в ali_item\n"
               "#\tid\tsku\tцена ₽\tназвание\tрейтинг\tкупили\tпривезут до\tдоставка (срок, цена)\tмагазин")


def results(products, pages=2):
    return {"data": {"pagination": {"totalPages": pages}, "productsFeed": {"productsV2": products}}}


class SearchTests(unittest.TestCase):
    def search(self, answers, query="кабель usb-c", **kw):
        tab, sent = MagicMock(), []

        def fetch(_tab, path, body):
            self.assertEqual(path, "/aer-webapi/v1/search")
            sent.append(dict(body))             # search() changes the same dict for the next page
            return answers[len(sent) - 1]
        with patch.object(ali, "_tab", return_value=tab), patch.object(ali, "_fetch", side_effect=fetch):
            out = ali.search(query, **kw)
        tab.close.assert_called_once()
        return out, sent

    def test_rows_across_pages(self):
        out, sent = self.search([results([P1, BANNER, P2]), results([P1, P3, P4, P5])])
        self.assertEqual([b["page"] for b in sent], [1, 2])
        self.assertEqual(sent[0], {"catId": "", "searchInfo": "", "searchText": "кабель usb-c", "page": 1, "storeIds": [],
                                   "pgChildren": [], "aeBrainIds": [], "searchTrigger": "search_bar", "mainFilters": "",
                                   "source": "direct"})
        self.assertEqual(out, SEARCH_HEAD + "\n" + "\n".join([
            f"1\t1005008606048009\t120001005008606048009\t209\tToocki USB Type C Кабель 100 Вт\t4.7\t950\t{by(14)}\t"
            "до 14 дней, бесплатно\tTest Store",
            "2\t1005008364835496\t120001005008364835496\t289\t" + ("PD 60 Вт USB C кабель " + "длинное название " * 8)[:110]
            + f"\t4.7\t18 906\t{by(14)}\t11-14 дн., 20 ₽\tTest Store",
            f"3\t1005006043702745\t120001005006043702745\t131\tКабель Essager\t4.7\t950\t{by(9)}\tДоставка 5 ноября\tTest Store",
            f"4\t1005009405736390\t120001005009405736390\t88\tКабель без доставки\t4.7\t950\t{by(12)}\t10-12 дн., бесплатно\tTest Store",
            "5\t1005001111111111\t120001005001111111111\t99\tКабель без срока\t4.7\t950\t\t\t"]))

    def test_sort_and_price_range_go_into_the_request(self):
        out, sent = self.search([{"data": None}], sort="orders", price_min=100.5, price_max=500)
        self.assertEqual({k: sent[0][k] for k in ("sortType", "minPrice", "maxPrice")},
                         {"sortType": "total_tranpro_desc", "minPrice": 100, "maxPrice": 500})
        self.assertEqual(out, SEARCH_HEAD + "\n(пусто)")
        self.assertNotIn("sortType", self.search([{"data": None}])[1][0])

    def test_limit_stops_reading_pages(self):
        out, sent = self.search([results([P1, P2])], limit=1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(out.splitlines()[3:], [f"1\t1005008606048009\t120001005008606048009\t209\tToocki USB Type C Кабель 100 Вт\t"
                                                f"4.7\t950\t{by(14)}\tдо 14 дней, бесплатно\tTest Store"])

    def test_reads_at_most_five_pages(self):
        out, sent = self.search([results([product(f"10050000000000{n:02}", f"товар {n}", n)], pages=9) for n in range(1, 10)],
                                limit=100)
        self.assertEqual(len(sent), 5)
        self.assertTrue(out.splitlines()[-1].startswith("5\t1005000000000005\t"))

    def test_unknown_sort(self):
        with self.assertRaisesRegex(ValueError, "sort: одно из"):
            ali.search("usb", sort="rating")


ITEM = "1005006043702745"
PHOTOS = [f"https://ae-pic-a1.aliexpress-media.com/kf/S{n}.jpg" for n in range(1, 12)]
DESC_IMGS = [f"https://ae-pic-a1.aliexpress-media.com/kf/D{n}.jpg" for n in range(1, 10)]
PRODUCT_DATA = {"data": {
    "price": {"discount": 51, "formattedActivityPrice": "88–147 ₽", "formattedPrice": "180–300 ₽"},
    "rating": {"middle": 4.8}, "reviews": 1657, "tradeInfo": {"formatTradeCount": "18 906 купили"}, "productInfo": {"brand": "OLOPKY"},
    "gallery": [{"imageUrl": u} for u in PHOTOS] + [{"videoUrl": "https://video.aliexpress-media.com/v1.mp4"}, {"other": 1}],
    "skuInfo": {
        "propertyList": [{"name": "Цвет", "values": [{"id": "200", "name": "as the pictures show "},
                                                     {"id": "201", "name": "black", "displayName": "Черный"}]},
                         {"name": "Длина", "values": [{"id": "300", "name": "1m"}, {"id": "301", "name": "2m", "displayName": "2 м"}]}],
        "priceList": [{"skuId": 12000035460442808, "skuPropIds": "200,300", "activityAmount": {"formatted": "88 ₽"},
                       "amount": {"formatted": "180 ₽"}, "availQuantity": 2480},
                      {"skuId": 12000035597315109, "skuPropIds": "201,301", "amount": {"formatted": "300 ₽"}, "availQuantity": 0},
                      {"skuId": 12000036024713698, "skuPropIds": "200,301", "amount": {"formatted": "147 ₽"}, "availQuantity": 4983},
                      {"skuId": 12000036024713699}]}}}
VARIANT_ROWS = ["  Цвет: as the pictures show; Длина: 1m\t12000035460442808\t88 ₽\t2480",
                "  Цвет: Черный; Длина: 2 м\t12000035597315109\t300 ₽\tнет",
                "  Цвет: as the pictures show; Длина: 2 м\t12000036024713698\t147 ₽\t4983",
                "  \t12000036024713699\t\tнет"]
BODY = "\n".join([
    "PD 60 Вт USB C кабель", "88 ₽", "  ", "Доставка",
    "9–12 ноября в пункт выдачи", "20 ₽",
    "15–19 ноября почтой", "Бесплатно",
    "9–12 ноября в пункт выдачи", "20 ₽",                          # the same option shown twice
    "3 ноября курьером", "Бесплатная доставка от 1 000 ₽",   # not a price line
    "12 ноября — строка, в которой слишком много текста для строки со сроком доставки", "20 ₽",
    "В корзину", "1 декабря"])


def pdp(body=BODY, title="PD 60 Вт USB C кабель", price="88 ₽", props=("Цвет: as the pictures show", None, "Длина: 1m"),
        search="?sku_id=12000035460442808", in_stock=True, combo=False, content=None):
    """The product page as item() sees it: one answer per JS expression it runs there."""
    answers = {"document.body.innerText": body, "location.search": search, f"!!({ali.CART_BTN})": in_stock,
               f"!!({ali.COMBO_BTN})": combo, ali.CONTENT_JS: content or {"chars": "", "desc": "", "imgs": []},
               "document.querySelector('h1')?.innerText.trim() || ''": title}

    def js(expr, **_):
        if "propNameWrap" in expr:
            return list(props)
        if "findIndex(s => s === 'В корзину')" in expr:
            return price
        return answers[expr]
    tab = MagicMock()
    tab.js.side_effect = js
    return tab


class ItemTests(unittest.TestCase):
    def item(self, tab, data, id_or_url=ITEM, **kw):
        with patch.object(ali, "_tab", return_value=tab), patch.object(ali, "_fetch", return_value=data) as fetch, \
                patch.object(ali.time, "sleep"):
            out = ali.item(id_or_url, **kw)
        tab.close.assert_called_once()
        self.assertEqual(fetch.call_args.args[1], f"/aer-jsonapi/v1/bx/pdp/web/productData?productId={ITEM}&sourceId=0&sku_id=0")
        return out, fetch

    def test_full_card_in_stock(self):
        tab = pdp(content={"chars": "Характеристики\nНазвание бренда\nOLOPKY\nПроисхождение\nКитай\nМатериал",
                           "desc": "Описание\n\n\nкабель\n  \nдля зарядки  ", "imgs": DESC_IMGS})
        out, fetch = self.item(tab, PRODUCT_DATA, sku="12000035460442808")
        self.assertEqual(fetch.call_count, 1)              # the variants come from the same answer
        self.assertEqual(tab.goto.call_args.args[:2], (f"https://aliexpress.ru/item/{ITEM}.html?sku_id=12000035460442808", "ali"))
        self.assertEqual(out, "\n".join([
            "PD 60 Вт USB C кабель", f"id {ITEM} · sku 12000035460442808 · 88 ₽", "выбрано: Цвет: as the pictures show; Длина: 1m",
            "доставка:", "  9–12 ноября в пункт выдачи — 20 ₽", "  15–19 ноября почтой — бесплатно",
            "скидка 51%: 88–147 ₽ вместо 180–300 ₽ (диапазон — по всем вариантам)",
            "рейтинг 4.8, отзывов 1657, 18 906 купили · бренд OLOPKY",
            "варианты (свойства\tsku\tцена\tостаток):", *VARIANT_ROWS,
            "фото (shop_images): " + " ".join(PHOTOS[:10]),
            "видео: https://video.aliexpress-media.com/v1.mp4",
            "картинки в описании (shop_images): " + " ".join(DESC_IMGS[:8]),
            "отзывы: ali_reviews",
            "характеристики: Название бренда: OLOPKY; Происхождение: Китай",
            "описание продавца:\nОписание\nкабель\nдля зарядки"]))

    def test_combo_only_without_variants_or_details(self):
        tab = pdp(body="Кабель\n500 ₽\nВ комбо-корзину", title="Кабель", price="500 ₽", props=(), search="", in_stock=False, combo=True)
        out, fetch = self.item(tab, {"data": None}, f"https://aliexpress.ru/item/{ITEM}.html?spm=a2g0o", list_variants=False)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(tab.goto.call_args.args[0], f"https://aliexpress.ru/item/{ITEM}.html")
        self.assertEqual(out, f"Кабель\nid {ITEM} · sku  · 500 ₽ · только комбо-корзина (купить можно от 2 товаров из комбо)\n"
                              "выбрано: \nдоставка: не нашёл на странице\nрейтинг —, отзывов 0, покупок —\nотзывы: ali_reviews")

    def test_out_of_stock(self):
        out, _ = self.item(pdp(in_stock=False), {"data": {}})
        self.assertEqual(out.splitlines()[1], f"id {ITEM} · sku 12000035460442808 · 88 ₽ · НЕТ В НАЛИЧИИ")

    def test_description_is_cut_unless_full(self):
        tab = pdp(content={"chars": "", "desc": "а" * 2600 + "КОНЕЦ", "imgs": []})
        self.assertEqual(self.item(tab, {"data": {}})[0].split("описание продавца:\n")[1], "а" * 2500)
        tab = pdp(content={"chars": "", "desc": "а" * 2600 + "КОНЕЦ", "imgs": []})
        self.assertEqual(self.item(tab, {"data": {}}, full=True)[0].split("описание продавца:\n")[1], "а" * 2600 + "КОНЕЦ")

    def test_no_item_id_in_the_link(self):
        with self.assertRaisesRegex(ValueError, "не нашёл id товара"):
            ali.item("https://aliexpress.ru/store/1102")


class VariantTests(unittest.TestCase):
    def setUp(self):
        with patch.object(ali, "_fetch", return_value=PRODUCT_DATA) as fetch:
            self.variants = ali._skus(MagicMock(), ITEM)        # no product data given: it asks the API itself
        self.assertEqual(fetch.call_args.args[1], f"/aer-jsonapi/v1/bx/pdp/web/productData?productId={ITEM}&sourceId=0&sku_id=0")

    def test_variants_from_the_product_api(self):
        self.assertEqual(["  " + "\t".join([v["label"], v["sku"], v["price"], str(v["stock"] or "нет")]) for v in self.variants],
                         VARIANT_ROWS)

    def test_one_variant_by_name_or_display_name_in_any_case(self):
        self.assertEqual(ali._sku_for(self.variants, {"ЦВЕТ": " черный "}), "12000035597315109")
        self.assertEqual(ali._sku_for(self.variants, {"Цвет": "As the pictures show", "длина": "2M"}), "12000036024713698")

    def test_several_variants_fit(self):
        with self.assertRaises(ValueError) as e:
            ali._sku_for(self.variants, {"Цвет": "as the pictures show"})
        self.assertEqual(str(e.exception), "подходит несколько для {'Цвет': 'as the pictures show'}; варианты: "
                                           "Цвет: as the pictures show; Длина: 1m | Цвет: as the pictures show; Длина: 2 м")

    def test_no_variant_fits(self):
        with self.assertRaises(ValueError) as e:
            ali._sku_for(self.variants, {"Цвет": "red"})
        self.assertEqual(str(e.exception), "нет такого варианта для {'Цвет': 'red'}; варианты: "
                                           "Цвет: as the pictures show; Длина: 1m | Цвет: Черный; Длина: 2 м | "
                                           "Цвет: as the pictures show; Длина: 2 м | ")


FULL_REVIEW = {"root": {"text": "Хороший  кабель\nзаряжает быстро", "grade": 5, "date": "1 июня 2026",
                        "images": [{"url": "https://ae01.alicdn.com/kf/r1.jpg"}, {"id": "без url"}],
                        "comments": [{"text": "Спасибо за отзыв!"}, {"text": ""}]},
               "additional": {"text": "через месяц работает", "images": [{"url": "https://ae01.alicdn.com/kf/r2.jpg"}]},
               "product": {"skuProperties": "Цвет: черный, Длина: 1m"}, "interaction": {"likesAmount": 7}, "reviewer": {"name": "A***a"}}
FULL_ROW = ("1 июня 2026\t5\t7\tЦвет: черный, Длина: 1m\tA***a\tХороший кабель заряжает быстро | дополнение: через месяц работает"
            " | ответ: Спасибо за отзыв!\thttps://ae01.alicdn.com/kf/r1.jpg https://ae01.alicdn.com/kf/r2.jpg")
PLAIN_REVIEW = {"root": {"text": "норм", "grade": 4, "date": "2 июня 2026"}}
ALI_REVIEWS_HEAD = "дата\t★\tполезно\tвариант\tавтор\tтекст\tфото (shop_images)"


def feedback(reviews):
    return {"data": {"reviews": reviews}}


class ReviewsTests(unittest.TestCase):
    def reviews(self, answers, **kw):
        tab = MagicMock()
        with patch.object(ali, "_tab", return_value=tab), patch.object(ali, "_fetch", side_effect=answers) as fetch, \
                patch.object(ali, "_product_data", return_value={"data": {"reviews": 1657, "rating": {"middle": 4.8}}}), \
                patch.object(ali.time, "sleep") as sleep:
            out = ali.reviews(ITEM, **kw)
        tab.close.assert_called_once()
        self.assertEqual({c.args[1] for c in fetch.call_args_list}, {"/aer-jsonapi/review/v5/desktop/product-reviews"})
        self.assertEqual(sleep.call_count, fetch.call_count - 1)       # a pause before every page after the first
        return out, [c.args[2] for c in fetch.call_args_list]

    def test_one_page(self):
        out, bodies = self.reviews([feedback([FULL_REVIEW, PLAIN_REVIEW])])
        self.assertEqual(bodies, [{"productKey": {"id": ITEM, "sourceId": 0}, "pagination": {"pageNum": 1, "pageSize": 10},
                                   "sort": 1, "filters": [], "skuFilter": []}])
        self.assertEqual(out, f"AliExpress · товар {ITEM}: рейтинг 4.8, отзывов 1657\n"
                              "страница 1 из 166 (по 10; с фильтром страниц меньше), сортировка useful. "
                              "У отзывов в ответе API только фото, видео нет.\n"
                              f"{ALI_REVIEWS_HEAD}\n{FULL_ROW}\n2 июня 2026\t4\t0\t\t\tнорм\t")

    def test_newest_with_photos_from_page_three(self):
        out, bodies = self.reviews([feedback([FULL_REVIEW])], sort="new", with_media=True, page=3)
        self.assertEqual((bodies[0]["pagination"], bodies[0]["sort"], bodies[0]["filters"]), ({"pageNum": 3, "pageSize": 10}, 2, [1]))
        self.assertEqual(out.splitlines()[1], "страница 3 из 166 (по 10; с фильтром страниц меньше), сортировка new, только с фото. "
                                              "У отзывов в ответе API только фото, видео нет.")

    def test_site_refuses_the_first_page(self):
        out, _ = self.reviews([{"error": {"message": "Неверный запрос"}}])
        self.assertEqual(out, "AliExpress не отдал отзывы: Неверный запрос")

    def test_site_refuses_a_later_page_of_a_query(self):
        out, bodies = self.reviews([feedback([FULL_REVIEW] + [PLAIN_REVIEW] * 9), {"error": {"message": "Слишком много запросов"}}],
                                   query="месяц")
        self.assertEqual([b["pagination"]["pageNum"] for b in bodies], [1, 2])
        self.assertEqual(out.splitlines()[1:], ["страница 1: «месяц» нашлось в 1 из 10; дальше сайт ответил «Слишком много запросов», "
                                                "сортировка useful. У отзывов в ответе API только фото, видео нет.",
                                                ALI_REVIEWS_HEAD, FULL_ROW])

    def test_query_stops_at_30_rows(self):
        out, bodies = self.reviews([feedback([FULL_REVIEW] * 10)] * 4, query="черный")
        self.assertEqual(len(bodies), 3)
        self.assertIn("страницы 1–3: «черный» нашлось в 30 из 30", out)

    def test_query_reads_at_most_eight_pages(self):
        out, bodies = self.reviews([feedback([FULL_REVIEW] + [PLAIN_REVIEW] * 9)] * 10, query="черный")
        self.assertEqual(len(bodies), ali.QUERY_PAGES)
        self.assertIn("страницы 1–8: «черный» нашлось в 8 из 80", out)

    def test_unknown_sort(self):
        with patch.object(ali, "_tab") as tab:
            self.assertEqual(ali.reviews(ITEM, sort="date"), "sort: одно из useful, new, high, low")
        tab.assert_not_called()


def cart_row(cart_id, link, checked, *lines):
    """One cart line as CART_ROWS_JS reads it from the page."""
    return {"cart_id": cart_id, "link": link, "checked": checked, "lines": list(lines)}


CART_TITLE = "PD 60 Вт USB C кабель " + "длинное название " * 6
ROWS = [cart_row("2001", f"https://aliexpress.ru/item/{ITEM}.html?sku_id=12000035460442808", True, CART_TITLE, "Цвет: черный",
                 "88 ₽", "180 ₽", "Бесплатная доставка", "Доставка 9–12 ноября", "12"),
        cart_row("2002", "https://aliexpress.ru/item/1005_1005008606048009.html", False, "Toocki Кабель", "Нет в наличии"),
        cart_row("2003", "", False)]
CART_HEAD = "корзина AliExpress (✓ = выбран к оформлению)\ncart_id\t✓\tid товара\tшт\tцена\tназвание\tдоставка"
ROW_LINES = [f"2001\t✓\t{ITEM}\t12\t88 ₽\t{CART_TITLE[:90]}\tДоставка 9–12 ноября",
             "2002\t\t1005008606048009\t\t\tToocki Кабель\t",
             "2003\t\t\t\t\t\t"]
CART_BODY = "Корзина\n  \nВыбрать всё\nТовары, 2 шт.\n1 234 ₽\nИтого\n1 134 ₽\n  К оформлению \nВам может понравиться"
CART_URL = ("https://aliexpress.ru/cart", "ali")
CART_READY = {"wait_js": "document.body.innerText.includes('Корзина')"}


def cart_tab(*rows, body=CART_BODY):
    """The cart page: CART_ROWS_JS answers with the next list of rows (one per page load), the page text with body."""
    loads = iter(rows)
    tab = MagicMock()
    tab.js.side_effect = lambda expr, **_: next(loads) if expr == ali.CART_ROWS_JS else {"document.body.innerText": body}[expr]
    return tab


class CartTests(unittest.TestCase):
    def cart(self, tab):
        with patch.object(ali, "_tab", return_value=tab), patch.object(ali.time, "sleep") as sleep:
            out = ali.cart()
        tab.goto.assert_called_once_with(*CART_URL, **CART_READY)
        sleep.assert_called_once_with(1.5)
        tab.close.assert_called_once()
        return out

    def test_lines_and_the_total_to_check_out(self):
        self.assertEqual(self.cart(cart_tab(ROWS)), "\n".join([CART_HEAD, *ROW_LINES,
                                                                "итого к оформлению: Товары, 2 шт. · 1 234 ₽ · Итого · 1 134 ₽"]))

    def test_total_near_the_top_of_the_page(self):
        out = self.cart(cart_tab(ROWS[:1], body="Итого\n88 ₽\nК оформлению"))
        self.assertEqual(out.splitlines()[-1], "итого к оформлению: Итого · 88 ₽")

    def test_no_total_on_the_page(self):
        self.assertEqual(self.cart(cart_tab(ROWS, body="Корзина\nИтого\n0 ₽")), "\n".join([CART_HEAD, *ROW_LINES]))

    def test_empty_cart(self):
        tab = cart_tab([])
        self.assertEqual(self.cart(tab), "корзина AliExpress пуста")
        self.assertEqual([c.args[0] for c in tab.js.call_args_list], [ali.CART_ROWS_JS])


if __name__ == "__main__":
    unittest.main()
