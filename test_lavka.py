"""Яндекс Лавка: the site's product JSON and delivery info -> the grocery product dict; its search answers -> search results.
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


if __name__ == "__main__":
    unittest.main()
