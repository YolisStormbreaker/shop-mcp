"""ВкусВилл read paths: the catalog API's JSON and the site's pages -> search results, the product card, reviews.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_vkusvill"""
import json
import unittest
import urllib.error
from unittest.mock import MagicMock, call, patch

from grocery import vkusvill

FACETS = ["веган", "без добавленного сахара", "без сахара", "только вкусвилл", "без глютена", "без лактозы", "мало жира", "много белка"]
KEFIR = "https://vkusvill.ru/search/?type=products&q=%D0%BA%D0%B5%D1%84%D0%B8%D1%80"

# catalog API hits: grams, under a kilogram, by weight with no pack, over a kilogram, nothing at all
GRAMS = {"id": 158, "name": "Кефир 3,2%,&nbsp;1000 г", "brand": "ВкусВилл", "price": {"current": 98, "old": None},
         "weight": {"value": "1000", "unit": "г"}, "rating": {"average": 4.91234, "count": 77474},
         "url": "https://vkusvill.ru/goods/kefir-3-158/", "unit": "шт"}
UNDER_KG = {"id": 20028, "name": "Кефир 1%", "price": {"current": 95, "old": 107}, "weight": {"value": 0.9, "unit": "кг"},
            "rating": {"average": 4.8, "count": 10}, "slug": "kefir-1"}
BY_WEIGHT = {"id": 777, "name": "Сыр <b>весовой</b>", "price": {"current": 1200}, "unit": "кг"}
OVER_KG = {"id": 5, "name": "Картофель", "price": {"current": 50, "old": 60}, "weight": {"value": "2.5", "unit": "кг"}}
NOTHING = {"id": 6, "name": "Хлеб", "price": {}}


def row(pid, name, size, price, old=None, available=True, url=None, rating=None, reviews=None, brand=""):
    return {"id": pid, "name": name, "brand": brand, "size": size, "price": price, "old": old, "available": available,
            "url": url or f"https://vkusvill.ru/goods/x-{pid}/", "rating": rating, "reviews": reviews, "ean": None}


ROW_GRAMS = row("158", "Кефир 3,2%, 1000 г", "1000 г", 98, url="https://vkusvill.ru/goods/kefir-3-158/", rating=4.91, reviews=77474,
                brand="ВкусВилл")
ROW_UNDER_KG = row("20028", "Кефир 1%", "900 г", 95, 107, url="https://vkusvill.ru/goods/kefir-1-20028/", rating=4.8, reviews=10)
ROW_BY_WEIGHT = row("777", "Сыр весовой", "1 кг", 1200)
ROW_OVER_KG = row("5", "Картофель", "2.5 кг", 50, 60)
ROW_NOTHING = row("6", "Хлеб", "", None)


def page(items, total, more):
    return {"items": items, "meta": {"total": total, "has_more": more}}


def tab_with(answer):
    """A site tab whose page script returns `answer` (or raises it)."""
    tab = MagicMock()
    tab.js.side_effect = answer if isinstance(answer, Exception) else lambda *a, **k: answer
    return tab


class Calls:
    """Patches the module's I/O: the catalog API answers `api` in turn, the site tab is `tab` (or fails to open)."""
    def __init__(self, api=(), tab=None):
        self.api, self.tab = MagicMock(side_effect=list(api)), tab

    def __enter__(self):
        tab = patch.object(vkusvill, "_tab", side_effect=RuntimeError("no tab")) if self.tab is None else \
            patch.object(vkusvill, "_tab", return_value=self.tab)
        self.patches = [patch.object(vkusvill, "_mcp", self.api), tab, patch.object(vkusvill, "log")]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class VkusvillSearchTests(unittest.TestCase):
    def test_catalog_pages_with_stock_at_the_users_address(self):
        stock = {"cards": [["158", "В наличии 5 шт", 5], ["20028", "", 0], ["777", "Закончился", -1], ["999", "", 3]]}
        tab = tab_with(stock)
        with Calls([page([GRAMS, UNDER_KG], 49, True), page([BY_WEIGHT], 48, False)], tab) as c:
            got = vkusvill.search("кефир", limit=15)
        self.assertEqual(c.api.call_args_list, [
            call("vkusvill_products_search", {"q": "кефир", "page": 1, "limit": 10, "sort": "popularity", "vvonly": 0}),
            call("vkusvill_products_search", {"q": "кефир", "page": 2, "limit": 10, "sort": "popularity", "vvonly": 0})])
        self.assertIn(json.dumps(KEFIR), tab.js.call_args.args[0])
        tab.close.assert_called_once()
        self.assertEqual(got, {"items": [ROW_GRAMS, dict(ROW_UNDER_KG, available=False), dict(ROW_BY_WEIGHT, available=False)],
                               "total": 48, "note": "наличие — для адреса пользователя (по первым 24 товарам сайта)",
                               "facets": FACETS, "url": KEFIR})

    def test_unknown_tag_is_searched_as_text_sorted_by_discount_without_stock(self):
        with Calls([page([UNDER_KG, OVER_KG, NOTHING], 3, True)]) as c:
            got = vkusvill.search("кефир", tag="без лактозы", sort="discount", page=2, limit=5)
        self.assertEqual(c.api.call_args_list, [
            call("vkusvill_products_search", {"q": "кефир без лактозы", "page": 2, "limit": 10, "sort": "popularity", "vvonly": 0})])
        self.assertEqual(got, {"items": [ROW_NOTHING, ROW_OVER_KG, ROW_UNDER_KG], "total": 3,
                               "note": "«без лактозы» — фильтр разделов сайта, а не поиска: искал «кефир без лактозы» текстом",
                               "facets": FACETS,
                               "url": "https://vkusvill.ru/search/?type=products&q=%D0%BA%D0%B5%D1%84%D0%B8%D1%80+%D0%B1%D0%B5%D0%B7+"
                                      "%D0%BB%D0%B0%D0%BA%D1%82%D0%BE%D0%B7%D1%8B"})

    def test_limit_cuts_the_page_and_a_failed_stock_page_is_skipped(self):
        tab = tab_with(RuntimeError("page script failed"))
        with Calls([page([GRAMS, UNDER_KG], 2, False)], tab) as c:
            got = vkusvill.search("кефир", sort="price", limit=1)
        self.assertEqual(c.api.call_args.args[1]["sort"], "price_asc")
        tab.close.assert_called_once()
        self.assertEqual(got, {"items": [ROW_GRAMS], "total": 2, "note": "", "facets": FACETS, "url": KEFIR})

    def test_site_filter_reads_the_sites_search_page(self):
        cards = [{"id": "1", "name": "Кефир веганский", "size": "450 мл", "price": 150, "old": 180, "rest": "В наличии", "max": 3,
                  "rating": "4.7", "href": "/goods/kefir-1/"},
                 {"id": "2", "name": "Кефир 2", "size": "", "price": 0, "old": 0, "rest": "Нет в наличии", "max": -1, "rating": "",
                  "href": "https://vkusvill.ru/goods/k-2/"},
                 {"id": "3", "name": "Кефир 3", "size": "1 л", "price": 100, "old": 90, "rest": "", "max": 0, "rating": "", "href": ""}]
        url = KEFIR + "&F%5BDEF_5%5D=1&sf4=Y&sort=cat_search__CATALOG_3&rf4=Y&PAGEN_1=2"
        tab = tab_with(cards)
        with Calls([], tab) as c:
            got = vkusvill.search("кефир", tag="Веган", sort="price", page=2, limit=3)
        c.api.assert_not_called()
        self.assertIn(json.dumps(url), tab.js.call_args.args[0])
        tab.close.assert_called_once()
        self.assertEqual(got, {"items": [
            row("1", "Кефир веганский", "450 мл", 150, 180, url="https://vkusvill.ru/goods/kefir-1/", rating="4.7"),
            row("2", "Кефир 2", "", None, available=False, url="https://vkusvill.ru/goods/k-2/"),
            dict(row("3", "Кефир 3", "1 л", 100, available=False), url="")],
            "total": None, "note": "фильтр ВкусВилла «Веган», наличие — для адреса пользователя", "facets": FACETS, "url": url})

    def test_site_filter_page_without_cards(self):
        url = KEFIR + "&F%5BDEF_6%5D=1&sf4=Y&sort=cat_search__CATALOG_15"
        with Calls([], tab_with(None)):
            got = vkusvill.search("кефир", tag="без сахара", limit=1)
        self.assertEqual(got, {"items": [], "total": None, "note": "фильтр ВкусВилла «без сахара», наличие — для адреса пользователя",
                               "facets": FACETS, "url": url})


FULL = {"id": 20028, "name": "Кефир 1% в бутылке, 900 г", "brand": "ВкусВилл", "url": "https://vkusvill.ru/goods/kefir-1-v-butylke-20028/",
        "price": {"current": 95, "old": 107, "discount_percent": 11, "discount_info": "по&nbsp;карте"},
        "weight": {"value": 900, "unit": "г"}, "rating": {"average": 4.8, "count": 55588},
        "properties": [
            {"name": "Состав", "value": "Молкомбинат ОАО: молоко нормализованное, закваска;<br>Гелиос ЗАО: молоко обезжиренное, закваска."
                                        "<br/><br>КОСМОЛ ООО: молоко цельное"},
            {"name": "Пищевая и энергетическая ценность", "value": "Белки 3 г, жиры 1 г, углеводы 4 г, в т.ч. сахара 4 г; 37 ккал"},
            {"name": "Аллергены по производителям", "value": "Гелиос ЗАО: молоко " + "о" * 300},
            {"name": "Срок годности", "value": "7 суток"}, {"name": "Страна производства", "value": ""},
            {"name": "<b>Изготовитель</b>", "value": "ЗАО Гелиос"}, {"name": "Вес", "value": None}],
        "images": [{"large": "https://img/1.webp"}, {"small": "https://img/s.webp"}, {"large": "https://img/2.webp"}],
        "description": "Кефир <i>пониженной</i> жирности"}
BARE = {"id": 91679, "name": "Сырок", "price": {"current": 69}}


class VkusvillProductTests(unittest.TestCase):
    def product(self, details, stock, id_or_url):
        with Calls([details], stock and tab_with(stock)) as c:
            got = vkusvill.product(id_or_url)
        return got, c.api

    def test_full_card_with_stock(self):
        stock = {"cards": [], "rest": "В наличии 17 шт", "max": 17, "delivery": "Сегодня за 30 минут"}
        got, api = self.product(FULL, stock, "https://vkusvill.ru/goods/kefir-1-v-butylke-20028/")
        api.assert_called_once_with("vkusvill_product_details", {"id": 20028})
        self.assertEqual(got, dict(
            row("20028", "Кефир 1% в бутылке, 900 г", "900 г", 95, 107, url="https://vkusvill.ru/goods/kefir-1-v-butylke-20028/",
                rating=4.8, reviews=55588, brand="ВкусВилл"),
            photos=["https://img/1.webp", "https://img/2.webp"], description="Кефир пониженной жирности",
            composition="молоко нормализованное, закваска",
            nutrition={"kcal": 37.0, "protein": 3.0, "fat": 1.0, "carbs": 4.0, "sugar": 4.0},
            composition_extra="Белки 3 г, жиры 1 г, углеводы 4 г, в т.ч. сахара 4 г; 37 ккал",
            extra=["скидка 11% по карте", "на адрес пользователя: В наличии 17 шт; доставка: Сегодня за 30 минут",
                   "поставщиков 3, у остальных состав: молоко обезжиренное, закваска. || молоко цельное",
                   "Аллергены по производителям: " + ("Гелиос ЗАО: молоко " + "о" * 300)[:200],
                   "Срок годности: 7 суток", "Изготовитель: ЗАО Гелиос"]))

    def test_bare_card_without_the_site(self):
        got, api = self.product(BARE, None, " 91679 ")
        api.assert_called_once_with("vkusvill_product_details", {"id": 91679})
        self.assertEqual(got, dict(row("91679", "Сырок", "", 69), photos=[], description="", composition="", nutrition={},
                                   composition_extra="", extra=[]))

    def test_discount_without_percent_one_supplier_and_stock_without_text(self):
        details = {"id": 5, "name": "Творог", "price": {"current": 50, "discount_info": "по карте"},
                   "properties": [{"name": "Состав", "value": "молоко, закваска"},
                                  {"name": "Пищевая ценность", "value": "Белки 18 г, жиры 9 г, углеводы 2 г; 160 ккал"}]}
        got, _ = self.product(details, {"rest": None, "max": 0, "delivery": ""}, "https://vkusvill.ru/goods/tvorog-5/?from=search")
        self.assertEqual(got, dict(row("5", "Творог", "", 50, available=False), photos=[], description="",
                                   composition="молоко, закваска", nutrition={"kcal": 160.0, "protein": 18.0, "fat": 9.0, "carbs": 2.0},
                                   composition_extra="", extra=["скидка % по карте", "на адрес пользователя: наличие не указано"]))

    def test_not_an_id(self):
        with Calls() as c:
            self.assertRaises(ValueError, vkusvill.product, "кефир")
        c.api.assert_not_called()


REVIEWS = "https://vkusvill.ru/ajax/product_comments/from_api/comments_load_page_v3.php?"


class VkusvillReviewsTests(unittest.TestCase):
    def reviews(self, answer, details, *args, **kw):
        tab = tab_with(answer)
        with Calls([details], tab):
            got = vkusvill.reviews(*args, **kw)
        tab.close.assert_called_once()
        return got, tab.js.call_args.args[0]

    def test_first_page_with_more(self):
        answer = {"more": True, "items": [{"date": "11 сен 2026", "rate": "1", "likes": "8", "text": "Жидкий"},
                                          {"date": "26 июл 2026", "rate": 5, "likes": "", "text": "Хороший"}]}
        got, script = self.reviews(answer, GRAMS, "https://vkusvill.ru/goods/kefir-3-158/")
        self.assertIn(json.dumps(REVIEWS + "id=158&sort=pr__likes_max&brand=&filter=0&page=1&isInited=N"), script)
        self.assertEqual(got, "ВкусВилл · Кефир 3,2%, 1000 г: рейтинг 4.91 (77474 оценок)\n"
                              "страница 1 по 10, сортировка useful; фото в отзывах ВкусВилла нет; есть ещё: page=2\n"
                              "дата\t★\tполезно\tтекст\n11 сен 2026\t1\t8\tЖидкий\n26 июл 2026\t5\t\tХороший")

    def test_later_page_without_reviews(self):
        got, script = self.reviews(None, NOTHING, "6", sort="new", page=3)
        self.assertIn(json.dumps(REVIEWS + "id=6&sort=pr__comment_new&brand=&filter=0&page=3&isInited=Y"), script)
        self.assertEqual(got, "ВкусВилл · Хлеб: рейтинг None (None оценок)\n"
                              "страница 3 по 10, сортировка new; фото в отзывах ВкусВилла нет\n"
                              "дата\t★\tполезно\tтекст\n(отзывов нет)")

    def test_unknown_sort(self):
        with Calls() as c:
            self.assertEqual(vkusvill.reviews("158", sort="best"), "sort: одно из useful, new, high, low")
        c.api.assert_not_called()


def answer(data=None, error=None, sse=False):
    text = json.dumps({"ok": True, "data": data} if error is None else {"ok": False, "error": error})
    raw = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}})
    r = MagicMock()
    r.__enter__.return_value.read.return_value = (f"event: message\ndata: {raw}\n\n" if sse else raw).encode()
    return r


def http(code, headers=None):
    return urllib.error.HTTPError(vkusvill.MCP, code, "error", headers or {}, None)


class VkusvillApiTests(unittest.TestCase):
    def call(self, *answers):
        with patch.object(vkusvill.urllib.request, "urlopen", side_effect=list(answers)) as urlopen, \
                patch.object(vkusvill.time, "sleep") as sleep:
            try:
                return vkusvill._mcp("vkusvill_product_details", {"id": 1}), urlopen, sleep
            except RuntimeError as e:
                return str(e), urlopen, sleep

    def test_json_answer(self):
        got, urlopen, sleep = self.call(answer({"id": 1}))
        req = urlopen.call_args.args[0]
        self.assertEqual((req.full_url, req.get_header("User-agent"), urlopen.call_args.kwargs), (vkusvill.MCP, "shop-mcp/1.0", {"timeout": 30}))
        self.assertEqual(json.loads(req.data), {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                "params": {"name": "vkusvill_product_details", "arguments": {"id": 1}}})
        self.assertEqual(got, {"id": 1})
        sleep.assert_not_called()

    def test_event_stream_answer(self):
        self.assertEqual(self.call(answer({"id": 2}, sse=True))[0], {"id": 2})

    def test_api_error(self):
        self.assertEqual(self.call(answer(error="нет товара"))[0], "ВкусВилл API: нет товара")

    def test_rate_limit_waits_and_retries_once(self):
        got, urlopen, sleep = self.call(http(429, {"X-RateLimit-Reset": "120"}), answer({"id": 3}))
        self.assertEqual((got, urlopen.call_count), ({"id": 3}, 2))
        sleep.assert_called_once_with(60)

    def test_rate_limit_twice(self):
        got, urlopen, sleep = self.call(http(429), http(429))
        self.assertEqual((got, urlopen.call_count), ("ВкусВилл API: HTTP 429", 2))
        sleep.assert_called_once_with(20)

    def test_server_error(self):
        got, urlopen, sleep = self.call(http(500))
        self.assertEqual((got, urlopen.call_count), ("ВкусВилл API: HTTP 500", 1))
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
