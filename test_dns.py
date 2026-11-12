"""DNS: what the site's pages show (search cards, product card) and its reviews JSON -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_dns"""
import json
import unittest
from unittest.mock import MagicMock, patch

import dns
import pace

GUID = "11111111-2222-4333-8444-555555555555"
GUID2 = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def fake_tab(results, here="https://www.dns-shop.ru/search/?q=x"):
    """A tab whose js() answers location.href with here and anything else with the next of results."""
    tab = MagicMock()
    answers = iter(results)
    tab.js.side_effect = lambda expr, **kw: here if expr == "location.href" else next(answers)
    return tab


class DnsHelperTests(unittest.TestCase):
    def test_rub(self):
        self.assertEqual(dns._rub("16 699\xa0₽"), 16699)
        self.assertEqual(dns._rub(" 12 699 "), 12699)
        self.assertIsNone(dns._rub(""))
        self.assertIsNone(dns._rub(None))

    def test_stock_lines_of_the_avails_markup(self):
        self.assertEqual(dns._avail(AVAIL_HTML), "В наличии в 5 магазинах; Доставим на дом за 2 часа")
        self.assertEqual(dns._avail(NOT_AVAIL_HTML), "Нет в наличии")
        self.assertEqual(dns._avail(""), "")
        self.assertEqual(dns._city(AVAIL_HTML), "Город-пример")
        self.assertEqual(dns._city(NOT_AVAIL_HTML), "")

    def test_text_from_markup(self):
        self.assertEqual(dns._text("<p>Яркий&nbsp;экран</p>\n <p>и звук</p>"), "Яркий экран и звук")
        self.assertEqual(dns._text(None), "")

    def test_url_id_of_a_guid(self):
        # the 16-hex id in a product link: the dashless guid's first 12 and its 28th-31st characters
        self.assertEqual(dns._url_id(GUID), "1111111122225555")

    def test_guid_in_any_text(self):
        self.assertEqual(dns._guid(f" {GUID.upper()} "), GUID)
        self.assertEqual(dns._guid(f"/product/microdata/{GUID}/"), GUID)
        self.assertIsNone(dns._guid("https://www.dns-shop.ru/product/1111111122225555/monitor/"))
        self.assertIsNone(dns._guid(None))

    def test_item_url(self):
        self.assertEqual(dns._item_url("https://www.dns-shop.ru/product/1111111122225555/monitor/?opinion"),
                         "https://www.dns-shop.ru/product/1111111122225555/monitor/")
        self.assertEqual(dns._item_url("/product/1111111122225555/monitor/"), "https://www.dns-shop.ru/product/1111111122225555/monitor/")
        self.assertEqual(dns._item_url(GUID), "https://www.dns-shop.ru/product/1111111122225555/")
        self.assertIsNone(dns._item_url("монитор"))
        self.assertIsNone(dns._item_url("https://example.com/product/1/"))
        self.assertIsNone(dns._item_url("https://www.dns-shop.ru/catalog/17a8/monitory/"))
        self.assertIsNone(dns._item_url(f"/catalog/stale-stock/{GUID}/"))

    def test_url_with_params(self):
        url = "https://www.dns-shop.ru/search/?q=%D0%BC&category=17a8"
        self.assertEqual(dns._with(url, {"order": "price-asc", "p": 2}),
                         "https://www.dns-shop.ru/search/?q=%D0%BC&category=17a8&order=price-asc&p=2")
        self.assertEqual(dns._with(url + "&stock=", {"p": 2}), url + "&stock=&p=2")                       # the site's empty params stay
        self.assertEqual(dns._with(url + "&order=popular&p=1", {"order": "price-asc", "p": 2}),        # the site's own order= gives way
                         "https://www.dns-shop.ru/search/?q=%D0%BC&category=17a8&order=price-asc&p=2")
        self.assertEqual(dns._with("https://www.dns-shop.ru/search/", {"p": 2}), "https://www.dns-shop.ru/search/?p=2")
        self.assertTrue(dns._has(url + "&order=price-asc&p=2", {"order": "price-asc", "p": 2}))
        self.assertFalse(dns._has(url, {"order": "price-asc"}))

    def test_load_waits_for_a_new_document(self):
        tab = MagicMock()
        tab.js.return_value = 1700000000123.5
        dns._load(tab, "https://www.dns-shop.ru/x/", "!!document.body")
        self.assertEqual(tab.goto.call_args.args, ("https://www.dns-shop.ru/x/", "dns"))
        self.assertEqual(tab.goto.call_args.kwargs["wait_js"], "performance.timeOrigin !== 1700000000123.5 && (!!document.body)")

    def test_photos_from_the_slider_script(self):
        images = [{"thumb": f"https://c/45/{i}.jpg", "desktop": f"https://c/500/{i}.jpg"} for i in range(12)]
        script = "window.x = 1; window.initProductImagesSlider('pis-1', " + json.dumps({"images": images, "v": {"a": 1}}) + "); window.y = {};"
        self.assertEqual(dns._photos(script), [f"https://c/500/{i}.jpg" for i in range(12)])
        self.assertEqual(dns._photos(""), [])
        self.assertEqual(dns._photos("initProductImagesSlider('a', {broken"), [])
        self.assertEqual(dns._photos("initProductImagesSlider('a'"), [])
        self.assertEqual(dns._photos('initProductImagesSlider(\'a\', {"images": [{"desktop": "u"}]})'), ["u"])   # the call first in its script
        self.assertEqual(dns._photos('{"images": [{"desktop": "u"}]}'), [])                                   # an object, but not the slider's


def buy(sid, key, current, previous=None, **more):
    return {"id": sid, "data": {"id": key, "price": {"current": current, **({"previous": previous} if previous else {})}, **more}}


AVAIL_HTML = ('<div class="order-avail-wrap order-avail-wrap_main" data-products="[{&quot;id&quot;:&quot;x&quot;}]"><span class="available">'
              'В наличии </span><a href="/shops/x/"><span>в 5 магазинах</span></a><div id="modal-pickup-shops-container"></div></div>'
              '<div class="delivery-info-widget" data-city-name = "Город-пример" data-price="1"><span>Доставим на дом </span><a>за 2 часа</a></div>')
NOT_AVAIL_HTML = '<div class="order-avail-wrap order-avail-wrap_main order-avail-wrap_not-avail " >\n\t\tНет в наличии\t</div>'
ANSWERS = {"buy": {"data": {"states": [buy("as-b1", GUID, 15199, 19199), buy("as-b2", GUID2, 9999, 9999), buy("as-b3", "1000003", 9499, 12699)]}},
           "avail": {"data": {"states": [{"id": "as-a1", "data": {"html": AVAIL_HTML}}, {"id": "as-a2", "data": {"html": NOT_AVAIL_HTML}},
                                         {"id": "as-a3", "data": {"html": "<div><span>В наличии </span><a>в 1 магазине</a></div>"}}]}}}
CARDS = [
    {"guid": GUID, "code": "1000001", "href": "/product/1111111122225555/27-monitor-a/", "name": '27" Монитор A черный',
     "rating": "4.77", "reviews": "2k отзывов", "brandRating": False, "seller": "", "buyId": "as-b1", "availId": "as-a1"},
    {"guid": GUID2, "code": "1000002", "href": "/product/aaaaaaaabbbbeeee/24-monitor-b/", "name": '24" Монитор  B ',
     "rating": "5", "reviews": "рейтинг бренда", "brandRating": True, "seller": 'Продавец: ООО "Пример"', "buyId": "", "availId": "as-a2"},
    {"guid": GUID, "code": "1000003", "href": f"/catalog/stale-stock/{GUID}/", "name": '27" Монитор A черный',
     "rating": "4.82", "reviews": "605 отзывов", "brandRating": False, "seller": "", "buyId": "", "availId": "as-a3"}]
PAGE_SHOWN = {"url": "https://www.dns-shop.ru/search/?q=%D0%BC%D0%BE%D0%BD%D0%B8%D1%82%D0%BE%D1%80&category=17a8",
              "title": "Найдено 1 727 товаров  в категории Мониторы", "h1": "Найдено 1 727 товаров  в категории Мониторы",
              "product": False, "cards": CARDS}
SEARCH_HEAD = ("ссылки относительно https://www.dns-shop.ru; цены и наличие — для города из профиля на сайте (Город-пример)\n"
               "#\tid\tкод\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tналичие\tпродавец\tссылка\n")
QUERY = "https://www.dns-shop.ru/search/?q=%D0%BC%D0%BE%D0%BD%D0%B8%D1%82%D0%BE%D1%80"


class DnsSearchTests(unittest.TestCase):
    def search(self, shown, here=None, answers=ANSWERS, **kw):
        tab = fake_tab([shown], here or (shown or {}).get("url", QUERY))
        with patch.object(dns, "tab_for", return_value=tab), patch.object(dns, "capture", return_value=answers) as capture, \
                patch.object(dns, "log") as log:
            return dns.search("монитор", **kw), capture, tab, log

    def test_whole_page(self):
        got, capture, tab, _ = self.search(PAGE_SHOWN)
        self.assertEqual(got, f"DNS · 1727 найдено · страница 1 (по 24) · {PAGE_SHOWN['url']}\n"
                              "Найдено 1 727 товаров в категории Мониторы\n" + SEARCH_HEAD +
                         f"1\t{GUID}\t1000001\t15199\t19199\t27\" Монитор A черный\t4.77\t2k\tВ наличии в 5 магазинах; Доставим на дом за 2 часа\t\t/product/1111111122225555/27-monitor-a/\n"
                         f"2\t{GUID2}\t1000002\t9999\t\t24\" Монитор B\t5 (бренда)\t\tНет в наличии\tООО \"Пример\"\t/product/aaaaaaaabbbbeeee/24-monitor-b/\n"
                         f"3\t{GUID}\t1000003\t9499\t12699\t(stale-stock) 27\" Монитор A черный\t4.82\t605\tВ наличии в 1 магазине\t\t/catalog/stale-stock/{GUID}/")
        self.assertEqual(capture.call_count, 1)
        self.assertEqual(capture.call_args.args, (tab, "dns", QUERY, dns.LIST_ANSWERS))
        tab.close.assert_called_once()

    def test_a_category_page_counts_in_its_heading(self):
        got, _, _, _ = self.search({**PAGE_SHOWN, "title": "124 товара", "h1": "Наушники"})
        self.assertTrue(got.startswith(f"DNS · 124 найдено · страница 1 (по 24) · {PAGE_SHOWN['url']}\nНаушники: 124 товара\n"))

    def test_a_page_without_a_count_line(self):
        got, _, _, _ = self.search({**PAGE_SHOWN, "title": ""})
        self.assertTrue(got.startswith(f"DNS · 3 найдено · страница 1 (по 24) · {PAGE_SHOWN['url']}\nссылки относительно"))

    def test_params_lost_in_the_category_redirect_are_asked_again(self):
        here = PAGE_SHOWN["url"] + "&order=popular"
        got, capture, _, _ = self.search(PAGE_SHOWN, here=here, sort="price_asc", price_max=20000, page=2)
        self.assertEqual([c.args[2] for c in capture.call_args_list],
                         [QUERY + "&order=price-asc&price=0-20000&p=2", PAGE_SHOWN["url"] + "&order=price-asc&price=0-20000&p=2"])
        self.assertTrue(got.startswith("DNS · 1727 найдено · страница 2 (по 24) · "))

    def test_params_the_site_dropped_twice_are_named(self):
        got, _, _, _ = self.search(PAGE_SHOWN, here=PAGE_SHOWN["url"], sort="price_asc")
        self.assertIn("\n⚠️ сайт не применил order=price-asc: это его выдача по умолчанию\n", got)

    def test_params_the_site_kept_take_one_load(self):
        _, capture, _, _ = self.search(PAGE_SHOWN, here=QUERY + "&order=rating&price=500-10000000", sort="rating", price_min=500)
        self.assertEqual(capture.call_count, 1)

    def test_limit(self):
        got, _, _, _ = self.search(PAGE_SHOWN, limit=1)
        self.assertEqual(len(got.splitlines()), 5)

    def test_without_the_prices_answer(self):
        got, _, _, _ = self.search({**PAGE_SHOWN, "cards": CARDS[:1]}, answers={})
        self.assertTrue(got.endswith(f"1\t{GUID}\t1000001\t\t\t27\" Монитор A черный\t4.77\t2k\t\t\t/product/1111111122225555/27-monitor-a/"))
        self.assertIn("цены и наличие — для города из профиля на сайте\n", got)

    def test_unknown_sort(self):
        self.assertEqual(dns.search("монитор", sort="cheap"),
                         "sort: одно из popular, price_asc, price_desc, new, discount, reviews, rating")

    def test_the_site_opened_a_product(self):
        got, _, _, _ = self.search({**PAGE_SHOWN, "product": True, "cards": [], "url": "https://www.dns-shop.ru/product/1111111122225555/a/"})
        self.assertEqual(got, "DNS сразу открыл карточку товара: https://www.dns-shop.ru/product/1111111122225555/a/ — смотри dns_item")

    def test_no_products_on_the_page(self):
        got, _, _, _ = self.search({**PAGE_SHOWN, "cards": [], "title": "", "h1": "Ничего не нашлось"})
        self.assertEqual(got, f"DNS: товаров на странице нет («Ничего не нашлось») · {PAGE_SHOWN['url']}")

    def test_blocked(self):
        got, _, tab, log = self.search({**PAGE_SHOWN, "cards": [], "title": "", "h1": ""})
        self.assertEqual(got, dns.BLOCKED)
        log.warning.assert_called_once()
        tab.close.assert_called_once()

    def test_refused_goes_up_and_closes_the_tab(self):
        tab = fake_tab([])
        with patch.object(dns, "tab_for", return_value=tab), patch.object(dns, "capture", side_effect=pace.Refused("⏸ DNS")):
            with self.assertRaises(pace.Refused):
                dns.search("монитор")
        tab.close.assert_called_once()


DESCRIPTION = "Матрица IPS. " * 300
SLIDER = "window.initProductImagesSlider('pis-1', " + json.dumps({"images": [{"desktop": f"https://c/500/{i}.jpg"} for i in range(11)]}) + ");"
LD = {"aggregateRating": {"ratingValue": 4.77, "reviewCount": 2022}, "description": DESCRIPTION,
      "offers": {"price": 15199, "availability": "https://schema.org/InStock"}}
CARD = {"url": "https://www.dns-shop.ru/product/1111111122225555/27-monitor-a/", "name": '27" Монитор A черный', "code": "1000001",
        "guid": f"/product/microdata/{GUID}/", "seller": "", "buyId": "as-b1", "availId": "as-a1", "ld": json.dumps(LD), "slider": SLIDER,
        "specs": [["Диагональ:", ' 27" '], ["Разрешение экрана:", "2560x1440"]], "drawnPrice": "", "drawnPrev": "", "drawnAvail": ""}
PENDING = [["as-b1", "product-buy"], ["as-a1", "avails-container"]]
CARD_ANSWERS = {"buy": {"data": {"states": [buy("as-b1", GUID, 15199, 19199)]}},
                "avail": {"data": {"states": [{"id": "as-a1", "data": {"html": AVAIL_HTML}}]}}}
CARD_TOP = ('27" Монитор A черный\nhttps://www.dns-shop.ru/product/1111111122225555/27-monitor-a/\n'
            f"код товара: 1000001 · id: {GUID}\n")
CARD_TAIL = ("рейтинг: 4.77, отзывов 2022\n"
             "фото (shop_images): " + " ".join(f"https://c/500/{i}.jpg" for i in range(10)) + "\n"
             "отзывы: dns_reviews\n"
             'характеристики:\nДиагональ: 27"\nРазрешение экрана: 2560x1440\n\n')
CARD_TEXT = (CARD_TOP + "цена: 15199 ₽ (было 19199, −21%)\n"
             "наличие и доставка (для города из профиля на сайте: Город-пример): В наличии в 5 магазинах; Доставим на дом за 2 часа\n" + CARD_TAIL)


class DnsItemTests(unittest.TestCase):
    def item(self, shown, url=CARD["url"] + "?opinion", full=False, answers=CARD_ANSWERS, pending=PENDING):
        tab = fake_tab([pending, shown])
        with patch.object(dns, "tab_for", return_value=tab), patch.object(dns, "capture", return_value=answers) as capture, \
                patch.object(dns, "_load") as load, patch.object(dns, "log") as log:
            return dns.item(url, full), capture, tab, log, load

    def test_full_card_with_the_answers_its_lazy_loader_was_woken_for(self):
        got, capture, tab, _, load = self.item(CARD)
        self.assertEqual(got, CARD_TEXT + DESCRIPTION.strip()[:2500])
        self.assertEqual(load.call_args.args[:3], (tab, CARD["url"], dns.ITEM_READY))
        args, kw = capture.call_args
        self.assertEqual(args, (tab, "dns", None, dns.LIST_ANSWERS))
        self.assertIn("A.handleIntersection(", kw["js"])
        self.assertIn(json.dumps(["as-b1", "as-a1"]), kw["js"])
        tab.close.assert_called_once()

    def test_only_the_woken_types_are_waited_for(self):
        _, capture, _, _, _ = self.item(CARD, pending=[["as-a1", "avails-container"]])
        self.assertEqual(capture.call_args.args[3], {"avail": dns.LIST_ANSWERS["avail"]})

    def test_a_tab_in_front_has_them_drawn_already(self):
        drawn = {**CARD, "buyId": "", "drawnPrice": "15 199\xa0₽", "drawnPrev": "19 199", "drawnAvail": AVAIL_HTML}
        got, capture, _, log, _ = self.item(drawn, pending=[])
        capture.assert_not_called()
        log.warning.assert_not_called()
        self.assertEqual(got, CARD_TEXT + DESCRIPTION.strip()[:2500])

    def test_only_the_page_data_left(self):
        got, _, _, log, _ = self.item(CARD, answers={}, pending=None)
        self.assertEqual(log.warning.call_args.args[0], "dns item %s: no AjaxState on the page")
        self.assertEqual(got, CARD_TOP + "цена: 15199 ₽ (из данных страницы: старая цена и скидка не пришли)\n"
                                         "наличие: в наличии (из данных страницы: магазины и доставка не пришли)\n" + CARD_TAIL + DESCRIPTION.strip()[:2500])

    def test_nothing_about_the_offer(self):
        got, _, _, _, _ = self.item({**CARD, "ld": "", "slider": "", "specs": []}, answers={})
        self.assertEqual(got, CARD_TOP + "цена: не пришла\nналичие: не пришло\nотзывы: dns_reviews\n\n")

    def test_out_of_stock_in_the_page_data(self):
        ld = {"offers": {"price": 999, "availability": "https://schema.org/OutOfStock"}}
        got, _, _, _, _ = self.item({**CARD, "ld": json.dumps(ld)}, answers={})
        self.assertIn("\nналичие: нет в наличии\n", got)

    def test_marketplace_seller_out_of_stock(self):
        sold_out = {"buy": {"data": {"states": [buy("as-b1", GUID, 15999, notAvail=True, tooltip="Последняя цена продажи")]}},
                    "avail": {"data": {"states": [{"id": "as-a1", "data": {"html": NOT_AVAIL_HTML}}]}}}
        got, _, _, _, _ = self.item({**CARD, "seller": 'ООО "Пример"', "ld": "", "slider": "", "specs": []}, answers=sold_out)
        self.assertEqual(got, CARD_TOP + "цена: 15999 ₽ (Последняя цена продажи)\nпродавец: ООО \"Пример\" (не DNS)\n"
                                         "наличие и доставка (для города из профиля на сайте): Нет в наличии\nотзывы: dns_reviews\n\n")

    def test_short_description_by_default(self):
        tab = fake_tab([PENDING, CARD])
        with patch.object(dns, "tab_for", return_value=tab), patch.object(dns, "capture", return_value=CARD_ANSWERS), patch.object(dns, "_load"):
            self.assertEqual(dns.item(CARD["url"]), CARD_TEXT + DESCRIPTION.strip()[:2500])

    def test_the_top_container_wins_over_another_of_the_same_product(self):
        answers = {**CARD_ANSWERS, "buy": {"data": {"states": [buy("as-other", GUID, 1), buy("as-b1", GUID, 15199, 19199)]}}}
        got, _, _, _, _ = self.item(CARD, answers=answers)
        self.assertIn("\nцена: 15199 ₽ (было 19199, −21%)\n", got)

    def test_an_old_price_equal_to_the_price_is_no_discount(self):
        answers = {**CARD_ANSWERS, "buy": {"data": {"states": [buy("as-b1", GUID, 15199, 15199)]}}}
        got, _, _, _, _ = self.item(CARD, answers=answers)
        self.assertIn("\nцена: 15199 ₽\n", got)

    def test_full_description(self):
        got, _, _, _, _ = self.item(CARD, full=True)
        self.assertTrue(got.endswith(DESCRIPTION.strip()))

    def test_guid_opens_the_short_link(self):
        _, _, _, _, load = self.item(CARD, url=GUID)
        self.assertEqual(load.call_args.args[1], "https://www.dns-shop.ru/product/1111111122225555/")

    def test_a_stale_stock_offer_points_to_the_regular_card(self):
        self.assertEqual(dns.item(f"/catalog/stale-stock/{GUID}/"),
                         f'страницу предложения stale-stock dns_item не читает; обычная карточка этого товара — dns_item("{GUID}")')

    def test_not_a_product(self):
        self.assertEqual(dns.item("монитор"), "нужна ссылка на товар из dns_search (https://www.dns-shop.ru/product/…) или его id")

    def test_blocked(self):
        got, _, tab, log, _ = self.item({**CARD, "name": ""})
        self.assertEqual(got, dns.BLOCKED)
        log.warning.assert_called_once()
        tab.close.assert_called_once()


OPINIONS = {"message": "", "data": {
    "totalCount": 2022, "averageRating": 4.77,
    "filtersCount": {"grades": [{"grade": 5, "count": 1772}, {"grade": 1, "count": 51}], "hasPhoto": 113, "hasVideo": 10},
    "grades": [{"grade": 1, "count": 51, "percentage": "2.52"}, {"grade": 5, "count": 1772, "percentage": "87.64"}],
    "characteristicGrades": [{"title": "Яркость", "value": 4.9}, {"title": "Качество сборки", "value": 4.8}],
    "opinions": [
        {"isTop": True, "insertStamp": "2025-05-21T22:40:56", "rating": 5, "votes": {"positive": 76, "negative": 9},
         "plus": "<p>Цвета</p>", "minus": "<p>Подставка</p>", "comment": "<p>Всё&nbsp;хорошо</p>", "period": "Менее месяца",
         "multiCardSpecs": {"Частота": "180"}, "additions": [{"text": "Сменил подставку"}],
         "images": [{"thumbUrl": "https://c/op/1.jpeg"}], "videos": [{"url": "https://v/1.mp4"}]},
        {"isTop": False, "insertStamp": "2026-01-02T10:00:00", "rating": 1, "votes": {"positive": 0, "negative": 0},
         "plus": None, "minus": "", "comment": "<p>Не включился</p>", "period": None, "multiCardSpecs": None,
         "additions": [], "images": [], "videos": []}]}}
REVIEWS_TEXT = (f"DNS · id {GUID}: рейтинг 4.77, отзывов 2022 (на все варианты товара) · 5★ 1772 · 1★ 51\n"
                "оценки: Яркость 4.9, Качество сборки 4.8\n"
                "страница 1 (по 10: больше сайт за раз не отдаёт), сортировка useful; с фото: 113, с видео: 10\n"
                "дата\t★\tполезно\tвариант\tсрок\tтекст\tфото и видео (shop_images)\n"
                "2025-05-21\t5\t+76/−9\tЧастота 180\tМенее месяца\t[закреплён] + Цвета | − Подставка | Всё хорошо | дополнение: Сменил подставку\t"
                "https://c/op/1.jpeg https://v/1.mp4\n"
                "2026-01-02\t1\t\t\t\tНе включился\t")


class DnsReviewsTests(unittest.TestCase):
    def reviews(self, answer, id_or_url=GUID, microdata=f"/product/microdata/{GUID}/", **kw):
        tab = fake_tab([microdata])
        with patch.object(dns, "site_tab", return_value=tab) as site_tab, patch.object(dns, "tab_for", return_value=tab) as tab_for, \
                patch.object(dns, "_load") as load, patch.object(dns, "capture", return_value=answer) as capture:
            got = dns.reviews(id_or_url, **kw)
        return got, capture, tab, load, site_tab, tab_for

    def test_by_guid_is_one_request_from_any_dns_page(self):
        got, capture, tab, load, site_tab, _ = self.reviews({"o": OPINIONS})
        self.assertEqual(got, REVIEWS_TEXT)
        load.assert_not_called()
        self.assertEqual(site_tab.call_args.args[:3], ("dns-shop.ru", "https://www.dns-shop.ru/", "dns"))
        args, kw = capture.call_args
        self.assertEqual(args, (tab, "dns", None, {"o": ["/v1/opinion/get-product-opinions"]}))
        js = kw["js"]
        self.assertIn("window.baseHeaderConfig?.config?.cityGuid", js)         # the city of the site profile, read in the page
        self.assertIn(json.dumps({"objectTypeId": dns.OPINION_TYPE, "objectId": GUID, "offset": "0", "limit": "10", "isRealBuyer": "0",
                                  "hasPhotos": "0", "hasVideo": "0", "sort": "2", "onlyObjectOpinions": "0", "init": "1"}), js)
        self.assertIn("https://restapi.dns-shop.ru/v1/opinion/get-product-opinions", js)
        tab.close.assert_called_once()

    def test_by_link_reads_the_guid_from_the_product_page(self):
        _, capture, _, load, site_tab, tab_for = self.reviews({"o": OPINIONS}, id_or_url=CARD["url"])
        self.assertEqual(load.call_args.args[1], CARD["url"])
        site_tab.assert_not_called()
        self.assertIn(f'"objectId": "{GUID}"', capture.call_args.kwargs["js"])

    def test_a_stale_stock_link_carries_the_guid(self):
        _, capture, _, load, site_tab, _ = self.reviews({"o": OPINIONS}, id_or_url=f"/catalog/stale-stock/{GUID}/")
        load.assert_not_called()
        site_tab.assert_called_once()
        self.assertIn(f'"objectId": "{GUID}"', capture.call_args.kwargs["js"])

    def test_a_link_to_no_product_card(self):
        got, capture, _, _, _, _ = self.reviews({"o": OPINIONS}, id_or_url=CARD["url"], microdata="")
        self.assertEqual(got, dns.BLOCKED)
        capture.assert_not_called()

    def test_sort_photos_and_page(self):
        got, capture, _, _, _, _ = self.reviews({"o": OPINIONS}, sort="new", with_media=True, page=3, limit=10)
        js = capture.call_args.kwargs["js"]
        self.assertIn('"offset": "20", "limit": "10"', js)
        self.assertIn('"hasPhotos": "1"', js)
        self.assertIn('"sort": "0"', js)
        self.assertIn("страница 3 (по 10: больше сайт за раз не отдаёт), сортировка new, только с фото", got)

    def test_limit_cuts_the_rows_not_the_page(self):
        got, capture, _, _, _, _ = self.reviews({"o": OPINIONS}, page=2, limit=1)
        self.assertIn('"offset": "10", "limit": "10"', capture.call_args.kwargs["js"])
        self.assertEqual(len(got.splitlines()), 5)

    def test_unknown_sort(self):
        self.assertEqual(dns.reviews(GUID, sort="best"), "sort: одно из useful, new, rating, edited")

    def test_not_a_product(self):
        self.assertEqual(dns.reviews("монитор"), "нужен id товара из dns_search или ссылка на товар DNS")

    def test_no_reviews(self):
        got, _, _, _, _, _ = self.reviews({"o": {"data": {"opinions": []}}})
        self.assertEqual(got, f"DNS · id {GUID}: рейтинг —, отзывов 0 (на все варианты товара)\n"
                              "страница 1 (по 10: больше сайт за раз не отдаёт), сортировка useful; с фото: 0, с видео: 0\n"
                              "дата\t★\tполезно\tвариант\tсрок\tтекст\tфото и видео (shop_images)\n(отзывов нет)")

    def test_votes_on_one_side_only(self):
        self.assertEqual(dns._useful({"negative": 3}), "+0/−3")
        self.assertEqual(dns._useful({"positive": 2}), "+2/−0")
        self.assertEqual(dns._useful({"positive": 0, "negative": 0}), "")

    def test_blocked(self):
        got, _, tab, _, _, _ = self.reviews({})
        self.assertEqual(got, dns.BLOCKED)
        tab.close.assert_called_once()

    def test_api_message(self):
        got, _, _, _, _, _ = self.reviews({"o": {"message": "Товар не найден", "data": None}})
        self.assertEqual(got, "⚠️ DNS не отдал отзывы: Товар не найден")


if __name__ == "__main__":
    unittest.main()
