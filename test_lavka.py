"""Яндекс Лавка: the site's product JSON and delivery info -> the grocery product dict; its search answers -> search results;
the cart and favorites: which of the page's buttons are clicked, what is sent and what is said.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_lavka"""
import unittest
from unittest.mock import MagicMock, call, patch

from grocery import lavka

FULL = {"product": {
    "id": "a1b2", "deepLink": "kefir-1", "longTitle": "Кефир&shy; 2,5%", "brand": "Простоквашино", "amount": "930 г",
    "currentPrice": "115", "oldPrice": "130", "available": True, "productTags": ["withoutSugar"], "facts": ["fermented"],
    "options": {"attributes": {"customTags": ["local"], "mainAllergens": ["молоко"], "importantIngredients": ["лактоза"]},
                "ingredients": {"pfcTraits": [{"id": "calories", "measures": {"per100g": "53"}},
                                              {"id": "protein", "measures": {"per100g": "2,9"}},
                                              {"id": "fat", "measures": {"per100g": "2.5"}},
                                              {"id": "carbohydrate", "measures": {"per100g": "4"}},
                                              {"id": "fiber", "measures": {"per100g": "1"}}]}},
    "descriptionBlocks": [{"attributes": ["ingredientsLoc"], "value": "молоко нормализованное, закваска"},
                          {"attributes": ["specificsProduction"], "value": "может содержать следы орехов"},
                          {"title": "Срок <b>хранения</b>", "value": "10 суток"}, {"title": "Пусто", "value": ""}],
    "stickersV2": [{"stickerId": "new", "text": "новинка"}, {"stickerId": "discount", "text": "−12%"}], "isLowStock": True,
    "imageUrlTemplates": ["https://img/{w}x{h}/1.jpg", "https://img/{w}x{h}/2.jpg"], "description": "Кефир <i>свежий</i>"}}
INFO = {"deliveryTimeText": "15–25 мин", "pricingConditions": {"deliveryCost": "99"},
        "deliveryConditions": [{"name": "бесплатно от", "threshold": "1500 ₽"}, {"name": "минимум"}], "isOpen": False}

BARE = {"product": {
    "id": "z9", "title": "Вода", "currentPrice": "49,90", "available": False, "snippetImage": {"url": "https://img/{w}x{h}/s.jpg"},
    "options": {"ingredients": {"pfcTraits": [{"id": "carbohydrate", "measures": {"per100g": "0"}}]}},
    "descriptionBlocks": [{"attributes": ["ingredientsLoc"], "value": "вода. следы солей"},
                          {"attributes": ["specificsProduction"], "value": "следы солей"}]}}


def product(answer, info, id_or_url="a1b2"):
    tab = MagicMock()
    tab.js.return_value = info
    with patch.object(lavka, "_tab", return_value=tab), patch.object(lavka, "_post", return_value=answer) as post:
        got = lavka.product(id_or_url)
    return got, post


class LavkaProductTests(unittest.TestCase):
    def test_full_card(self):
        got, post = product(FULL, INFO)
        self.assertEqual(post.call_args.args[1:], ("v1/product", {"productId": "a1b2", "needCatalogPaths": True, "enableUnavailable": True},
                                                   "regular"))
        self.assertEqual(got, {
            "id": "a1b2", "name": "Кефир 2,5%", "brand": "Простоквашино", "size": "930 г", "price": 115.0, "old": 130.0,
            "available": True, "url": "https://lavka.yandex.ru/good/kefir-1", "rating": None, "reviews": None, "ean": None,
            "photos": ["https://img/orig/1.jpg", "https://img/orig/2.jpg"], "description": "Кефир свежий",
            "composition": "молоко нормализованное, закваска. может содержать следы орехов",
            "nutrition": {"kcal": 53.0, "protein": 2.9, "fat": 2.5, "carbs": 4.0},
            "composition_extra": "без сахара (тег Лавки)",
            "extra": ["скидка −12%",
                      "доставка (Лавка у дома): 15–25 мин, доставка 99 ₽; бесплатно от 1500 ₽; минимум · сейчас закрыто",
                      "осталось мало", "теги Лавки: fermented, local, withoutSugar",
                      "аллергены: молоко · важные ингредиенты: лактоза", "о товаре: Срок хранения: 10 суток"]})

    def test_bare_card_in_the_big_lavka(self):
        got, post = product(BARE, {"deliveryTimeText": "завтра", "pricingConditions": {"deliveryCost": "бесплатно"}}, "s:z9")
        self.assertEqual(post.call_args.args[3], "supermarket")
        self.assertEqual(got, {
            "id": "s:z9", "name": "Вода · Большая лавка", "brand": "", "size": "", "price": 49.9, "old": None, "available": False,
            "url": "https://lavka.yandex.ru/supermarket/good/z9", "rating": None, "reviews": None, "ean": None,
            "photos": ["https://img/orig/s.jpg"], "description": "", "composition": "вода. следы солей",
            "nutrition": {"carbs": 0.0, "sugar": 0.0}, "composition_extra": "",
            "extra": ["доставка (Большая лавка): завтра, бесплатно"]})

    def test_no_delivery_info(self):
        got, _ = product(BARE, None)
        self.assertEqual(got["extra"], [])

    def test_unknown_product(self):
        self.assertEqual(product({}, INFO)[0], "Лавка: товар a1b2 не найден")

    def test_site_did_not_answer(self):
        self.assertEqual(product(None, None)[0], lavka.BLOCKED)


# search answers: the regular depot orders its hits by layoutItems (a banner and a vanished id among them), the big one has none
KEFIR = {"id": "k1", "longTitle": "Кефир 3,2%", "brand": "Простоквашино", "amount": "930 г", "currentPrice": "115", "oldPrice": "130",
         "available": True, "deepLink": "kefir-1", "productTags": ["withoutLactose"], "options": {"attributes": {"mainAllergens": ["milk"]}}}
LACTOSE_FREE = {"id": "k2", "title": "Кефир безлактозный", "currentPrice": "99", "available": True,
                "options": {"attributes": {"customTags": ["withoutLactose"], "mainAllergens": ["milk", "gluten"]}}}
VEGAN = {"id": "k3", "title": "Кефир 1%", "currentPrice": "89", "oldPrice": "99", "available": False, "facts": ["vegan"]}
BIG = {"id": "k4", "title": "Кефир большой", "currentPrice": "200", "oldPrice": "250", "available": True, "deepLink": "kefir-big"}
NO_PRICE = {"id": "k5", "title": "Кефир без цены"}
REGULAR = {"cacheProducts": [KEFIR, LACTOSE_FREE, VEGAN],
           "layoutItems": [{"type": "good", "id": "k2"}, {"type": "banner", "id": "b"}, {"type": "good", "id": "gone"}, {"type": "good", "id": "k1"}]}
SUPERMARKET = {"cacheProducts": [BIG, NO_PRICE]}


def row(pid, name, price, old=None, available=True, link=None, brand="", size=""):
    sup = pid.startswith("s:")
    return {"id": pid, "name": name + (" · Большая лавка" if sup else ""), "brand": brand, "size": size, "price": price, "old": old,
            "available": available, "url": f"https://lavka.yandex.ru{'/supermarket' if sup else ''}/good/{link or pid.removeprefix('s:')}",
            "rating": None, "reviews": None, "ean": None}


K1 = row("k1", "Кефир 3,2%", 115.0, 130.0, link="kefir-1", brand="Простоквашино", size="930 г")
K2 = row("k2", "Кефир безлактозный", 99.0)
K3 = row("k3", "Кефир 1%", 89.0, 99.0, available=False)
K4 = row("s:k4", "Кефир большой", 200.0, 250.0, link="kefir-big")
K5 = row("s:k5", "Кефир без цены", None, available=False)
URL = "https://lavka.yandex.ru/search?text=%D0%BA%D0%B5%D1%84%D0%B8%D1%80"
SORTED = "Лавка не сортирует: отсортированы полученные товары"


def search_body(text, limit=32):
    return {"text": text, "productsLimit": limit, "subcategoriesLimit": 0, "useRetail": True, "source": "manual_input",
            "cart": {"cartItems": []}}


def search(answers, *args, **kw):
    """lavka.search with the site's answers keyed by (path, depot); returns the result, the _post mock and the tab."""
    tab = MagicMock()
    with patch.object(lavka, "_tab", return_value=tab), \
            patch.object(lavka, "_post", side_effect=lambda t, path, body, depot="regular": answers[path, depot]) as post:
        got = lavka.search(*args, **kw)
    tab.close.assert_called_once()
    return got, post


DEPOTS = {("search/v3/lavka", "regular"): REGULAR, ("search/v3/lavka", "supermarket"): SUPERMARKET}


class LavkaSearchTests(unittest.TestCase):
    def test_both_depots(self):
        got, post = search(DEPOTS, "кефир")
        tab = post.call_args.args[0]
        self.assertEqual(post.call_args_list, [call(tab, "search/v3/lavka", search_body("кефир"), "regular"),
                                               call(tab, "search/v3/lavka", search_body("кефир"), "supermarket")])
        self.assertEqual(got, {"items": [K2, K1, K3, K4, K5], "total": 5, "note": "", "facets": list(lavka.TAGS), "url": URL})

    def test_tag_keeps_the_tagged(self):
        got, post = search(DEPOTS, "кефир", tag="без лактозы", limit=40)
        self.assertEqual(post.call_args.args[2], search_body("кефир", 40))
        self.assertEqual(got, {"items": [K2, K1], "total": 2, "note": "тег Лавки «без лактозы»", "facets": list(lavka.TAGS), "url": URL})

    def test_tags_match_whatever_case_the_site_writes_them_in(self):
        protein = {"id": "k6", "title": "Сыр протеиновый", "currentPrice": "150", "available": True, "productTags": ["HighProtein"]}
        got, _ = search({("search/v3/lavka", "regular"): {"cacheProducts": [protein, KEFIR]}, ("search/v3/lavka", "supermarket"): {}},
                        "сыр", tag="много белка")
        self.assertEqual([p["id"] for p in got["items"]], ["k6"])

    def test_gluten_free_is_read_from_the_allergens(self):
        got, _ = search(DEPOTS, "кефир", tag="Без глютена")
        self.assertEqual(got, {"items": [K1, K3, K4, K5], "total": 4,
                               "note": "тег Лавки «Без глютена» — по списку аллергенов: глютена в нём нет (сайт этого не утверждает)",
                               "facets": list(lavka.TAGS), "url": URL})

    def test_fact_without_query_lists_by_attribute(self):
        answers = {("v1/products/list/by-attribute", "regular"): {"products": [VEGAN, KEFIR]}}
        got, post = search(answers, "", tag="веган", limit=5)
        self.assertEqual(post.call_args.args[1:], ("v1/products/list/by-attribute", {"attribute": {"type": "fact", "value": "vegan"}, "limit": 20}))
        self.assertEqual(got, {"items": [K3], "total": 1, "note": "тег Лавки «веган»", "facets": list(lavka.TAGS),
                               "url": "https://lavka.yandex.ru/search?text="})

    def test_fact_list_did_not_answer(self):
        self.assertEqual(search({("v1/products/list/by-attribute", "regular"): None}, "", tag="веган")[0], lavka.BLOCKED)

    def test_fact_list_answered_empty_is_empty_not_blocked(self):
        got, _ = search({("v1/products/list/by-attribute", "regular"): {}}, "", tag="веган")
        self.assertEqual((got["items"], got["total"]), ([], 0))

    def test_unknown_tag_is_searched_as_text_and_sorted(self):
        expected = {"price": [K3, K2, K1, K4, K5], "price_desc": [K4, K1, K2, K3, K5], "discount": [K5, K4, K1, K3, K2],
                    "rating": [K2, K1, K3, K4, K5]}
        for sort, items in expected.items():
            with self.subTest(sort):
                got, post = search(DEPOTS, "кефир", tag="свежий", sort=sort)
                self.assertEqual(post.call_args.args[2]["text"], "кефир свежий")
                self.assertEqual(got, {"items": items, "total": 5,
                                       "note": "тега «свежий» у Лавки нет — искал «кефир свежий» текстом\n" + SORTED,
                                       "facets": list(lavka.TAGS),
                                       "url": "https://lavka.yandex.ru/search?text=%D0%BA%D0%B5%D1%84%D0%B8%D1%80%20%D1%81%D0%B2%D0%B5%D0%B6%D0%B8%D0%B9"})

    def test_sorted_without_note(self):
        self.assertEqual(search(DEPOTS, "кефир", sort="price")[0]["note"], SORTED)

    def test_second_page(self):
        got, _ = search(DEPOTS, "кефир", page=2, limit=2)
        self.assertEqual((got["items"], got["total"]), ([K3, K4], 5))

    def test_big_lavka_did_not_answer(self):
        got, _ = search(DEPOTS | {("search/v3/lavka", "supermarket"): None}, "кефир")
        self.assertEqual((got["items"], got["total"]), ([K2, K1, K3], 3))

    def test_empty_answer(self):
        got, _ = search({("search/v3/lavka", "regular"): {}, ("search/v3/lavka", "supermarket"): {}}, "кефир")
        self.assertEqual((got["items"], got["total"]), ([], 0))

    def test_site_did_not_answer(self):
        got, post = search({("search/v3/lavka", "regular"): None}, "кефир")
        self.assertEqual((got, post.call_count), (lavka.BLOCKED, 1))


class LavkaPostTests(unittest.TestCase):
    def post(self, *answers):
        tab = MagicMock()
        tab.js.side_effect = list(answers)
        with patch.object(lavka, "log"):
            got = lavka._post(tab, "v1/product", {"productId": "a1"}, "supermarket")
        return got, tab

    def test_answer(self):
        got, tab = self.post({"product": {}})
        self.assertEqual(got, {"product": {}})
        self.assertEqual(tab.js.call_args.args[0], lavka.POST_JS + '("v1/product", {"productId": "a1"}, "supermarket")')
        tab.goto.assert_not_called()

    def test_stale_token_reloads_the_page_once(self):
        for error in (401, 403, "no page state"):
            with self.subTest(error):
                got, tab = self.post({"__error": error}, {"product": {}})
                self.assertEqual((got, tab.js.call_count), ({"product": {}}, 2))
                tab.goto.assert_called_once_with("https://lavka.yandex.ru/", "lavka",
                                                 wait_js="!!window.storeDehydratedState && !!window.__PAGE_PROPS__")

    def test_still_failing_after_the_reload(self):
        self.assertEqual(self.post({"__error": 403}, {"__error": 403})[0], None)

    def test_other_errors_are_not_retried(self):
        got, tab = self.post({"__error": 500})
        self.assertEqual((got, tab.js.call_count), (None, 1))
        tab.goto.assert_not_called()

    def test_not_json(self):
        for answer in (None, [], "text"):
            with self.subTest(answer):
                self.assertIsNone(self.post(answer)[0])


# --- cart and favorites: the page's own buttons, clicked in a model of the site ------------------------------------

GOOD = {"id": "a1b2", "deepLink": "kefir-1", "longTitle": "Кефир&shy; 2,5%", "title": "Кефир", "currentPrice": "115", "available": True}
READY = "!!document.querySelector('[data-testid=snippet-control], [data-testid=snippet-control-base]')"
BUTTONS = {"[data-testid=snippet-control]": "В корзину", "[data-testid=snippet-control-base] [data-testid=add-spin-button]": "+",
           "[data-testid=snippet-control-base] [data-testid=remove-spin-button]": "−"}
CLICKS = {"(() => { const b = document.querySelector('" + sel + "'); if (!b) return false; b.click(); return true })()": name
          for sel, name in BUTTONS.items()}
RETRIEVE = ("cart/v1/retrieve", {}, "regular")
UNCHECKED = "Кефир 2,5%: Лавка не отдала корзину, и не видно, что получилось — проверь grocery_cart, прежде чем повторять"


class Shop:
    """The site as the cart code meets it: the product API, the cart of each depot (cart/v1/retrieve), the product
    page with «В корзину» while its depot's cart has none of the product, «+» and «−» while it has some, a click
    changing that cart.  sent: API calls (path, body, depot), page loads and clicks in order."""
    def __init__(self, qty=0, depot="regular", good=GOOD, buttons=True, reads=(True,), checkout=True):
        """reads: whether each cart read in turn gets an answer (the last one goes for the reads after it)."""
        self.carts = {"regular": {}, "supermarket": {}}
        self.carts[depot]["a1b2"] = qty
        self.good, self.buttons, self.reads, self.checkout, self.page, self.sent = good, buttons, list(reads), checkout, None, []
        self.tab = MagicMock()
        self.tab.js.side_effect, self.tab.goto.side_effect = self.click, self.goto

    def post(self, tab, path, body, depot="regular"):
        assert tab is self.tab
        self.sent.append((path, body, depot))
        if path == "cart/v1/retrieve":
            return self.retrieve(depot) if (self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]) else None
        assert path == "v1/product" and body == {"productId": body["productId"], "enableUnavailable": True}, (path, body)
        return {"product": self.good} if self.good and body["productId"] in ("a1b2", "kefir-1") else {}

    def retrieve(self, depot):
        items = [{"id": i, "quantity": q, "price": "115", "title": "Кефир&shy; 2,5%"} for i, q in self.carts[depot].items() if q]
        return {"items": items, "totalItemsPrice": 115 * sum(i["quantity"] for i in items), "totalPriceValue": 115 * sum(i["quantity"] for i in items) + 99,
                "availableForCheckout": self.checkout, "checkoutUnavailableReason": "минимальный заказ 500 ₽"}

    def goto(self, url, site, wait_js=None):
        assert (site, wait_js) == ("lavka", READY)
        self.sent.append(url)
        self.page = "supermarket" if "/supermarket/" in url else "regular"

    def click(self, expr):
        name = CLICKS[expr]
        cart = self.carts[self.page]
        if not self.buttons or (name == "В корзину") != (not cart["a1b2"]):
            return False
        self.sent.append(name)
        cart["a1b2"] += -1 if name == "−" else 1
        return True

    def run(self, fn, *args):
        with patch.object(lavka, "_tab", return_value=self.tab), patch.object(lavka, "_post", side_effect=self.post), \
                patch.object(lavka, "time"):
            got = fn(*args)
        self.tab.close.assert_called_once()
        return got


PAGE = "https://lavka.yandex.ru/good/kefir-1"
OPEN = ("v1/product", {"productId": "a1b2", "enableUnavailable": True}, "regular")


def nothing_but_the_lookup(test, shop):
    shop.tab.close.assert_called_once()
    test.assertEqual(shop.sent, [("v1/product", {"productId": "zz", "enableUnavailable": True}, "regular")])


class LavkaAddToCartTests(unittest.TestCase):
    def test_first_unit_by_the_add_button_then_plus(self):
        shop = Shop()
        self.assertEqual(shop.run(lavka.add_to_cart, "https://lavka.yandex.ru/good/kefir-1", 2),
                         "в корзине Лавка у дома: Кефир 2,5% — 2 шт; корзина 230 ₽ без доставки")
        self.assertEqual(shop.sent, [("v1/product", {"productId": "kefir-1", "enableUnavailable": True}, "regular"), PAGE, RETRIEVE,
                                     "В корзину", "+", RETRIEVE])

    def test_big_lavka_already_in_the_cart_and_under_the_minimum(self):
        shop = Shop(qty=1, depot="supermarket", checkout=False)
        self.assertEqual(shop.run(lavka.add_to_cart, "s:a1b2"),
                         "в корзине Большая лавка: Кефир 2,5% — 2 шт; корзина 230 ₽ без доставки · к заказу пока нельзя: минимальный заказ 500 ₽")
        sup = ("cart/v1/retrieve", {}, "supermarket")
        self.assertEqual(shop.sent, [("v1/product", {"productId": "a1b2", "enableUnavailable": True}, "supermarket"),
                                     "https://lavka.yandex.ru/supermarket/good/kefir-1", sup, "+", sup])

    def test_quantity_is_one_to_thirty_clicks(self):
        for quantity, clicks in ((0, 1), (-3, 1), ("2", 2), (100, 30)):
            with self.subTest(quantity):
                shop = Shop()
                shop.run(lavka.add_to_cart, "a1b2", quantity)
                self.assertEqual(len([x for x in shop.sent if x in ("В корзину", "+")]), clicks)

    def test_page_by_id_when_the_product_has_no_link(self):
        shop = Shop(good=dict(GOOD, deepLink=None))
        shop.run(lavka.add_to_cart, "a1b2")
        self.assertEqual(shop.sent[1], "https://lavka.yandex.ru/good/a1b2")

    def test_not_available(self):
        shop = Shop(good=dict(GOOD, available=False))
        self.assertEqual(shop.run(lavka.add_to_cart, "a1b2"), "Лавка: Кефир 2,5% сейчас нет в наличии")
        self.assertEqual(shop.sent, [OPEN, PAGE, RETRIEVE])

    def test_button_that_is_not_there(self):
        shop = Shop(buttons=False)
        self.assertEqual(shop.run(lavka.add_to_cart, "a1b2", 3), "Лавка не положила Кефир 2,5% в корзину (кнопка не сработала)")
        self.assertEqual(shop.sent, [OPEN, PAGE, RETRIEVE, RETRIEVE])

    def test_cart_that_did_not_come(self):
        shop = Shop(qty=1, reads=(False,))
        self.assertEqual(shop.run(lavka.add_to_cart, "a1b2"), lavka.BLOCKED)
        self.assertEqual(shop.sent, [OPEN, PAGE, RETRIEVE])

    def test_cart_that_did_not_come_back(self):
        shop = Shop(reads=(True, False))
        self.assertEqual(shop.run(lavka.add_to_cart, "a1b2", 2), UNCHECKED)
        self.assertEqual(shop.sent, [OPEN, PAGE, RETRIEVE, "В корзину", "+", RETRIEVE])

    def test_unknown_product(self):
        shop = Shop(good=None)
        with self.assertRaisesRegex(ValueError, "Лавка: товар zz не найден"):
            shop.run(lavka.add_to_cart, "zz")
        nothing_but_the_lookup(self, shop)


class LavkaRemoveFromCartTests(unittest.TestCase):
    def test_minus_until_it_is_gone(self):
        shop = Shop(qty=2)
        self.assertEqual(shop.run(lavka.remove_from_cart, "a1b2"), "убрано из корзины Лавка у дома: Кефир 2,5%")
        self.assertEqual(shop.sent, [OPEN, PAGE, RETRIEVE, "−", RETRIEVE, "−", RETRIEVE])

    def test_not_in_the_cart(self):
        shop = Shop(qty=1, depot="supermarket")
        self.assertEqual(shop.run(lavka.remove_from_cart, "a1b2"), "Кефир 2,5% в корзине Лавка у дома нет")
        self.assertEqual(shop.sent, [OPEN, PAGE, RETRIEVE])

    def test_no_minus_button(self):
        shop = Shop(qty=1, buttons=False)
        self.assertEqual(shop.run(lavka.remove_from_cart, "a1b2"), "не удалось убрать Кефир 2,5% из корзины Лавки")
        self.assertEqual(shop.sent, [OPEN, PAGE, RETRIEVE])

    def test_at_most_thirty_clicks(self):
        shop = Shop(qty=31)
        self.assertEqual(shop.run(lavka.remove_from_cart, "a1b2"), "не удалось убрать Кефир 2,5% из корзины Лавки")
        self.assertEqual(shop.sent, [OPEN, PAGE] + [RETRIEVE, "−"] * 30 + [RETRIEVE])

    def test_cart_that_did_not_come(self):
        shop = Shop(qty=1, reads=(False,))
        self.assertEqual(shop.run(lavka.remove_from_cart, "a1b2"), lavka.BLOCKED)
        self.assertEqual(shop.sent, [OPEN, PAGE, RETRIEVE])

    def test_cart_that_did_not_come_back(self):
        shop = Shop(qty=2, reads=(True, False))
        self.assertEqual(shop.run(lavka.remove_from_cart, "a1b2"), UNCHECKED)
        self.assertEqual(shop.sent, [OPEN, PAGE, RETRIEVE, "−", RETRIEVE])

    def test_unknown_product(self):
        shop = Shop(good=None)
        with self.assertRaisesRegex(ValueError, "Лавка: товар zz не найден"):
            shop.run(lavka.remove_from_cart, "zz")
        nothing_but_the_lookup(self, shop)


class LavkaCartTests(unittest.TestCase):
    def test_both_depots(self):
        shop = Shop(qty=2, checkout=False)
        shop.carts["supermarket"] = {"c3": 1, "gone": 0}
        self.assertEqual(shop.run(lavka.cart), "корзина Лавки\n"
                         "Лавка у дома: 230 ₽ без доставки, итого 329 ₽ (к заказу нельзя: минимальный заказ 500 ₽)\n  a1b2\t2 шт\t115 ₽\tКефир 2,5%\n"
                         "Большая лавка: 115 ₽ без доставки, итого 214 ₽ (к заказу нельзя: минимальный заказ 500 ₽)\n  s:c3\t1 шт\t115 ₽\tКефир 2,5%")
        self.assertEqual(shop.sent, [RETRIEVE, ("cart/v1/retrieve", {}, "supermarket")])

    def test_one_depot(self):
        shop = Shop(qty=1, depot="supermarket")
        self.assertEqual(shop.run(lavka.cart), "корзина Лавки\nБольшая лавка: 115 ₽ без доставки, итого 214 ₽\n  s:a1b2\t1 шт\t115 ₽\tКефир 2,5%")

    def test_empty(self):
        self.assertEqual(Shop().run(lavka.cart), "корзины Лавки (у дома и Большой лавки) пусты")

    def test_cart_that_did_not_come(self):
        self.assertEqual(Shop(reads=(False,)).run(lavka.cart), lavka.BLOCKED)

    def test_one_depot_did_not_answer(self):
        self.assertEqual(Shop(qty=2, reads=(True, False)).run(lavka.cart), "корзина Лавки\n"
                         "Лавка у дома: 230 ₽ без доставки, итого 329 ₽\n  a1b2\t2 шт\t115 ₽\tКефир 2,5%\nБольшая лавка: корзина не пришла")
        self.assertEqual(Shop(depot="supermarket", reads=(False, True)).run(lavka.cart), "корзина Лавки\nЛавка у дома: корзина не пришла")


class LavkaFavoritesTests(unittest.TestCase):
    def favorites(self, answer):
        tab = MagicMock()
        with patch.object(lavka, "_tab", return_value=tab), patch.object(lavka, "_post", return_value=answer) as post:
            got = lavka.favorites()
        tab.close.assert_called_once()
        self.assertEqual(post.call_args_list, [call(tab, "v1/api/v1/user/favorites", {})])
        return got

    def test_favorites(self):
        self.assertEqual(self.favorites({"products": [KEFIR, VEGAN]}),
                         "избранное Лавки\nid\tцена ₽\tналичие\tназвание\nk1\t115.0\t\tКефир 3,2%\nk3\t89.0\tнет в наличии\tКефир 1%")

    def test_no_favorites(self):
        for answer in ({"products": []}, {}):
            with self.subTest(answer):
                self.assertEqual(self.favorites(answer), "избранное Лавки пусто")

    def test_favorites_that_did_not_come(self):
        self.assertEqual(self.favorites(None), lavka.BLOCKED)


class LavkaFavoriteTests(unittest.TestCase):
    def favorite(self, product, answer, *args):
        tab, sent = MagicMock(), []

        def post(t, path, body, depot="regular"):
            assert t is tab
            sent.append((path, body, depot))
            return product if path == "v1/product" else answer

        with patch.object(lavka, "_tab", return_value=tab), patch.object(lavka, "_post", side_effect=post):
            got = lavka.favorite(*args)
        tab.close.assert_called_once()
        return got, sent

    def test_add_by_link(self):
        got, sent = self.favorite({"product": GOOD}, {"isFavorite": True}, "https://lavka.yandex.ru/good/kefir-1")
        self.assertEqual(sent, [("v1/product", {"productId": "kefir-1", "enableUnavailable": True}, "regular"),
                                ("attributes/v2/favorite", {"productId": "a1b2", "isFavorite": True}, "regular")])
        self.assertEqual(got, "в избранном Лавки: Кефир 2,5%")

    def test_remove_in_the_big_lavka(self):
        got, sent = self.favorite({"product": GOOD}, {"isFavorite": False}, "s:a1b2", True)
        self.assertEqual(sent[1], ("attributes/v2/favorite", {"productId": "a1b2", "isFavorite": False}, "supermarket"))
        self.assertEqual(got, "убрано из избранного Лавки: Кефир 2,5%")

    def test_unknown_product_is_sent_as_given(self):
        for product in (None, {}, {"product": None}):
            with self.subTest(product):
                got, sent = self.favorite(product, {"isFavorite": True}, "zz")
                self.assertEqual((got, sent[1]), ("в избранном Лавки: zz", ("attributes/v2/favorite", {"productId": "zz", "isFavorite": True}, "regular")))

    def test_not_changed(self):
        for answer, remove in ((None, False), ({}, False), ({"isFavorite": True}, True), ({"isFavorite": 0}, True)):
            with self.subTest(answer=answer, remove=remove):
                self.assertEqual(self.favorite({"product": GOOD}, answer, "a1b2", remove)[0], "Лавка не изменила избранное")


if __name__ == "__main__":
    unittest.main()
