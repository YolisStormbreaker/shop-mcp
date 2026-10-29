"""Золотое яблоко: the site's JSON (search, product card, delivery, reviews) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_goldapple"""
import unittest
from unittest.mock import MagicMock, patch

import goldapple

DELIVERY = {"options": [
    {"name": "экспресс-доставка", "dateInfo": "сегодня за 3 часа", "cost": {"value": {"amount": 99}}},
    {"name": "самовывоз из магазина", "date": "2026-10-30T10:00:00+03:00", "cost": {"value": {"amount": 0}},
     "costSpecial": "при заказе от 1000 ₽ — бесплатно"},
    {"name": "курьер", "cost": {"value": None}}]}


class GoldAppleHelperTests(unittest.TestCase):
    def test_delivery_options(self):
        self.assertEqual(goldapple._delivery(DELIVERY), ["экспресс-доставка — сегодня за 3 часа, 99 ₽",
                                                         "самовывоз из магазина — 2026-10-30, бесплатно (при заказе от 1000 ₽ — бесплатно)",
                                                         "курьер — "])
        self.assertEqual(goldapple._delivery(None), [])

    def test_picture_from_the_template(self):
        self.assertEqual(goldapple._img({"url": "https://cdn/p/1/${screen}.${format}", "format": ["webp", "jpg"]}), "https://cdn/p/1/fullhd.jpg")
        self.assertEqual(goldapple._img({"url": "https://cdn/p/1/${screen}.${format}", "format": ["avif"]}, "mobile"), "https://cdn/p/1/mobile.avif")
        self.assertEqual(goldapple._img({}), "")

    def test_cart_items(self):
        self.assertEqual(goldapple._items({"data": {"rawCart": {"items": [{"productSku": "1"}]}}}), [{"productSku": "1"}])
        self.assertEqual(goldapple._items({"data": None}), [])
        self.assertEqual(goldapple._items(None), [])

    def test_rub(self):
        self.assertEqual(goldapple._rub({"actual": {"amount": 453}}, "actual"), 453)
        self.assertIsNone(goldapple._rub({"old": None}, "old"))
        self.assertIsNone(goldapple._rub(None, "actual"))

    def test_sku_from_an_id_or_a_link(self):
        for s in ("https://goldapple.ru/19000163536-cushion", " /19000163536-cushion ", "19000163536", 19000163536):
            self.assertEqual(goldapple._sku(s), "19000163536")
        self.assertIsNone(goldapple._sku("кушон"))

    def test_text_from_markup(self):
        self.assertEqual(goldapple._text("<p>Крем&nbsp;для <b>рук</b></p>\n  "), "Крем для рук")
        self.assertEqual(goldapple._text(None), "")


SEARCH = {"data": {"count": 2000, "products": [
    {"itemId": "19000163536", "price": {"actual": {"amount": 2150}, "old": {"amount": 3070}}, "brand": "Brand A", "name": "Кушон",
     "productType": "тональный кушон", "attributes": {"units": {"currentUnitValue": "7.5", "name": "г", "count": 9}},
     "reviews": {"rating": 4.6, "reviewsCount": 7274}, "inStock": True, "url": "/19000163536-cushion"},
    {"itemId": "19000000001", "price": {"actual": {"amount": 500}, "old": {"amount": 500}}, "brand": "Brand B", "name": "Шампунь",
     "productType": "шампунь", "attributes": {"units": {"currentUnitValue": "250", "name": "мл", "count": 1}}, "reviews": {"rating": 0},
     "inStock": False, "url": "/19000000001-shampoo"},
    {"itemId": "19000000002"}]}}
SEARCH_HEAD = ("ссылки относительно https://goldapple.ru; цены и наличие — для города из профиля\n"
               "#\tартикул\tцена ₽\tбез скидки\tбренд\tназвание\tтип\tобъём\tрейтинг\tотзывов\tналичие\tссылка\n")
QUERY = "https://goldapple.ru/catalogsearch/result?q=%D1%88%D0%B0%D0%BC%D0%BF%D1%83%D0%BD%D1%8C"


class GoldAppleSearchTests(unittest.TestCase):
    def search(self, answer, **kw):
        tab = MagicMock()
        with patch.object(goldapple, "tab_for", return_value=tab), patch.object(goldapple, "capture", return_value=answer) as capture, \
                patch.object(goldapple, "log") as log:
            return goldapple.search("шампунь", **kw), capture, tab, log

    def test_whole_answer(self):
        got, capture, tab, _ = self.search({"s": SEARCH})
        self.assertEqual(got, f"Золотое яблоко · 2000+ найдено · страница 1 (по 24) · {QUERY}\n" + SEARCH_HEAD +
                         "1\t19000163536\t2150\t3070\tBrand A\tКушон\tтональный кушон\t7.5 г (вариантов: 9)\t4.6\t7274\t\t/19000163536-cushion\n"
                         "2\t19000000001\t500\t\tBrand B\tШампунь\tшампунь\t250 мл\t\t\tнет в наличии\t/19000000001-shampoo\n"
                         "3\t19000000002\tNone\t\t\t\t\t\t\t\tнет в наличии\t")
        self.assertEqual(capture.call_args.args, (tab, "goldapple", QUERY, {"s": ["/front/api/catalog/search-products"]}))
        tab.close.assert_called_once()

    def test_sort_price_and_page_go_into_the_url(self):
        got, capture, _, _ = self.search({"s": {"data": {"products": []}}}, price_max=1000, sort="priceAsc", page=3)
        url = QUERY + "&sort=priceAsc&calculatedprices=0-1000&p=3"
        self.assertEqual(capture.call_args.args[2], url)
        self.assertEqual(got, f"Золотое яблоко · 0 найдено · страница 3 (по 24) · {url}\n" + SEARCH_HEAD + "(пусто)")
        self.assertTrue(self.search({"s": {}}, price_min=300)[1].call_args.args[2].endswith("&calculatedprices=300-10000000"))

    def test_count_of_the_rows_when_the_site_gives_none(self):
        got, _, _, _ = self.search({"s": {"data": {"products": SEARCH["data"]["products"]}}}, limit=2)
        self.assertTrue(got.startswith("Золотое яблоко · 2 найдено"))
        self.assertEqual(len(got.splitlines()), 5)

    def test_unknown_sort(self):
        self.assertEqual(goldapple.search("шампунь", sort="cheap"),
                         "sort: одно из relevance, priceAsc, priceDesc, discountAmount, byRating, byNewest")

    def test_blocked(self):
        got, _, tab, log = self.search({})
        self.assertEqual(got, goldapple.BLOCKED)
        self.assertEqual(log.warning.call_args.args, ("goldapple search %s: no search-products response", QUERY))
        tab.close.assert_called_once()


def picture(path, formats=("webp", "jpg")):
    return {"url": f"https://cdn-01.goldapple.ru/p/p/{path}/${{screen}}.${{format}}", "format": list(formats), "screen": ["fullhd", "mobile"]}


APPLY = "Наносить спонжем. " * 200
CARD = {"data": {
    "itemId": "19000163536", "brand": "Brand A", "name": "Кушон", "productType": "тональный кушон",
    "attributes": {"units": {"unit": "г"}, "colors": {"options": [{"value": "c1", "text": "0.5, Porcelain"}, {"value": "c2", "text": "02, Beige"}]}},
    "variants": [
        {"itemId": "19000163535", "attributesValue": {"units": "7.5", "colors": "c2"}, "inStock": True, "imageUrls": [picture("35")],
         "price": {"actual": {"amount": 2150}, "old": {"amount": 3070}, "viewOptions": {"discountPercent": 30}}},
        {"itemId": 19000163536, "attributesValue": {"units": "7.5", "colors": "c1"}, "inStock": False,
         "imageUrls": [picture(f"36/{i}", ["webp"]) for i in range(12)], "price": {"actual": {"amount": 2150}, "old": {"amount": 2150}}},
        {"itemId": "19000163537", "attributesValue": {}, "price": None, "inStock": True, "imageUrls": [picture("37")]}],
    "productDescription": [{"type": "Description", "text": "Описание", "content": "<p>Лёгкий&nbsp;кушон</p>"},
                           {"type": "Brand", "text": "О бренде", "content": "О бренде"}, {"type": "Composition", "text": "Состав", "content": ""},
                           {"type": "Application", "text": "Применение", "content": APPLY}]}}
CARD_URL = "https://goldapple.ru/19000163536-cushion"


class GoldAppleItemTests(unittest.TestCase):
    def item(self, answer, url=CARD_URL + "?utm_source=x", full=False):
        tab = MagicMock()
        with patch.object(goldapple, "tab_for", return_value=tab), patch.object(goldapple, "capture", return_value=answer) as capture, \
                patch.object(goldapple, "log") as log:
            return goldapple.item(url, full), capture, tab, log

    def test_full_card(self):
        got, capture, tab, _ = self.item({"c": CARD, "deliv": DELIVERY})
        description = "Описание: Лёгкий кушон\nПрименение: " + APPLY.strip()
        self.assertEqual(got, "Brand A Кушон (тональный кушон)\n" + CARD_URL + "\nартикул: 19000163536\n"
                              "варианты: 7.5 г 02, Beige — 2150 ₽ (было 3070, −30%), артикул 19000163535; "
                              "7.5 г 0.5, Porcelain — 2150 ₽, нет в наличии, артикул 19000163536; 19000163537 — None ₽, артикул 19000163537\n"
                              "доставка: экспресс-доставка — сегодня за 3 часа, 99 ₽; "
                              "самовывоз из магазина — 2026-10-30, бесплатно (при заказе от 1000 ₽ — бесплатно); курьер — \n"
                              "фото (shop_images): " + " ".join(f"https://cdn-01.goldapple.ru/p/p/36/{i}/fullhd.webp" for i in range(10)) + "\n"
                              "отзывы: goldapple_reviews\n\n" + description[:2500])
        self.assertEqual(capture.call_args.args, (tab, "goldapple", CARD_URL + "?utm_source=x",
                                                  {"c": ["/front/api/catalog/product-card/base/v3", "19000163536"],
                                                   "deliv": ["/web/api/v1/delivery/calculate/item"]}))
        tab.close.assert_called_once()

    def test_full_description(self):
        self.assertTrue(self.item({"c": CARD}, full=True)[0].endswith("\n\nОписание: Лёгкий кушон\nПрименение: " + APPLY.strip()))

    def test_bare_card_by_relative_link(self):
        got, capture, _, _ = self.item({"c": {"itemId": "1"}}, "/1-x")
        self.assertEqual(capture.call_args.args[2], "https://goldapple.ru/1-x")
        self.assertEqual(got, "  ()\nhttps://goldapple.ru/1-x\nартикул: 1\nварианты: \nотзывы: goldapple_reviews\n\n")

    def test_this_variant_without_photos_gives_way_to_the_next_with_photos(self):
        card = {"itemId": "2", "variants": [{"itemId": "1", "imageUrls": [picture("1")]}, {"itemId": "2"}, {"itemId": "3", "imageUrls": [picture("3")]}]}
        self.assertIn("фото (shop_images): https://cdn-01.goldapple.ru/p/p/3/fullhd.jpg\n", self.item({"c": card}, "https://goldapple.ru/2-x")[0])

    def test_link_without_the_name_part(self):
        self.assertEqual(goldapple.item("19000163536"), "нужна ссылка на товар из goldapple_search: https://goldapple.ru/<артикул>-<название>")

    def test_blocked(self):
        got, _, tab, log = self.item({})
        self.assertEqual(got, goldapple.BLOCKED)
        self.assertEqual(log.warning.call_args.args, ("goldapple item %s: no product-card response", CARD_URL + "?utm_source=x"))
        tab.close.assert_called_once()


GA_REVIEWS = {"data": {
    "statistic": {"rating": 4.6, "allReviewsCount": 7274, "recommended": 89, "starStatistic": [{"star": 5, "percent": 80}, {"star": 1, "percent": 3}]},
    "gallery": {"mediaCount": 142},
    "listing": {"reviews": [
        {"submitDate": "2026-10-28T10:00:00+03:00", "stars": 5, "likes": 1, "username": "Покупатель Б.",
         "attributes": {"units": {"value": "7.5", "name": "г"}, "colors": {"value": picture("36"), "name": "0.5, Porcelain"}},
         "pros": "стойкий", "cons": "<b>мало</b>", "comment": "Беру&nbsp;снова", "imageUrls": [{"original": picture("r1")}, {}]},
        {"stars": 4, "comment": "", "attributes": {"size": {"value": "M"}}}]}}}
REVIEWS_HEAD = "дата\t★\tполезно\tвариант\tавтор\tтекст\tфото (shop_images)\n"


class GoldAppleReviewsTests(unittest.TestCase):
    def reviews(self, d, id_or_url="19000163536", **kw):
        tab = MagicMock()
        with patch.object(goldapple, "_ga_tab", return_value=tab), patch.object(goldapple, "_api", return_value=d) as api:
            return goldapple.reviews(id_or_url, **kw), api, tab

    def test_page_with_reviews(self):
        got, api, tab = self.reviews(GA_REVIEWS)
        self.assertEqual(got, "Золотое яблоко · артикул 19000163536: рейтинг 4.6, отзывов 7274, рекомендуют 89% · 5★ 80% 1★ 3%\n"
                              "страница 1 (по 20), сортировка useful; фото с отзывов всего: 142\n" + REVIEWS_HEAD +
                              f"2026-10-28\t5\t1\t7.5 г {picture('36')} 0.5, Porcelain\tПокупатель Б.\t+ стойкий | − мало | Беру снова\t"
                              "https://cdn-01.goldapple.ru/p/p/r1/fullhd.jpg \n"
                              "\t4\t\tM\t\t\t")
        self.assertEqual(api.call_args.args, (tab, "GET", "/front/api/review/listing/v3?locale=ru&itemId=19000163536&pageNumber=1&sortType=ByUsefulness"))
        tab.close.assert_called_once()

    def test_empty_page_with_photos_only(self):
        got, api, _ = self.reviews({}, "https://goldapple.ru/19000163536-cushion", sort="low", with_media=True, page=2)
        self.assertEqual(got, "Золотое яблоко · артикул 19000163536: рейтинг None, отзывов None, рекомендуют None% · \n"
                              "страница 2 (по 20), сортировка low, только с фото; фото с отзывов всего: 0\n" + REVIEWS_HEAD + "(отзывов нет)")
        self.assertTrue(api.call_args.args[2].endswith("&pageNumber=2&sortType=ByLowestStars&hasMedia=true"))

    def test_limit(self):
        self.assertEqual(len(self.reviews(GA_REVIEWS, limit=1)[0].splitlines()), 4)

    def test_blocked(self):
        got, _, tab = self.reviews(None)
        self.assertEqual(got, goldapple.BLOCKED)
        tab.close.assert_called_once()

    def test_bad_arguments(self):
        self.assertEqual(goldapple.reviews("кушон"), "нужен артикул или ссылка на товар Золотого яблока")
        self.assertEqual(goldapple.reviews("19000163536", sort="best"), "sort: одно из useful, new, high, low")


if __name__ == "__main__":
    unittest.main()
