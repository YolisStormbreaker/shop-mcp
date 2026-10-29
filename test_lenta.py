"""Лента search, product card and reviews: what the page's own requests answer -> the grocery dicts and text; the cart and
favorites: which of the page's buttons are pressed and what is said.
No requests to shops: site_tab and capture are fakes.  Run: .venv/bin/python -B -m unittest -v test_lenta"""
import json
import re
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from grocery import lenta

ITEM = {"id": 84812, "slug": "kefir-25-930g", "name": "кефир", "display": {"name": "Кефир 2,5%", "package": "930 г"},
        "prices": {"price": 10999, "priceRegular": 12499, "cost": 11827}, "features": {"isWeight": False}, "count": 1,
        "rating": {"rate": 4.9, "votes": 2846}}
WEIGHED = {"id": 3001, "slug": "banany", "display": {"name": "Бананы"}, "prices": {"price": 8999, "priceRegular": 8999, "cost": 17998},
           "features": {"isWeight": True}, "units": {"saleUnitQuantity": 0.5}, "count": 0}
ITEM_ROW = {"id": "84812", "name": "Кефир 2,5%", "brand": "", "size": "930 г", "price": 109.99, "old": 124.99, "available": True,
            "url": "https://lenta.com/product/kefir-25-930g-84812/", "rating": 4.9, "reviews": 2846, "ean": None}
WEIGHED_ROW = {"id": "3001", "name": "Бананы", "brand": "", "size": "0.5 кг", "price": 89.99, "old": None, "available": False,
               "url": "https://lenta.com/product/banany-3001/", "rating": None, "reviews": None, "ean": None}
FOUND = {"total": 47, "items": [ITEM, WEIGHED], "filters": {"multicheckbox": [
    {"key": "brand", "name": "Бренд", "values": [{"id": 1, "value": "Простоквашино"}]},
    {"key": "taste", "name": "Вкус", "values": [{"id": 7, "value": "Клубника"}, {"id": 8, "value": "Малина"}]},
    {"key": "fat", "name": "Жирность, %", "values": [{"id": i, "value": v} for i, v in enumerate([2.5, 1, 3.2, 2.9, 0, 4, 6])]},
    {"key": "rating", "name": "Рейтинг", "values": [{"id": 5, "value": 4}]},
    {"key": "empty", "name": "Пусто", "values": []}]}}
FACETS = list(lenta.DIET) + ["Вкус: Клубника / Малина", "Жирность, %: 2.5 / 1 / 3.2 / 2.9 / 0 / 4"]
STRAWBERRY = {"total": 2, "items": [ITEM]}
KEFIR = "/search/%D0%BA%D0%B5%D1%84%D0%B8%D1%80/"

CARD = dict(ITEM, count=167, attributes=[
    {"id": 232, "name": "Состав", "value": "молоко нормализованное, закваска"},
    {"id": 233, "name": "Пищевая ценность", "value": "белки 3 г, жиры 2,5 г, углеводы 4 г"},
    {"id": 234, "name": "Энергетическая ценность", "value": "51 ккал"},
    {"id": 242, "name": "Описание", "value": "<p>Кефир <b>свежий</b></p>"},
    {"id": 84, "name": "Бренд", "value": "ПРОСТОКВАШИНО", "alias": "brand"},
    {"id": 238, "name": "Срок", "value": "10 суток"}, {"id": 236, "name": "Код", "value": "4600"},
    {"id": 10, "name": "Веганское", "value": "Нет"}, {"id": 11, "name": "Содержание лактозы", "value": "Да"},
    {"id": 12, "name": "Производитель", "value": "АО «Молоко»", "alias": "manufacturer"}, {"id": 13, "name": "Пусто", "value": ""}],
    badges={"discount": [{"title": "-12%"}, {"title": ""}], "other": [{"title": "хит"}]},
    images=[{"large": "https://img/l1.png", "original": "https://img/o1.png"}, {"original": "https://img/o2.png"}, {}],
    reviews=[{"rating": 5, "text": "  Вкусный\n кефир "}, {"rating": 4, "text": ""}, {"rating": 3, "text": "х" * 250}])
ZONES = [{"name": "Супер Лента", "selected": False, "time": "~ 2 часа", "min": 500, "prices": [[199, 500]]},
         {"name": "Гипер Лента", "selected": True, "time": "~ 40 минут", "min": 1000, "prices": [[79, 1000], [0, 4300]]}]
CARD_DICT = dict(ITEM_ROW, brand="ПРОСТОКВАШИНО", photos=["https://img/l1.png", "https://img/o2.png"], description="Кефир  свежий",
                 composition="молоко нормализованное, закваска", nutrition={"kcal": 51.0, "protein": 3.0, "fat": 2.5, "carbs": 4.0},
                 composition_extra="Веганское: Нет; Содержание лактозы: Да",
                 extra=["скидка -12%", "в наличии до 167 шт",
                        "доставка: Гипер Лента ~ 40 минут, заказ от 1000 ₽, доставка 79 ₽ от 1000 ₽, 0 ₽ от 4300 ₽",
                        "характеристики: Веганское: Нет; Содержание лактозы: Да; Производитель: АО «Молоко»",
                        "отзывы (первые 2, ещё — grocery_reviews): 5★ Вкусный кефир | 3★ " + "х" * 200])
BARE = {"id": 5, "name": "Вода", "attributes": [{"id": 1, "name": "Состав", "alias": "ingredients", "value": "вода"}]}
BARE_DICT = {"id": "5", "name": "Вода", "brand": "", "size": "", "price": None, "old": None, "available": False,
             "url": "https://lenta.com/product/x-5/", "rating": None, "reviews": None, "ean": None, "photos": [], "description": "",
             "composition": "вода", "nutrition": {}, "composition_extra": "", "extra": ["характеристики: Состав: вода"]}


def fake_tab(here="/", zones=None, card=None):
    """The page: its path, the delivery zones and the server-rendered card in ng-state."""
    tab = MagicMock()
    tab.js.side_effect = lambda expr: here if expr == "location.pathname" else zones if expr == lenta.ZONES_JS else \
        card if "ng-state" in expr else None
    return tab


@contextmanager
def site(tabs, answers):
    """capture() answers the next of answers ({name: JSON}); sent collects (path navigated to, our request body)."""
    sent, answers = [], list(answers)

    def capture(tab, site, url, patterns, timeout=20, rewrite=None, js=None):
        body = rewrite and json.loads(rewrite[1]("https://lenta.com" + lenta.ITEMS[1:])[1])
        sent.append((json.loads(re.search(r"'', (\".*?\")\)", js).group(1)), patterns, body))
        a = answers.pop(0)
        return {k: v for k, v in a.items() if v is not None}

    with patch.object(lenta, "site_tab", side_effect=tabs), patch.object(lenta, "capture", side_effect=capture), \
            patch.object(lenta, "time") as clock, patch.object(lenta, "log") as log:
        yield sent, clock, log


def body(query="кефир", mc=(), sort=("popular", "desc"), limit=30, offset=0, **cat):
    return dict({"query": query, "filters": {"checkbox": [], "multicheckbox": list(mc), "range": []},
                 "sort": {"type": sort[0], "order": sort[1]}, "limit": limit, "offset": offset}, **cat)


class LentaSearchTests(unittest.TestCase):
    def search(self, answers, *args, here="/", **kw):
        tab = fake_tab(here)
        with site([tab], [{"s": a} for a in answers]) as (sent, _, _):
            got = lenta.search(*args, **kw)
        tab.close.assert_called_once()
        return got, [(path, b) for path, _, b in sent]

    def test_query(self):
        got, sent = self.search([FOUND], "кефир", limit=5)
        self.assertEqual(sent, [(KEFIR, body(limit=5))])
        self.assertEqual(got, {"items": [ITEM_ROW, WEIGHED_ROW], "total": 47, "note": "есть следующая страница: page=2",
                               "facets": FACETS, "url": "https://lenta.com" + KEFIR})

    def test_the_same_query_again_changes_the_path_so_the_app_searches(self):
        _, sent = self.search([FOUND], "кефир", here=KEFIR)
        self.assertEqual(sent[0][0], KEFIR[:-1] + "%20/")

    def test_a_full_last_page_has_no_next(self):
        self.assertEqual(self.search([dict(FOUND, total=30)], "кефир")[0]["note"], "")

    def test_last_page_sort_and_limit_over_40(self):
        got, sent = self.search([FOUND], "кефир", sort="price_desc", page=2, limit=100)
        self.assertEqual(sent, [(KEFIR, body(sort=("price", "desc"), limit=40, offset=40))])
        self.assertEqual(got["note"], "")

    def test_empty_query_searches_goods(self):
        got, sent = self.search([{}], "")
        self.assertEqual(sent, [("/search/%D1%82%D0%BE%D0%B2%D0%B0%D1%80%D1%8B/", body(""))])
        self.assertEqual(got, {"items": [], "total": None, "note": "", "facets": list(lenta.DIET), "url": "https://lenta.com/search//"})

    def test_diet_tag_is_a_category(self):
        got, sent = self.search([FOUND], "кефир", tag="Веган", limit=5)
        self.assertEqual(sent, [(KEFIR, body(limit=5, categoryId=13616))])
        self.assertEqual(got["note"], "раздел Ленты «вегетарианское» + запрос «кефир»\nесть следующая страница: page=2")

    def test_tag_of_the_search_facets(self):
        got, sent = self.search([FOUND, STRAWBERRY], "кефир", tag="клубн", page=2, limit=10)
        self.assertEqual(sent, [(KEFIR, body(limit=10, offset=10)),
                                (KEFIR, body(mc=[{"key": "taste", "valueIds": [7]}], limit=10, offset=10))])
        self.assertEqual(got, {"items": [ITEM_ROW], "total": 2, "note": "фильтр Ленты «Вкус: Клубника»", "facets": list(lenta.DIET),
                               "url": "https://lenta.com" + KEFIR})

    def test_facet_search_without_answer_keeps_the_first(self):
        got, _ = self.search([FOUND, None], "кефир", tag="Малина", limit=50)
        self.assertEqual((got["items"], got["note"]), ([ITEM_ROW, WEIGHED_ROW], "фильтр Ленты «Вкус: Малина»\nесть следующая страница: page=2"))

    def test_unknown_tag_goes_into_the_text(self):
        got, sent = self.search([FOUND, STRAWBERRY], "кефир", tag="козий")
        self.assertEqual(sent[1], ("/search/%D0%BA%D0%B5%D1%84%D0%B8%D1%80%20%D0%BA%D0%BE%D0%B7%D0%B8%D0%B9/", body("кефир козий")))
        self.assertEqual((got["items"], got["note"]), ([ITEM_ROW], "тега «козий» у Ленты для этого запроса нет — искал «кефир козий» текстом"))

    def test_text_search_without_answer_keeps_the_first(self):
        got, _ = self.search([FOUND, None], "кефир", tag="козий")
        self.assertEqual(got["items"], [ITEM_ROW, WEIGHED_ROW])

    def test_no_answer(self):
        self.assertEqual(self.search([None], "кефир", tag="козий")[0], lenta.BLOCKED)


class CardSite(unittest.TestCase):
    def product(self, card, zones=ZONES, here="/", rendered=None, zones_rendered=None, fn=lenta.product, id_or_url="84812", **kw):
        tabs = [fake_tab(here, zones), fake_tab(zones=zones_rendered, card=rendered)]
        with site(tabs, [{"p": card}]) as (sent, clock, log):
            got = fn(id_or_url, **kw)
        self.sent, self.tabs, self.clock, self.log = sent, tabs, clock, log
        return got


class LentaProductTests(CardSite):
    def test_full_card(self):
        self.assertEqual(self.product(CARD), CARD_DICT)
        self.assertEqual(self.sent, [("/product/x-84812/", {"p": ["re:/api-gateway/v1/catalog/items/84812(\\?|$)"]}, None)])
        self.tabs[0].close.assert_called_once()
        self.tabs[1].close.assert_not_called()
        self.clock.sleep.assert_not_called()
        self.log.warning.assert_not_called()

    def test_weighed_card_from_a_link_with_every_zone_when_none_is_selected(self):
        zones = [dict(z, selected=False) for z in ZONES]
        got = self.product(dict(WEIGHED, rating={"rate": 4.5}), zones, id_or_url="https://lenta.com/product/banany-3001/?from=x")
        self.assertEqual(self.sent[0][0], "/product/x-3001/")
        self.assertEqual(got, dict(WEIGHED_ROW, rating=4.5, photos=[], description="", composition="", nutrition={}, composition_extra="", extra=[
            "весовой товар: 179.98 ₽/кг, шаг 0.5 кг",
            "доставка: Супер Лента ~ 2 часа, заказ от 500 ₽, доставка 199 ₽ от 500 ₽; "
            "Гипер Лента ~ 40 минут, заказ от 1000 ₽, доставка 79 ₽ от 1000 ₽, 0 ₽ от 4300 ₽"]))

    def test_another_card_is_left_by_going_to_this_one(self):
        self.product(CARD, here="/product/kefir-1-930g-69170/")
        self.assertEqual([c.args[0] for c in self.tabs[0].js.call_args_list], ["location.pathname", lenta.ZONES_JS])

    def test_the_same_card_again_leaves_it_first(self):
        self.product(CARD, here="/product/kefir-25-930g-84812/")
        self.assertEqual(self.tabs[0].js.call_args_list[1].args, (lenta.NAV_JS % '"/"',))
        self.clock.sleep.assert_called_once_with(1.5)

    def test_card_the_app_did_not_fetch_again_comes_from_a_full_load(self):
        self.assertEqual(self.product(None, zones=None, rendered=BARE, zones_rendered=None), BARE_DICT)
        self.tabs[1].goto.assert_called_once_with("https://lenta.com/product/x-84812/", "lenta", wait_js="!!document.getElementById('ng-state')")
        self.tabs[0].close.assert_called_once()
        self.tabs[1].close.assert_called_once()
        self.log.warning.assert_called_once()

    def test_full_load_keeps_the_zones_already_read(self):
        got = self.product(None, rendered=BARE, zones_rendered=[dict(ZONES[0], selected=True)])
        self.assertEqual(got["extra"][0], "доставка: Гипер Лента ~ 40 минут, заказ от 1000 ₽, доставка 79 ₽ от 1000 ₽, 0 ₽ от 4300 ₽")
        got = self.product(None, zones=[], rendered=BARE, zones_rendered=[dict(ZONES[0], selected=True)])
        self.assertEqual(got["extra"][0], "доставка: Супер Лента ~ 2 часа, заказ от 500 ₽, доставка 199 ₽ от 500 ₽")

    def test_no_card(self):
        self.assertEqual(self.product(None), "Лента: карточка 84812 не пришла (неверный id или проверка на бота)")
        self.assertEqual(self.product({"name": "?"}), "Лента: карточка 84812 не пришла (неверный id или проверка на бота)")

    def test_not_an_id(self):
        with self.assertRaises(ValueError):
            lenta.product("кефир")


class LentaReviewsTests(CardSite):
    def reviews(self, card, **kw):
        return self.product(card, fn=lenta.reviews, **kw)

    def test_reviews_come_with_the_card(self):
        self.assertEqual(self.reviews(CARD, sort="new", page=2), "Лента · Кефир 2,5%: рейтинг 4.9 (2846 оценок)\n"
                         "Лента отдаёт с карточкой 5 последних отзывов; фото в отзывах у Ленты нет\n"
                         "отзывы (первые 2, ещё — grocery_reviews): 5★ Вкусный кефир | 3★ " + "х" * 200)

    def test_no_reviews(self):
        self.assertEqual(self.reviews(BARE), "Лента · Вода: рейтинг — (0 оценок)\n"
                         "Лента отдаёт с карточкой 5 последних отзывов; фото в отзывах у Ленты нет\n(отзывов нет)")

    def test_reviews_without_text(self):
        got = self.reviews(dict(BARE, reviews=[{"rating": 4, "text": ""}, {"rating": 5}]))
        self.assertEqual(got.splitlines()[-1], "(отзывов нет)")

    def test_no_card(self):
        self.assertEqual(self.reviews(None), "Лента: карточка 84812 не пришла (неверный id или проверка на бота)")


class LentaCartLookupTests(unittest.TestCase):
    def test_goods_by_id_without_leading_zeros(self):
        cl = {"PositionsCount": 2, "Goods": [{"GoodsItemId": "052602", "Quantity": 2}, {"GoodsItemId": "000", "Quantity": 1}]}
        self.assertEqual(lenta._goods({"Body": {"CartList": [cl]}}),
                         ({"52602": {"GoodsItemId": "052602", "Quantity": 2}, "0": {"GoodsItemId": "000", "Quantity": 1}}, cl))

    def test_no_cart(self):
        self.assertEqual(lenta._goods(None), ({}, {}))
        self.assertEqual(lenta._goods({"Body": {"CartList": []}}), ({}, {}))


# --- cart and favorites: the page's own buttons, pressed in a model of the page ---------------------------------

PAGE = "https://lenta.com/product/x-84812/"
MODIFY = "/api/rest/cartItemModify"
BUTTONS = {lenta.ADD: "В корзину", lenta.INC: "+", lenta.DEC: "−", lenta.HEART: "♥"}
UNCHECKED = "Кефир 2,5%: Лента не отдала корзину, и не видно, что получилось — проверь grocery_cart, прежде чем повторять"
OTHER = {"GoodsItemId": "052602", "Quantity": 2, "Price": 250, "PriceTotal": 500, "Name": "Хлеб"}


class Shop:
    """The site as the cart code meets it.  A full load answers the cart (cartLookup) or the favorites list; the
    product page shows «В корзину» while the cart has none of it, «+» while there is stock left and «−» while the
    cart has some; a press changes the cart like the site does and answers.  sent: loads and presses in order."""
    def __init__(self, qty=0, stock=100, favs=(), card=True, lookup=(True,), faved=True, inert=False):
        """lookup: whether each full load in turn brings its answer (the last one goes for the loads after it)."""
        self.qty, self.stock, self.favs, self.card, self.lookup, self.faved, self.inert = qty, stock, list(favs), card, list(lookup), faved, inert
        self.sent, self.tab = [], MagicMock()
        self.tab.js.side_effect = self.js

    def js(self, expr):
        if expr == f"{lenta.CARD_JS}(\"84812\")":
            return {"name": "Кефир 2,5%", "fav": False, "count": self.stock} if self.card else None
        button = next(b for b in BUTTONS if expr == f"!!({b})")
        return {lenta.ADD: not self.qty and self.stock > 0, lenta.INC: 0 < self.qty < self.stock, lenta.DEC: self.qty > 0}[button]

    def capture(self, tab, site, url, patterns, timeout=20, js=None):
        assert (tab, site) == (self.tab, "lenta")
        if js is None:
            self.sent.append(url)
            if not (self.lookup.pop(0) if len(self.lookup) > 1 else self.lookup[0]):
                return {}
            if patterns == {"f": ["re:/catalog/items/favorites$"]}:
                return {"f": {"total": len(self.favs), "items": self.favs}}
            assert patterns == {"c": ["/api/rest/cartLookup"]}
            return {"c": self.cart()}
        button = next(b for b in BUTTONS if js == f"({b}).click()")
        [(what, [awaited])] = patterns.items()
        self.sent.append((BUTTONS[button], awaited))
        if not self.inert:
            self.press(button)
        return {what: {"result": self.faved}}

    def press(self, button):
        if button == lenta.HEART:
            self.favs = [p for p in self.favs if p["id"] != 84812] if any(p["id"] == 84812 for p in self.favs) else self.favs + [ITEM]
        else:
            self.qty += -1 if button == lenta.DEC else 1

    def cart(self):
        goods = [{"GoodsItemId": "084812", "Quantity": self.qty, "Price": 109.99, "PriceTotal": round(109.99 * self.qty, 2),
                  "Name": "Кефир 2,5%"}] if self.qty > 0 else []
        return {"Body": {"CartList": [{"PositionsCount": len(goods) + 1, "TotalCost": round(500 + 109.99 * max(self.qty, 0), 2),
                                       "DeliveryPrice": 0, "Goods": [OTHER] + goods}]}}

    def run(self, fn, *args):
        with patch.object(lenta, "site_tab", return_value=self.tab), patch.object(lenta, "capture", side_effect=self.capture), \
                patch.object(lenta, "time"):
            got = fn(*args)
        self.tab.close.assert_called_once()
        return got


class LentaCartTests(unittest.TestCase):
    def test_cart(self):
        shop = Shop(qty=3)
        self.assertEqual(shop.run(lenta.cart), "корзина Ленты: позиций 2, итого 829.97 ₽, доставка 0 ₽\nid\tшт\tцена ₽\tсумма ₽\tназвание\n"
                                               "52602\t2\t250\t500\tХлеб\n84812\t3\t109.99\t329.97\tКефир 2,5%")
        self.assertEqual(shop.sent, ["https://lenta.com/"])

    def test_cart_without_delivery_price_and_line_fields(self):
        shop = Shop()
        shop.cart = lambda: {"Body": {"CartList": [{"PositionsCount": 1, "TotalCost": 100, "Goods": [{"GoodsItemId": "7"}]}]}}
        self.assertEqual(shop.run(lenta.cart), "корзина Ленты: позиций 1, итого 100 ₽\nid\tшт\tцена ₽\tсумма ₽\tназвание\n7\tNone\tNone\t\t")

    def test_empty_cart(self):
        shop = Shop()
        shop.cart = lambda: {"Body": {"CartList": [{"PositionsCount": 0, "TotalCost": 0, "Goods": []}]}}
        self.assertEqual(shop.run(lenta.cart), "корзина Ленты пуста")

    def test_cart_that_did_not_come(self):
        self.assertEqual(Shop(lookup=(False,)).run(lenta.cart), lenta.BLOCKED)


class LentaAddToCartTests(unittest.TestCase):
    def test_first_unit_by_the_add_button_then_plus(self):
        shop = Shop()
        self.assertEqual(shop.run(lenta.add_to_cart, "https://lenta.com/product/kefir-25-930g-84812/", 3),
                         "в корзине Ленты: Кефир 2,5% — 3 шт × 109.99 ₽; итого корзины 829.97 ₽")
        self.assertEqual(shop.sent, [PAGE, ("В корзину", MODIFY), ("+", MODIFY), ("+", MODIFY), PAGE])

    def test_already_in_the_cart_takes_plus(self):
        shop = Shop(qty=2)
        self.assertEqual(shop.run(lenta.add_to_cart, "84812"), "в корзине Ленты: Кефир 2,5% — 3 шт × 109.99 ₽; итого корзины 829.97 ₽")
        self.assertEqual(shop.sent, [PAGE, ("+", MODIFY), PAGE])

    def test_quantity_is_one_to_thirty_presses(self):
        for quantity, presses in ((0, 1), (-2, 1), ("2", 2), (100, 30)):
            with self.subTest(quantity):
                shop = Shop()
                shop.run(lenta.add_to_cart, "84812", quantity)
                self.assertEqual(len(shop.sent), presses + 2)

    def test_no_card(self):
        shop = Shop(card=False)
        self.assertEqual(shop.run(lenta.add_to_cart, "84812"), "Лента: товар 84812 не открылся")
        self.assertEqual(shop.sent, [PAGE])

    def test_out_of_stock_has_no_add_button(self):
        shop = Shop(stock=0)
        self.assertEqual(shop.run(lenta.add_to_cart, "84812"), "Лента: кнопки «В корзину» на странице Кефир 2,5% нет (нет в наличии?)")
        self.assertEqual(shop.sent, [PAGE])

    def test_plus_gone_at_the_stock_limit(self):
        shop = Shop(stock=2)
        self.assertEqual(shop.run(lenta.add_to_cart, "84812", 3), "Лента: кнопки «+» на странице Кефир 2,5% нет (нет в наличии?)")
        self.assertEqual(shop.sent, [PAGE, ("В корзину", MODIFY), ("+", MODIFY)])

    def test_presses_that_changed_nothing(self):
        shop = Shop(qty=1, inert=True)
        self.assertEqual(shop.run(lenta.add_to_cart, "84812"), "Лента не положила Кефир 2,5% в корзину")
        self.assertEqual(shop.sent, [PAGE, ("+", MODIFY), PAGE])

    def test_cart_that_did_not_come(self):
        shop = Shop(qty=1, lookup=(False,))
        self.assertEqual(shop.run(lenta.add_to_cart, "84812"), lenta.BLOCKED)
        self.assertEqual(shop.sent, [PAGE])

    def test_cart_that_did_not_come_back(self):
        shop = Shop(lookup=(True, False))
        self.assertEqual(shop.run(lenta.add_to_cart, "84812", 2), UNCHECKED)
        self.assertEqual(shop.sent, [PAGE, ("В корзину", MODIFY), ("+", MODIFY), PAGE])


class LentaRemoveFromCartTests(unittest.TestCase):
    def test_minus_until_the_line_is_gone(self):
        shop = Shop(qty=2)
        self.assertEqual(shop.run(lenta.remove_from_cart, "84812"), "убрано из корзины Ленты: Кефир 2,5%")
        self.assertEqual(shop.sent, [PAGE, ("−", MODIFY), ("−", MODIFY), PAGE])

    def test_not_in_the_cart(self):
        shop = Shop()
        self.assertEqual(shop.run(lenta.remove_from_cart, "84812"), "Кефир 2,5% в корзине Ленты нет")
        self.assertEqual(shop.sent, [PAGE])

    def test_without_the_card_the_id_names_it(self):
        shop = Shop(qty=1, card=False)
        self.assertEqual(shop.run(lenta.remove_from_cart, "84812"), "убрано из корзины Ленты: 84812")
        self.assertEqual(shop.sent, [PAGE, ("−", MODIFY), PAGE])

    def test_no_minus_button(self):
        shop = Shop(qty=1)
        shop.js = lambda expr: False if expr == f"!!({lenta.DEC})" else Shop.js(shop, expr)
        shop.tab.js.side_effect = shop.js
        self.assertEqual(shop.run(lenta.remove_from_cart, "84812"), "не удалось убрать Кефир 2,5% из корзины Ленты")
        self.assertEqual(shop.sent, [PAGE, PAGE])

    def test_at_most_thirty_presses(self):
        shop = Shop(qty=31)
        self.assertEqual(shop.run(lenta.remove_from_cart, "84812"), "не удалось убрать Кефир 2,5% из корзины Ленты")
        self.assertEqual(shop.sent, [PAGE] + [("−", MODIFY)] * 30 + [PAGE])

    def test_weighed_line_under_one_unit(self):
        shop = Shop(qty=0.5)
        self.assertEqual(shop.run(lenta.remove_from_cart, "84812"), "Кефир 2,5% в корзине Ленты нет")
        self.assertEqual(shop.sent, [PAGE])

    def test_cart_that_did_not_come(self):
        shop = Shop(qty=1, lookup=(False,))
        self.assertEqual(shop.run(lenta.remove_from_cart, "84812"), lenta.BLOCKED)
        self.assertEqual(shop.sent, [PAGE])

    def test_cart_that_did_not_come_back(self):
        shop = Shop(qty=1, lookup=(True, False))
        self.assertEqual(shop.run(lenta.remove_from_cart, "84812"), UNCHECKED)
        self.assertEqual(shop.sent, [PAGE, ("−", MODIFY), PAGE])


FAVORITES = "https://lenta.com/my-account/favorites/"


class LentaFavoritesTests(unittest.TestCase):
    def test_favorites(self):
        shop = Shop(favs=[ITEM, WEIGHED])
        self.assertEqual(shop.run(lenta.favorites), "избранное Ленты (2)\nid\tцена ₽\tналичие\tназвание\n"
                                                    "84812\t109.99\t\tКефир 2,5%\n3001\t89.99\tнет в наличии\tБананы")
        self.assertEqual(shop.sent, [FAVORITES])

    def test_no_favorites(self):
        self.assertEqual(Shop().run(lenta.favorites), "избранное Ленты пусто")

    def test_favorites_that_did_not_come(self):
        self.assertEqual(Shop(lookup=(False,)).run(lenta.favorites), "Лента не отдала избранное")


class LentaFavoriteTests(unittest.TestCase):
    def test_add(self):
        shop = Shop(favs=[WEIGHED])
        self.assertEqual(shop.run(lenta.favorite, "84812"), "в избранном Ленты: Кефир 2,5%")
        self.assertEqual(shop.sent, [FAVORITES, PAGE, ("♥", "/catalog/items/favorites/add")])
        self.assertEqual(shop.favs, [WEIGHED, ITEM])

    def test_remove(self):
        shop = Shop(favs=[ITEM, WEIGHED])
        self.assertEqual(shop.run(lenta.favorite, "84812", True), "убрано из избранного Ленты: Кефир 2,5%")
        self.assertEqual(shop.sent, [FAVORITES, PAGE, ("♥", "/catalog/items/favorites/delete")])
        self.assertEqual(shop.favs, [WEIGHED])

    def test_already_as_asked(self):
        for favs, remove, said in (([ITEM], False, "уже в избранном"), ([WEIGHED], True, "и так не в избранном")):
            with self.subTest(said):
                shop = Shop(favs=favs)
                self.assertEqual(shop.run(lenta.favorite, "84812", remove), f"Кефир 2,5% {said} Ленты")
                self.assertEqual(shop.sent, [FAVORITES, PAGE])

    def test_favorites_that_did_not_come(self):
        shop = Shop(lookup=(False,))
        self.assertEqual(shop.run(lenta.favorite, "84812"), "Лента не отдала избранное")
        self.assertEqual(shop.sent, [FAVORITES])

    def test_no_card(self):
        shop = Shop(card=False)
        self.assertEqual(shop.run(lenta.favorite, "84812"), "Лента: товар 84812 не открылся")
        self.assertEqual(shop.sent, [FAVORITES, PAGE])

    def test_site_did_not_change_it(self):
        shop = Shop(faved=False)
        self.assertEqual(shop.run(lenta.favorite, "84812"), "Лента не изменила избранное")
        self.assertEqual(shop.sent, [FAVORITES, PAGE, ("♥", "/catalog/items/favorites/add")])

    def test_not_an_id(self):
        with self.assertRaises(ValueError):
            lenta.favorite("кефир")


if __name__ == "__main__":
    unittest.main()
