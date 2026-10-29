"""ВкусВилл: the catalog API's JSON and the site's pages -> search results, the product card, reviews; the cart and
favorites, with the buttons add_to_cart and remove_from_cart would press on fake site pages and the request favorite
would send.  No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_vkusvill"""
import json
import re
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
                                   composition_extra="", extra=["скидка по карте", "на адрес пользователя: наличие не указано"]))

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
        self.assertEqual(got, "ВкусВилл · Хлеб: рейтинг — (0 оценок)\n"
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


NAME = "Кефир 3,2%, 1000 г"
MILK = {"777": {"q": 0.5, "price": 120.0, "total": 60.0, "name": "Сыр", "unit": None, "can": "N"}}


def sent(expr):
    """What a fetch() in a page script would send: (path, method, headers, form fields)."""
    def obj(text):          # a JS object literal of strings
        return {k: a or b for k, a, b in re.findall(r"'?([\w-]+)'?: (?:\"([^\"]*)\"|'([^']*)')", text)}
    path, method = re.search(r"fetch\('([^']+)', \{method: '(\w+)'", expr).groups()
    return (path, method, obj(re.search(r"headers: (\{.*?\})", expr).group(1)),
            obj(re.search(r"new URLSearchParams\((\{.*?\})\)", expr).group(1)))


class Site:
    """The site in the tab: the cart it keeps (read by its dropdown endpoint), the product page with the product's add
    button while it is not in the cart and its «+» once it is, the cart page with a «−» on the product's row, and the
    favorites. A click or a favorites request changes the site unless it ignores that one."""
    def __init__(self, qty=0, absent=(), ignored=(), favs=()):
        self.qty, self.absent, self.ignored, self.favs = qty, set(absent), set(ignored), list(favs)
        self.page, self.clicks, self.gotos, self.posts = None, [], [], []
        self.tab = MagicMock()
        self.tab.js.side_effect = self.js
        self.tab.goto.side_effect = self.goto

    def goto(self, url, site, wait_js=None):
        self.gotos.append((url, site, wait_js))
        self.page = url

    def buttons(self):
        shown = {"−"} if self.page == "https://vkusvill.ru/cart/" and self.qty else set()
        if self.page == "https://vkusvill.ru/goods/x-158/":
            shown = {"+"} if self.qty else {"add"}
        return shown - self.absent

    def js(self, expr, timeout=None):
        if expr == vkusvill.CART_JS:
            assert timeout == 40
            mine = {"158": {"q": float(self.qty), "price": 98.0, "total": 98.0 * self.qty, "name": "Кефир", "unit": "шт", "can": "Y"}}
            return {"basket": {**MILK, **(mine if self.qty else {})}, "totals": {}}
        if expr == vkusvill.FAV_JS:
            assert timeout == 40
            return [{"id": i, "name": "", "price": "", "rest": ""} for i in self.favs]
        if expr == "document.querySelector('h1')?.innerText || ''":
            return NAME
        if "fetch('/ajax/favorites/" in expr:
            path, method, headers, form = sent(expr)
            self.posts.append((path, method, headers, form))
            if "favorite" not in self.ignored:
                self.favs = [i for i in self.favs if i != form["id"]] + ([form["id"]] if form["command"] == "add" else [])
            return {"s": 200, "b": "{}"}
        assert "b.click()" in expr, expr
        button = "+" if ".Q_Up" in expr else "−" if ".Q_Down" in expr else "add"
        assert {"+": "basket--add[data-id='158']", "−": "basket--row[data-product-id='158'] .Q_Down",
                "add": "basket--add[data-id='158']"}[button] in expr, expr     # the product's own button, not another's
        if button not in self.buttons():
            return False
        self.clicks.append(button)
        if button not in self.ignored:
            self.qty += -1 if button == "−" else 1
        return True


def change(fn, site, *args):
    """fn(*args) on the fake site: (answer, buttons clicked, pages loaded, time.sleep calls); the tab is closed once."""
    with patch.object(vkusvill, "_tab", return_value=site.tab), patch.object(vkusvill, "_mcp") as api, \
            patch.object(vkusvill.time, "sleep") as sleep, patch.object(vkusvill, "log") as site.log:
        got = fn(*args)
    site.tab.close.assert_called_once()
    api.assert_not_called()
    return got, site.clicks, site.gotos, sleep.call_args_list


PRODUCT_PAGE = ("https://vkusvill.ru/goods/x-158/", "vkusvill", "!!document.querySelector('.js-delivery__basket--add')")
CART_PAGE = ("https://vkusvill.ru/cart/", "vkusvill", "document.readyState === 'complete'")
NOT_ADDED = f"ВкусВилл не положил «{NAME}» в корзину (нет в наличии на адрес пользователя?)"


class VkusvillAddToCartTests(unittest.TestCase):
    def test_add_presses_the_add_button_then_plus(self):
        got, clicks, gotos, _ = change(vkusvill.add_to_cart, Site(), "https://vkusvill.ru/goods/kefir-3-158/", 3)
        self.assertEqual((clicks, gotos), (["add", "+", "+"], [PRODUCT_PAGE]))
        self.assertEqual(got, f"в корзине ВкусВилла: {NAME} — 3")

    def test_add_on_top_of_the_cart_presses_plus(self):
        got, clicks, _, _ = change(vkusvill.add_to_cart, Site(qty=2), "158")
        self.assertEqual((got, clicks), (f"в корзине ВкусВилла: {NAME} — 3", ["+"]))

    def test_quantity_is_one_to_thirty(self):
        for quantity, presses in ((0, 1), (-3, 1), ("2", 2), (99, 30)):
            with self.subTest(quantity):
                got, clicks, _, _ = change(vkusvill.add_to_cart, Site(), "158", quantity)
                self.assertEqual((len(clicks), got), (presses, f"в корзине ВкусВилла: {NAME} — {presses}"))

    def test_add_button_the_site_ignores(self):
        got, clicks, _, sleeps = change(vkusvill.add_to_cart, Site(ignored=["add"]), "158", 2)
        self.assertEqual((got, clicks), (NOT_ADDED, ["add"]))
        self.assertEqual(sleeps, [call(1.5)] + [call(0.5)] * 14)      # it waits 7 s for the cart to change

    def test_no_add_button(self):
        got, clicks, _, _ = change(vkusvill.add_to_cart, Site(absent=["add"]), "158", 2)
        self.assertEqual((got, clicks), (NOT_ADDED, []))

    def test_no_plus_on_top_of_the_cart(self):
        got, clicks, _, _ = change(vkusvill.add_to_cart, Site(qty=1, absent=["+"]), "158")
        self.assertEqual((got, clicks), (NOT_ADDED, []))

    def test_not_an_id(self):
        with patch.object(vkusvill, "_tab") as tab, self.assertRaises(ValueError):
            vkusvill.add_to_cart("кефир")
        tab.assert_not_called()


class VkusvillRemoveFromCartTests(unittest.TestCase):
    def test_minus_on_the_cart_page_until_it_is_gone(self):
        got, clicks, gotos, sleeps = change(vkusvill.remove_from_cart, Site(qty=3), "https://vkusvill.ru/goods/kefir-3-158/")
        self.assertEqual((clicks, gotos), (["−"] * 3, [CART_PAGE]))
        self.assertEqual(sleeps[-1], call(5))                         # the site drops the line 4 s after the last «−»
        self.assertEqual(got, "убрано из корзины ВкусВилла: 158")

    def test_minus_the_site_ignores_is_pressed_forty_times(self):
        got, clicks, _, _ = change(vkusvill.remove_from_cart, Site(qty=2, ignored=["−"]), "158")
        self.assertEqual((got, clicks), ("не удалось убрать товар 158 из корзины ВкусВилла", ["−"] * 40))

    def test_no_minus(self):
        got, clicks, _, _ = change(vkusvill.remove_from_cart, Site(qty=1, absent=["−"]), "158")
        self.assertEqual((got, clicks), ("не удалось убрать товар 158 из корзины ВкусВилла", []))

    def test_not_in_the_cart(self):
        got, clicks, _, _ = change(vkusvill.remove_from_cart, Site(), "158")
        self.assertEqual((got, clicks), ("убрано из корзины ВкусВилла: 158", []))

    def test_not_an_id(self):
        with patch.object(vkusvill, "_tab") as tab, self.assertRaises(ValueError):
            vkusvill.remove_from_cart("кефир")
        tab.assert_not_called()


FAVORITES = ("/ajax/favorites/add-remove.php", "POST",
             {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"})


class VkusvillFavoriteTests(unittest.TestCase):
    def favorite(self, site, *args):
        got, _, gotos, _ = change(vkusvill.favorite, site, *args)
        self.assertEqual(gotos, [])
        return got, site.posts

    def test_add(self):
        got, posts = self.favorite(Site(favs=["5"]), "https://vkusvill.ru/goods/kefir-3-158/")
        self.assertEqual(posts, [FAVORITES + ({"id": "158", "xmlid": "158", "command": "add", "notNeedHtml": "false"},)])
        self.assertEqual(got, "в избранном ВкусВилла: 158")

    def test_remove(self):
        got, posts = self.favorite(Site(favs=["158", "5"]), "158", True)
        self.assertEqual(posts, [FAVORITES + ({"id": "158", "xmlid": "158", "command": "remove", "notNeedHtml": "false"},)])
        self.assertEqual(got, "убрано из избранного ВкусВилла: 158")

    def test_the_site_did_not_change(self):
        for favs, remove in (([], False), (["158"], True)):
            with self.subTest(remove=remove):
                site = Site(favs=favs, ignored=["favorite"])
                got, posts = self.favorite(site, "158", remove)
                self.assertEqual((got, len(posts)), ("ВкусВилл не изменил избранное", 1))
                site.log.warning.assert_called_once_with("vkusvill favorite %s %s: %s", "158", remove, {"s": 200, "b": "{}"})

    def test_not_an_id(self):
        with patch.object(vkusvill, "_tab") as tab, self.assertRaises(ValueError):
            vkusvill.favorite("кефир")
        tab.assert_not_called()


class VkusvillCartAndFavoritesTests(unittest.TestCase):
    def read(self, fn, answer):
        tab = MagicMock()
        tab.js.return_value = answer
        with patch.object(vkusvill, "_tab", return_value=tab):
            got = fn()
        tab.close.assert_called_once()
        tab.goto.assert_not_called()
        return got, tab.js.call_args_list

    def test_cart(self):
        basket = {"158": {"q": 2.0, "price": 98.0, "total": 196.0, "name": "Кефир", "unit": "шт", "can": "Y"}, **MILK,
                  "9": {"q": 1, "price": 50, "total": 50, "name": "Хлеб", "unit": "шт", "can": True},
                  "10": {"q": 3, "price": 10, "total": 30, "name": "Вода", "unit": "шт", "can": "true"}}
        got, js = self.read(vkusvill.cart, {"basket": basket, "totals": {"sum": 336}})
        self.assertEqual(js, [call(vkusvill.CART_JS, timeout=40)])
        self.assertEqual(got, "корзина ВкусВилла\nid\tкол-во\tцена ₽\tсумма ₽\tназвание\n"
                              "158\t2 шт\t98.0\t196.0\tКефир\n"
                              "777\t0.5 \t120.0\t60.0\tСыр — нельзя купить\n"
                              "9\t1 шт\t50\t50\tХлеб\n"
                              "10\t3 шт\t10\t30\tВода")

    def test_empty_cart(self):
        for answer in ({"basket": {}}, None):
            with self.subTest(answer):
                self.assertEqual(self.read(vkusvill.cart, answer)[0], "корзина ВкусВилла пуста")

    def test_favorites(self):
        got, js = self.read(vkusvill.favorites, [{"id": "158", "name": "Кефир", "price": "98", "rest": "В наличии"},
                                                 {"id": "5", "name": "Хлеб", "price": "", "rest": ""}])
        self.assertEqual(js, [call(vkusvill.FAV_JS, timeout=40)])
        self.assertEqual(got, "избранное ВкусВилла\nid\tцена ₽\tналичие\tназвание\n158\t98\tВ наличии\tКефир\n5\t\t\tХлеб")

    def test_no_favorites(self):
        for answer in ([], None):
            with self.subTest(answer):
                self.assertEqual(self.read(vkusvill.favorites, answer)[0], "избранное ВкусВилла пусто")


if __name__ == "__main__":
    unittest.main()
