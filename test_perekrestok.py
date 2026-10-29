"""Перекрёсток read paths: the site's API answers -> search results, the product card, the review list; the API
client's retry and cache; the tab it runs in; the cart and favorites: what they would send and say.  No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_perekrestok"""
import copy
import unittest
from unittest.mock import MagicMock, patch

from grocery import perekrestok as pk

SITE = "https://www.perekrestok.ru"


def run(fn, answers, *args, **kw):
    """fn(*args) with the site answering answers[path] (a value, or a function of the request body)."""
    calls = []

    def call(tab, method, path, body=None):
        calls.append((method, path, body))
        a = answers.get(path.split("?")[0])
        return copy.deepcopy(a(body) if callable(a) else a)

    tab = MagicMock()
    with patch.object(pk, "_tab", return_value=tab), patch.object(pk, "_call", side_effect=call), patch.dict(pk._cache, clear=True):
        got = fn(*args, **kw)
    tab.close.assert_called_once()
    return got, calls


# --- product -----------------------------------------------------------------------------------------------------

FULL = {
    "title": "Кефир 2,5%, 930г", "balanceState": "in-stock", "balanceStock": 5, "rating": 495, "ratingCount": 24100, "reviewCount": 883,
    "masterData": {"plu": 2093082, "slug": "kefir-2-5-930g", "weight": 930, "unitName": "шт"}, "catalogPrimaryCategory": {"id": 1589},
    "priceTag": {"price": 10999, "grossPrice": 14999, "labels": [{"text": "-26%"}, {"text": ""}, {}, {"text": "2 по цене 1"}]},
    "medianPrice": 12999, "description": "Кефир из молока",
    "images": [{"cropUrlTemplate": "https://img/%s/1.jpg"}, {}, {"cropUrlTemplate": "https://img/%s/2.jpg"}],
    "features": [
        {"title": "Состав", "items": [{"key": "sostav", "title": "Состав", "values": ["молоко, закваска"], "displayValues": ["молоко, закваска"]}]},
        {"title": "Пищевая ценность на 100 г", "items": [
            {"key": "kkal", "title": "Ккал", "values": ["51000"], "displayValues": ["51"]}, {"key": "belki", "values": ["3000"]},
            {"key": "jiry", "values": ["2500"]}, {"key": "uglevody", "values": [""]}, {"key": "sahar", "values": ["4000"]}, {"key": "kletchatka"}]},
        {"title": "Основные", "items": [
            {"key": "brand", "title": "Бренд", "displayValues": ["Простоквашино"]}, {"key": "zhirnost", "title": "Жирность, %", "displayValues": ["до 2,5%"]},
            {"key": "strana", "displayValues": ["Россия", "Беларусь"]}, {"key": "pusto", "title": "Пусто", "displayValues": []}]},
        {"items": [{"key": "kakao", "title": "Какао, %", "displayValues": ["30"]}]},
    ],
}
DELIVERY = {"tabs": [
    {"type": "catalog", "title": "Каталог", "costString": "-"},
    {"type": "standard", "title": "Стандарт", "costString": "Доставка 99 ₽", "congestion": {"deliveryRange": "сегодня 18–20"}, "minCost": 100000},
    {"type": "express", "cost": 29900, "congestion": {}},
    {"type": "pickup", "title": "Самовывоз", "costString": "Бесплатно,"},
    {"type": "nocost"},
    {"type": "later", "congestion": {"deliveryRange": "завтра"}},
]}
WEIGHED = {"masterData": {"plu": 42, "unitName": "кг", "quantum": 500, "weight": 1000}, "priceTag": {"price": 50000}, "balanceState": "sold-out"}


class ProductTests(unittest.TestCase):
    def test_full_card(self):
        got, calls = run(pk.product, {"/catalog/product/plu2093082": FULL, "/delivery/switcher": DELIVERY},
                         f"{SITE}/cat/1589/p/kefir-2-5-930g-2093082")
        self.assertEqual(calls, [("get", "/catalog/product/plu2093082", None), ("get", "/delivery/switcher", None)])
        self.assertEqual(got, {
            "id": "2093082", "name": "Кефир 2,5%, 930г", "brand": "Простоквашино", "size": "930 г", "price": 109.99, "old": 149.99,
            "available": True, "url": f"{SITE}/cat/1589/p/kefir-2-5-930g-2093082", "rating": 4.95, "reviews": 883, "ean": None,
            "photos": ["https://img/800x800-fit/1.jpg", "https://img/800x800-fit/2.jpg"], "description": "Кефир из молока",
            "composition": "молоко, закваска", "nutrition": {"kcal": 51.0, "protein": 3.0, "fat": 2.5},
            "composition_extra": "Жирность, %: до 2,5%; Какао, %: 30",
            "extra": ["акции: -26%; 2 по цене 1",
                      "обычная цена (медиана): 129.99 ₽",
                      "доставка на адрес из профиля: Стандарт: Доставка 99 ₽, сегодня 18–20, заказ от 1000.0 ₽; express: 299.0 ₽; "
                      "Самовывоз: Бесплатно; nocost; later: завтра",
                      "характеристики: Жирность, %: до 2,5%; strana: Россия, Беларусь; Какао, %: 30"]})

    def test_weighed_card_without_extras(self):
        got, _ = run(pk.product, {"/catalog/product/plu42": WEIGHED, "/delivery/switcher": None}, "42")
        self.assertEqual(got, {
            "id": "42", "name": "", "brand": "", "size": "1 кг", "price": 500.0, "old": None, "available": False,
            "url": f"{SITE}/cat/search?search=42", "rating": None, "reviews": None, "ean": None, "photos": [], "description": "",
            "composition": "", "nutrition": {}, "composition_extra": "",
            "extra": ["весовой товар: цена за кг, шаг продажи 0.5 кг (≈ 250 ₽ за шаг)"]})

    def test_weighed_card_without_a_price(self):
        got, _ = run(pk.product, {"/catalog/product/plu42": {**WEIGHED, "priceTag": {}}}, "42")
        self.assertEqual((got["price"], got["extra"]), (None, ["весовой товар: цена за кг, шаг продажи 0.5 кг"]))

    def test_labels_without_text(self):
        card = {"masterData": {"plu": 7}, "priceTag": {"labels": [{}]}, "features": [{"title": "Состав", "items": [{"key": "sostav"}]}]}
        got, _ = run(pk.product, {"/catalog/product/plu7": card, "/delivery/switcher": {}}, "plu7")
        self.assertEqual((got["composition"], got["extra"]), ("", []))

    def test_unknown_product(self):
        self.assertEqual(run(pk.product, {"/catalog/product/plu5": {"__error": 404}}, "5")[0], "Перекрёсток: товар 5 не найден")

    def test_site_did_not_answer(self):
        self.assertEqual(run(pk.product, {"/catalog/product/plu5": {"__error": 500}}, "5")[0], pk.BLOCKED)
        self.assertEqual(run(pk.product, {}, "5")[0], pk.BLOCKED)

    def test_not_a_plu(self):
        with self.assertRaises(ValueError):
            pk.product("кефир")


# --- search ------------------------------------------------------------------------------------------------------

FORM = {"productCount": 62, "searchFeatures": [
    {"key": "brand", "enumList": [{"title": "Простоквашино", "value": "prostokvashino"}]},
    {"key": "category", "enumList": [{"title": f"Вид {i}", "value": f"v{i}"} for i in range(30)]},
    {"key": "osobennosti", "enumList": [{"title": "Без лактозы", "value": "bez-laktozy"}, {"title": "Без сахара", "value": "bez-sahara"}]},
    {"key": "empty"},
]}
FACETS = ["Без лактозы", "Без сахара"] + [f"Вид {i}" for i in range(25)]
ITEMS = [
    {"title": "Кефир 2.5%", "masterData": {"plu": 2093082, "slug": "kefir", "volume": 930}, "catalogPrimaryCategory": {"id": 1589},
     "priceTag": {"price": 10999, "grossPrice": 14999}, "balanceState": "in-stock", "rating": 495, "ratingCount": 100},
    {"title": "Кефир 1%", "masterData": {"plu": 777, "slug": "kefir-1", "weight": 500}, "primaryCategory": {"id": 2}, "balanceStock": 0},
    {"plu": 555, "balanceState": "out-of-stock"},
]
LISTED = [
    {"id": "2093082", "name": "Кефир 2.5%", "brand": "", "size": "930 мл", "price": 109.99, "old": 149.99, "available": True,
     "url": f"{SITE}/cat/1589/p/kefir-2093082", "rating": 4.95, "reviews": 100, "ean": None},
    {"id": "777", "name": "Кефир 1%", "brand": "", "size": "500 г", "price": None, "old": None, "available": False,
     "url": f"{SITE}/cat/2/p/kefir-1-777", "rating": None, "reviews": None, "ean": None},
    {"id": "555", "name": "", "brand": "", "size": "", "price": None, "old": None, "available": False,
     "url": f"{SITE}/cat/search?search=", "rating": None, "reviews": None, "ean": None},
]


def site(feed, form=FORM, filtered=None):
    return {"/catalog/search/form": lambda body: filtered if "features" in body["filter"] else form, "/catalog/product/feed": feed}


class SearchTests(unittest.TestCase):
    def test_popular_first_page(self):
        got, calls = run(pk.search, site({"items": ITEMS, "paginator": {"nextPageExists": True}}), "кефир")
        self.assertEqual(calls, [
            ("post", "/catalog/search/form", {"filter": {"textQuery": "кефир"}, "disableBubbleUp": True, "sortByAlpha": True}),
            ("post", "/catalog/product/feed", {"page": 1, "perPage": 30, "filter": {"textQuery": "кефир"}, "withBestProductReviews": False})])
        self.assertEqual(got, {"items": LISTED, "total": 62, "note": "есть следующая страница: page=2", "facets": FACETS,
                               "url": f"{SITE}/cat/search?search=%D0%BA%D0%B5%D1%84%D0%B8%D1%80"})

    def test_tag_the_site_filters_by(self):
        got, calls = run(pk.search, site({"items": ITEMS[:1]}, filtered={"productCount": 7}), "кефир", tag="ЛАКТОЗ", limit=5)
        flt = {"textQuery": "кефир", "features": [{"key": "osobennosti", "value": "bez-laktozy"}]}
        self.assertEqual(calls[1:], [
            ("post", "/catalog/product/feed", {"page": 1, "perPage": 12, "filter": flt, "withBestProductReviews": False}),
            ("post", "/catalog/search/form", {"filter": flt, "disableBubbleUp": True, "sortByAlpha": True})])
        self.assertEqual((got["items"], got["total"], got["note"]), (LISTED[:1], 7, ""))

    def test_tag_without_a_filter_is_searched_as_text(self):
        got, calls = run(pk.search, site({"items": ITEMS, "paginator": {"nextPageExists": True}}, form=None), "кефир", tag="фермерский",
                         sort="price_desc", page=2, limit=60)
        self.assertEqual(calls[1:], [("post", "/catalog/product/feed", {
            "page": 2, "perPage": 48, "filter": {"textQuery": "кефир фермерский"}, "withBestProductReviews": False,
            "orderBy": "price", "orderDirection": "desc"})])
        self.assertEqual(got, {"items": LISTED, "total": None, "facets": [],
                               "note": "фильтра «фермерский» у Перекрёстка для этого запроса нет — искал «кефир фермерский» текстом\n"
                                       "есть следующая страница: page=3",
                               "url": f"{SITE}/cat/search?search=%D0%BA%D0%B5%D1%84%D0%B8%D1%80&orderBy=price&orderDirection=desc&page=2"})

    def test_limit_cuts_the_page(self):
        self.assertEqual(run(pk.search, site({"items": ITEMS}), "кефир", limit=2)[0]["items"], LISTED[:2])

    def test_site_did_not_answer(self):
        self.assertEqual(run(pk.search, site(None), "кефир")[0], pk.BLOCKED)
        self.assertEqual(run(pk.search, site({"__error": 403}), "кефир")[0], pk.BLOCKED)


# --- reviews -----------------------------------------------------------------------------------------------------

NOON = 1747915200           # 2025-05-22 12:00 UTC: the same date in any time zone
REVIEWS = {"items": [
    {"createdAt": NOON * 1000, "rating": 500, "username": "Покупатель", "comment": "Вкусный\n  густой ",
     "approvedImages": [{"cropUrlTemplate": "https://img/%s/r1.jpg"}, {}, {"cropUrlTemplate": "https://img/%s/r2.jpg"}]},
    {"createdAt": NOON, "rating": 450, "comment": "Норм"},
    {"createdAt": "2025-05-20T10:00:00+03:00", "rating": None},
    {},
], "paginator": {"nextPageExists": True}}
COUNT = {"total": 12, "five": 9, "four": 2, "one": 1}
HEADER = "дата\t★\tавтор\tтекст\tфото (shop_images)"


def answers(plu, count, page):
    return {f"/catalog/product/plu{plu}/review/count": count, f"/catalog/product/plu{plu}/review": page}


class ReviewsTests(unittest.TestCase):
    def test_first_page(self):
        got, calls = run(pk.reviews, answers(3922310, COUNT, REVIEWS), f"{SITE}/cat/1589/p/kefir-ekoniva-3922310/reviews")
        self.assertEqual([c[1] for c in calls], ["/catalog/product/plu3922310/review/count", "/catalog/product/plu3922310/review?page=1&perPage=40"])
        self.assertEqual(got.split("\n"), [
            "Перекрёсток · plu 3922310: отзывов 12 · 5★ 9 4★ 2 3★ 0 2★ 0 1★ 1",
            "страница 1 по 40, новые сверху (другой сортировки у сайта нет); есть ещё: page=2", HEADER,
            "2025-05-22\t5\tПокупатель\tВкусный густой\thttps://img/800x800-fit/r1.jpg https://img/800x800-fit/r2.jpg",
            "2025-05-22\t4.5\t\tНорм\t", "2025-05-20\t0\t\t\t", "\t0\t\t\t"])

    def test_low_stars_with_photos_only(self):
        got, calls = run(pk.reviews, answers(5, COUNT, REVIEWS), "5", sort="low", with_media=True, page=2, limit=10)
        self.assertEqual(calls[1][1], "/catalog/product/plu5/review?page=2&perPage=10&ratingFrom=100&ratingTo=200")
        self.assertEqual(got.split("\n")[1:], [
            "страница 2 по 10, только 1–2★, только с фото — из этой страницы; есть ещё: page=3", HEADER,
            "2025-05-22\t5\tПокупатель\tВкусный густой\thttps://img/800x800-fit/r1.jpg https://img/800x800-fit/r2.jpg"])

    def test_five_stars(self):
        got, calls = run(pk.reviews, answers(5, {}, {"items": []}), "5", sort="high")
        self.assertEqual(calls[1][1], "/catalog/product/plu5/review?page=1&perPage=40&ratingFrom=500&ratingTo=500")
        self.assertEqual(got.split("\n")[1], "страница 1 по 40, только 5★")

    def test_no_reviews(self):
        got, _ = run(pk.reviews, answers(5, None, None), "5", sort="new")
        self.assertEqual(got, "Перекрёсток · plu 5: отзывов ? · 5★ 0 4★ 0 3★ 0 2★ 0 1★ 0\nстраница 1 по 40, новые сверху\n"
                              f"{HEADER}\n(отзывов нет)")

    def test_unknown_sort(self):
        self.assertEqual(pk.reviews("5", sort="best"), "sort: одно из useful, new, high, low")


# --- the API client, its cache and its tab -----------------------------------------------------------------------

def api_tab(*replies, found=True, path="/"):
    """A tab whose site client answers replies in turn; after a reload FIND_API gives found, the page shows path."""
    tab, it = MagicMock(), iter(replies)
    tab.js.side_effect = lambda expr: (next(it) if expr.startswith("window.__shopApi.") else found if expr == pk.FIND_API
                                       else path if expr == "location.pathname" else None)
    return tab


class CallTests(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(pk.time, "sleep"), patch.object(pk, "log")):
            setattr(self, p.attribute, p.start())
            self.addCleanup(p.stop)

    def call(self, tab, *args):
        return pk._call(tab, *args)

    def test_answer_comes_back_parsed(self):
        tab = api_tab('{"items": [1]}')
        self.assertEqual(self.call(tab, "post", "/catalog/product/feed", {"page": 1}), {"items": [1]})
        self.assertTrue(tab.js.call_args.args[0].startswith('window.__shopApi.post("/catalog/product/feed", {"page": 1}).then('))
        tab.goto.assert_not_called()

    def test_calls_are_spaced(self):
        pk._last = pk.time.time()
        self.call(api_tab("null"), "get", "/basket")
        self.assertGreater(self.sleep.call_args.args[0], 1)

    def test_no_answer(self):
        tab = api_tab("")
        self.assertIsNone(self.call(tab, "get", "/basket"))
        self.assertTrue(tab.js.call_args.args[0].startswith('window.__shopApi.get("/basket").then('))

    def test_error_is_logged_and_returned(self):
        self.assertEqual(self.call(api_tab('{"__error": 500}'), "get", "/basket"), {"__error": 500})
        self.log.warning.assert_called_once_with("perekrestok %s %s: %s%s", "get", "/basket", 500, "")

    def test_stale_session_is_renewed_once(self):
        tab = api_tab('{"__error": 401}', '{"ok": 1}')
        self.assertEqual(self.call(tab, "get", "/basket"), {"ok": 1})
        tab.js.assert_any_call("delete window.__shopApi")
        # the wait ends on the bot-check page too, so a check is reported at once, not after goto's 30 s
        tab.goto.assert_called_once_with(SITE + "/", "perekrestok", wait_js="!!window.__LOADABLE_LOADED_CHUNKS__ && document.readyState === "
                                         "'complete' || location.pathname.includes('/xpvnsulc/')")

    def test_still_refused_after_renewal(self):
        tab = api_tab('{"__error": 403}', '{"__error": 403}')
        self.assertEqual(self.call(tab, "get", "/basket"), {"__error": 403})
        self.assertEqual(self.log.warning.call_args.args[-1], " again after reload")
        tab.goto.assert_called_once()

    def test_renewal_shows_the_bot_check(self):
        with self.assertRaisesRegex(RuntimeError, "ServicePipe"):
            self.call(api_tab('{"__error": 401}', found=False, path="/xpvnsulc/abc"), "get", "/basket")

    def test_renewal_finds_no_client(self):
        self.assertEqual(self.call(api_tab('{"__error": 401}', found=False, path=None), "get", "/basket"), {"__error": 401})


class CachedTests(unittest.TestCase):
    def cached(self, *answers, ttl=600):
        with patch.object(pk, "_call", side_effect=answers) as call, patch.dict(pk._cache, clear=True):
            got = [pk._cached("tab", "get", "/delivery/switcher", None, ttl) for _ in answers]
        return got, call.call_count

    def test_answer_is_kept(self):
        self.assertEqual(self.cached({"a": 1}, {"a": 2}), ([{"a": 1}, {"a": 1}], 1))

    def test_kept_answer_expires(self):
        self.assertEqual(self.cached({"a": 1}, {"a": 2}, ttl=-1), ([{"a": 1}, {"a": 2}], 2))

    def test_errors_are_not_kept(self):
        self.assertEqual(self.cached({"__error": 500}, None, {"a": 1}), ([{"__error": 500}, None, {"a": 1}], 3))


def page_tab(host, found, path="/"):
    tab, it = MagicMock(), iter(found)
    tab.js.side_effect = lambda expr: host if expr == "location.hostname" else next(it) if expr == pk.FIND_API else path
    return tab


class TabTests(unittest.TestCase):
    def tab(self, tab):
        with patch.object(pk, "tab_for", return_value=tab) as tab_for:
            got = pk._tab()
        tab_for.assert_called_once_with("perekrestok.ru")
        return got

    def test_tab_with_the_client_is_used_as_is(self):
        tab = page_tab("www.perekrestok.ru", [True])
        self.assertIs(self.tab(tab), tab)
        tab.goto.assert_not_called()

    def test_tab_elsewhere_loads_the_home_page(self):
        tab = page_tab(None, [True])
        self.assertIs(self.tab(tab), tab)
        tab.goto.assert_called_once_with(SITE + "/", "perekrestok", wait_js="!!window.__LOADABLE_LOADED_CHUNKS__ && document.readyState === "
                                         "'complete' || location.pathname.includes('/xpvnsulc/')")

    def test_bot_check(self):
        tab = page_tab("www.perekrestok.ru", [False, False], "/xpvnsulc/abc")
        with self.assertRaisesRegex(RuntimeError, "ServicePipe"):
            self.tab(tab)
        tab.close.assert_called_once()

    def test_no_client_on_the_home_page(self):
        tab = page_tab("www.perekrestok.ru", [False, False], None)
        with self.assertRaisesRegex(RuntimeError, "не отдал данные"):
            self.tab(tab)
        tab.close.assert_called_once()


class LineTests(unittest.TestCase):
    """_line reads the basket the cart calls answer with (those calls change the account and are not run here)."""
    BASKET = {"items": [{"product": None}, {"product": {"masterData": {"plu": 5}}, "quantity": 2}], "state": "too_cheap"}

    def test_line_and_minimum_order(self):
        self.assertEqual(pk._line({**self.BASKET, "disabledButtonTitle": "Ещё 300 ₽"}, "5"),
                         ({"product": {"masterData": {"plu": 5}}, "quantity": 2}, "до минимального заказа ещё 300 ₽"))

    def test_minimum_order_without_its_amount(self):
        self.assertEqual(pk._line(self.BASKET, 6), (None, "сумма меньше минимального заказа"))

    def test_basket_without_a_state(self):
        self.assertEqual(pk._line({}, 6), (None, ""))


# --- cart and favorites: what would be sent, against a model of the basket ---------------------------------------

KEFIR = {"id": 7001, "title": "Кефир 2,5%, 930г", "masterData": {"plu": 2093082}, "priceTag": {"price": 10999}}
BREAD = {"id": 7002, "title": "Хлеб", "masterData": {"plu": 42}, "balanceState": "sold-out"}


class Basket:
    """The site's basket: «+» puts one unit of a product in, deleting the line takes it out; every call answers
    the whole basket.  answers() gives run() the paths the cart code calls."""
    def __init__(self, kefir=0, bread=0, state=None, plus=None, delete=True):
        """plus: {n: answer} for the «+» calls that answer otherwise (the first is 1)."""
        self.lines, self.state, self.plus_answers, self.delete, self.pluses = {"7001": kefir, "7002": bread}, state or {}, plus or {}, delete, 0

    def view(self):
        items = [{"product": p, "quantity": self.lines[str(p["id"])], "price": 10999, "cost": 10999 * self.lines[str(p["id"])]}
                 for p in (KEFIR, BREAD) if self.lines[str(p["id"])]]
        return {"items": items, "totalCost": sum(i["cost"] for i in items), **self.state}

    def plus(self, _):
        self.pluses += 1
        if self.pluses in self.plus_answers:
            return self.plus_answers[self.pluses]
        self.lines["7001"] += 1
        return self.view()

    def remove(self, _):
        if self.delete:
            self.lines["7001"] = 0
        return {}

    def answers(self, basket=None):
        """basket: what GET /basket answers in turn instead of the basket itself (None there: the basket)."""
        reads = list(basket or [])
        return {"/catalog/product/plu2093082": KEFIR, "/basket/plu2093082/plus": self.plus, "/basket/item/7001": self.remove,
                "/basket": lambda _: (reads.pop(0) if reads else None) or self.view()}


PRODUCT = ("get", "/catalog/product/plu2093082", None)
PLUS = ("put", "/basket/plu2093082/plus", None)
BASKET = ("get", "/basket", None)


class CartTests(unittest.TestCase):
    def test_cart(self):
        got, calls = run(pk.cart, {"/basket": {"totalCost": 52998, "items": [
            {"product": KEFIR, "quantity": 2, "price": 10999, "cost": 21998}, {"product": BREAD, "quantity": 1, "price": 31000, "cost": 31000},
            {"product": {"title": "Без plu"}, "quantity": 1}, {}]}})
        self.assertEqual(calls, [BASKET])
        self.assertEqual(got, "корзина Перекрёстка, итого 529.98 ₽\nplu\tшт\tцена ₽\tсумма ₽\tназвание\tналичие\n"
                              "2093082\t2\t109.99\t219.98\tКефир 2,5%, 930г\t\n42\t1\t310.0\t310.0\tХлеб\tнет в наличии\n"
                              "\t1\tNone\tNone\tБез plu\t\n\t\tNone\tNone\t\t")

    def test_cart_without_a_total(self):
        got, _ = run(pk.cart, {"/basket": {"items": [{"product": KEFIR, "quantity": 1, "price": 10999, "cost": 10999}]}})
        self.assertEqual(got.split("\n")[0], "корзина Перекрёстка")

    def test_empty_cart(self):
        for answer in ({"items": []}, None):
            with self.subTest(answer):
                self.assertEqual(run(pk.cart, {"/basket": answer})[0], "корзина Перекрёстка пуста")

    def test_cart_that_did_not_come(self):
        self.assertEqual(run(pk.cart, {"/basket": {"__error": 403}})[0], pk.BLOCKED)


class AddToCartTests(unittest.TestCase):
    def test_plus_once_per_unit(self):
        basket = Basket()
        got, calls = run(pk.add_to_cart, basket.answers(), f"{SITE}/cat/1589/p/kefir-2-5-930g-2093082", 2)
        self.assertEqual(calls, [PRODUCT, PLUS, PLUS])
        self.assertEqual(got, "в корзине Перекрёстка: Кефир 2,5%, 930г — 2 шт × 109.99 ₽ = 219.98 ₽")

    def test_under_the_minimum_order(self):
        got, _ = run(pk.add_to_cart, Basket(kefir=1, state={"state": "too_cheap", "disabledButtonTitle": "Ещё 300 ₽"}).answers(), "2093082")
        self.assertEqual(got, "в корзине Перекрёстка: Кефир 2,5%, 930г — 2 шт × 109.99 ₽ = 219.98 ₽\nдо минимального заказа ещё 300 ₽")

    def test_quantity_is_one_to_thirty_calls(self):
        for quantity, presses in ((0, 1), (-1, 1), ("3", 3), (31, 30)):
            with self.subTest(quantity):
                self.assertEqual(run(pk.add_to_cart, Basket().answers(), "2093082", quantity)[1], [PRODUCT] + [PLUS] * presses)

    def test_refused(self):
        for answer, said in (({"__error": 400}, "400"), (None, "None")):
            with self.subTest(said):
                got, calls = run(pk.add_to_cart, Basket(plus={1: answer}).answers(), "2093082", 3)
                self.assertEqual((got, calls), (f"Перекрёсток не положил Кефир 2,5%, 930г: {said}", [PRODUCT, PLUS]))

    def test_refused_halfway(self):
        got, calls = run(pk.add_to_cart, Basket(plus={3: {"__error": 400}}).answers(), "2093082", 5)
        self.assertEqual(got, "в корзине Перекрёстка: Кефир 2,5%, 930г — 2 шт × 109.99 ₽ = 219.98 ₽\n"
                              "положено 2 из 5, дальше Перекрёсток отказал: 400")
        self.assertEqual(calls, [PRODUCT, PLUS, PLUS, PLUS])

    def test_not_in_the_basket_after_all(self):
        got, _ = run(pk.add_to_cart, Basket(plus={1: {"items": []}}).answers(), "2093082")
        self.assertEqual(got, "Перекрёсток: Кефир 2,5%, 930г в корзине не появился (нет в наличии?)")

    def test_unknown_product(self):
        for answer in ({"__error": 404}, {"title": "без id"}, None):
            with self.subTest(answer), self.assertRaisesRegex(ValueError, "Перекрёсток: товар plu 5 не найден"):
                run(pk.add_to_cart, {"/catalog/product/plu5": answer}, "5")


class RemoveFromCartTests(unittest.TestCase):
    def test_line_is_deleted(self):
        basket = Basket(kefir=3, bread=1)
        got, calls = run(pk.remove_from_cart, basket.answers(), "2093082")
        self.assertEqual(calls, [PRODUCT, BASKET, ("delete", "/basket/item/7001", None), BASKET])
        self.assertEqual((got, basket.lines), ("убрано из корзины Перекрёстка: Кефир 2,5%, 930г", {"7001": 0, "7002": 1}))

    def test_not_in_the_cart(self):
        got, calls = run(pk.remove_from_cart, Basket(bread=1).answers(), "2093082")
        self.assertEqual((got, calls), ("Кефир 2,5%, 930г в корзине Перекрёстка нет", [PRODUCT, BASKET]))

    def test_still_there(self):
        got, _ = run(pk.remove_from_cart, Basket(kefir=1, delete=False).answers(), "2093082")
        self.assertEqual(got, "не удалось убрать Кефир 2,5%, 930г из корзины Перекрёстка")

    def test_basket_that_did_not_come(self):
        got, calls = run(pk.remove_from_cart, Basket(kefir=1).answers([{"__error": 500}]), "2093082")
        self.assertEqual((got, calls), (pk.BLOCKED, [PRODUCT, BASKET]))

    def test_basket_that_did_not_come_back(self):
        got, calls = run(pk.remove_from_cart, Basket(kefir=1, delete=False).answers([None, {"__error": 500}]), "2093082")
        self.assertEqual(got, "Кефир 2,5%, 930г: Перекрёсток не отдал корзину, и не видно, что получилось — проверь grocery_cart, "
                              "прежде чем повторять")
        self.assertEqual(calls, [PRODUCT, BASKET, ("delete", "/basket/item/7001", None), BASKET])


class FavoritesTests(unittest.TestCase):
    def test_favorites(self):
        got, calls = run(pk.favorites, {"/user/liked-product": {"items": [{"product": ITEMS[0]}, {"product": None}, {}, {"product": ITEMS[1]}]}})
        self.assertEqual(calls, [("get", "/user/liked-product?page=1&perPage=100", None)])
        self.assertEqual(got, "избранное Перекрёстка\nplu\tцена ₽\tналичие\tназвание\n2093082\t109.99\t\tКефир 2.5%\n777\tNone\tнет в наличии\tКефир 1%")

    def test_no_favorites(self):
        for answer in ({"items": [{}]}, None):
            with self.subTest(answer):
                self.assertEqual(run(pk.favorites, {"/user/liked-product": answer})[0], "избранное Перекрёстка пусто")

    def test_favorites_that_did_not_come(self):
        self.assertEqual(run(pk.favorites, {"/user/liked-product": {"__error": 403}})[0], pk.BLOCKED)


class FavoriteTests(unittest.TestCase):
    def test_add_and_remove(self):
        for remove, method, said in ((False, "post", "в избранном"), (True, "delete", "убрано из избранного")):
            with self.subTest(method):
                got, calls = run(pk.favorite, {"/catalog/product/plu2093082": KEFIR, "/user/liked-product/7001": None}, "2093082", remove)
                self.assertEqual(calls, [PRODUCT, (method, "/user/liked-product/7001", None)])
                self.assertEqual(got, f"{said} Перекрёстка: Кефир 2,5%, 930г")

    def test_refused(self):
        got, _ = run(pk.favorite, {"/catalog/product/plu2093082": KEFIR, "/user/liked-product/7001": {"__error": 500}}, "2093082")
        self.assertEqual(got, "Перекрёсток не изменил избранное: 500")

    def test_product_without_a_title(self):
        got, _ = run(pk.favorite, {"/catalog/product/plu5": {"id": 9}, "/user/liked-product/9": {}}, "5")
        self.assertEqual(got, "в избранном Перекрёстка: ")

    def test_unknown_product(self):
        with self.assertRaisesRegex(ValueError, "Перекрёсток: товар plu 5 не найден"):
            run(pk.favorite, {"/catalog/product/plu5": {"__error": 404}}, "5")


if __name__ == "__main__":
    unittest.main()
