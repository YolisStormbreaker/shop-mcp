"""Самокат read paths: the site's tab, its endpoint answers -> search results and the product card.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_samokat"""
import unittest
from unittest.mock import MagicMock, patch

from grocery import samokat

DELIVERY = "доставка: ~15 мин из ближайшего склада Самоката (условия сайта для адреса пользователя)"
LOADED = "!!window.webpackChunk_N_E && document.readyState === 'complete'"
HOME = {"href": "https://samokat.ru/", "setup": True}
NO_SETUP = {"href": "https://samokat.ru/", "setup": False}
CHECK = {"href": "https://samokat.ru/xpvnsulc/?r=1"}
ELSEWHERE = {"href": None}


class Page:
    """A tab: js() answers from the page it shows, goto() shows the next page it was given to load."""
    def __init__(self, page, *loads):
        self.page, self.loads, self.gotos, self.closed = page, list(loads), [], False

    def js(self, expr, timeout=None):
        href = self.page["href"]
        if expr == "location.href":
            return href
        if expr == "location.hostname.endsWith('samokat.ru')":
            return "samokat.ru" in (href or "")
        assert expr == samokat.SETUP_JS, expr
        return self.page.get("setup", False)

    def goto(self, url, site, wait_js=None):
        self.gotos.append((url, site, wait_js))
        self.page = self.loads.pop(0)

    def close(self):
        self.closed = True


def tab(*pages):
    page = Page(*pages)
    with patch.object(samokat, "tab_for", return_value=page) as tab_for:
        got = samokat._tab()
    tab_for.assert_called_once_with("samokat.ru")
    return got, page


class SamokatTabTests(unittest.TestCase):
    def test_open_page_is_used_as_it_is(self):
        got, page = tab(HOME)
        self.assertIs(got, page)
        self.assertEqual((page.gotos, page.closed), ([], False))

    def test_stale_bot_check_page_is_loaded_once_more(self):
        got, page = tab(CHECK, HOME)
        self.assertIs(got, page)
        self.assertEqual(page.gotos, [("https://samokat.ru/", "samokat", LOADED + " || location.href.includes('/xpvnsulc/')")])

    def test_bot_check_that_stays_closes_the_tab(self):
        got, page = tab(CHECK, CHECK)
        self.assertIsNone(got)
        self.assertEqual((len(page.gotos), page.closed), (1, True))

    def test_tab_elsewhere_loads_the_home_page(self):
        got, page = tab(ELSEWHERE, HOME)
        self.assertIs(got, page)
        self.assertEqual(page.gotos, [("https://samokat.ru/", "samokat", LOADED)])

    def test_check_page_that_reloads_elsewhere_loads_the_home_page(self):
        got, page = tab(CHECK, ELSEWHERE, HOME)
        self.assertIs(got, page)
        self.assertEqual(len(page.gotos), 2)

    def test_page_without_the_store_shows_the_check_after_loading(self):
        got, page = tab(NO_SETUP, CHECK)
        self.assertEqual((got, page.closed), (None, True))

    def test_page_where_the_store_is_never_found(self):
        got, page = tab(NO_SETUP, NO_SETUP)
        self.assertEqual((got, page.gotos, page.closed), (None, [("https://samokat.ru/", "samokat", LOADED)], True))


class SamokatCallTests(unittest.TestCase):
    def call(self, answer):
        page = MagicMock()
        page.js.return_value = answer
        with patch.object(samokat, "log") as log:
            got = samokat._call(page, "searchProducts", {"query": "мёд", "showcaseId": "SC"})
        self.assertEqual(page.js.call_args.args[0],
                         samokat.CALL_JS + '("searchProducts", {"query": "мёд", "showcaseId": "SC"})')
        self.assertEqual(page.js.call_args.kwargs, {"timeout": 40})
        return got, log

    def test_data(self):
        self.assertEqual(self.call({"data": [1]})[0], [1])

    def test_error_is_logged(self):
        got, log = self.call({"__error": 404})
        self.assertIsNone(got)
        log.warning.assert_called_once_with("samokat %s: %s", "searchProducts", 404)

    def test_no_answer(self):
        self.assertIsNone(self.call(None)[0])


def site(answers):
    """_call answering each endpoint from answers: name -> answer, or name -> {args key -> answer}."""
    calls = []

    def call(tab, name, args):
        calls.append((name, args))
        a = answers.get(name)
        return a.get(args.get("categoryIdOrSlug")) if name == "categoryByIdOrSlug" else a
    return call, calls


def run(fn, answers, *args, **kw):
    page = MagicMock()
    call, calls = site(answers)
    with patch.object(samokat, "_tab", return_value=page), patch.object(samokat, "_call", side_effect=call):
        got = fn(*args, **kw)
    page.close.assert_called_once()
    return got, calls


CATS = [{"id": "c1", "slug": "bez-laktozy", "name": "Без лактозы"}, {"id": "c2", "name": "Сыр без лактозы"},
        {"id": "c3", "slug": "moloko", "name": "Молоко"}, {"id": "c4", "slug": "vegan", "name": "Сладкое для веганов"},
        {"id": "c5", "name": "Протеиновые батончики"}, {"id": "c6"}, {"id": "c7", "slug": "med", "name": "Мёд и сахар"}]
DIET = ["Без лактозы", "Мёд и сахар", "Протеиновые батончики", "Сладкое для веганов", "Сыр без лактозы"]
SECTIONS = {
    "bez-laktozy": {"categories": [{"productIds": ["p1", "p2"], "children": [{"productIds": ["p3"]}]}, {"productIds": ["p2", "p4"]}],
                    "products": [{"id": "p5"}, {"id": "p1"}]},
    "c2": {"products": [{"id": "p4"}, {"id": "p6"}]},
    "med": None}
PRODUCTS = [
    {"id": "p1", "slug": "moloko-bez-laktozy-1-l", "name": "Молоко без лактозы 1 л", "price": 14500, "oldPrice": 16900, "isAvailable": True},
    {"id": "p2", "name": "Коктейль молочный", "price": 9900},
    "not a product",
    {"id": "p6", "name": "Сыр, 45% молока", "price": 30050, "quantity": 2},
    {"id": "p7", "price": 100}]


def row(id, name, price, old=None, available=True, slug=None):
    return {"id": slug or id, "name": name, "brand": "", "size": "", "price": price, "old": old, "available": available,
            "url": f"https://samokat.ru/product/{slug or id}", "rating": None, "reviews": None, "ean": None}


MILK = row("p1", "Молоко без лактозы 1 л", 145.0, 169.0, slug="moloko-bez-laktozy-1-l")
CHEESE = row("p6", "Сыр, 45% молока", 300.5)


def search(answers, *args, **kw):
    return run(samokat.search, answers, *args, **kw)


class SamokatSearchTests(unittest.TestCase):
    def test_tag_lists_the_sections_products_with_the_query_words(self):
        got, calls = search({"categoriesList": CATS, "categoryByIdOrSlug": SECTIONS, "productsByIds": PRODUCTS},
                            "молоко", tag=" БЕЗ ЛАКТОЗЫ")
        self.assertEqual(calls, [
            ("categoriesList", "SC"),
            ("categoryByIdOrSlug", {"categoryIdOrSlug": "bez-laktozy", "filters": {}, "limit": 100}),
            ("categoryByIdOrSlug", {"categoryIdOrSlug": "c2", "filters": {}, "limit": 100}),
            ("productsByIds", {"showcaseId": "SC", "productIds": ["p1", "p2", "p4", "p3", "p5", "p6"]})])
        self.assertEqual(got, {"items": [MILK, CHEESE], "total": 2, "note": "разделы Самоката « БЕЗ ЛАКТОЗЫ» (2), названия со словами «молоко»",
                               "facets": DIET, "url": "https://samokat.ru/search?value=молоко"})

    def test_tag_without_a_query_takes_every_product_and_matches_yo(self):
        got, calls = search({"categoriesList": CATS, "categoryByIdOrSlug": SECTIONS, "productsByIds": PRODUCTS}, "", tag="мед")
        self.assertEqual(calls[1:], [("categoryByIdOrSlug", {"categoryIdOrSlug": "med", "filters": {}, "limit": 100})])
        self.assertEqual(got, {"items": [], "total": 0, "note": "разделы Самоката «мед» (1)", "facets": DIET,
                               "url": "https://samokat.ru/search?value="})

    def test_tag_reads_at_most_eight_sections(self):
        cats = [{"id": f"x{i}", "name": f"Без лактозы {i}"} for i in range(9)]
        got, calls = search({"categoriesList": cats, "categoryByIdOrSlug": {}}, "сыр", tag="без лактозы")
        self.assertEqual([c[0] for c in calls], ["categoriesList"] + ["categoryByIdOrSlug"] * 8)
        self.assertEqual((got["items"], got["note"]), ([], "разделы Самоката «без лактозы» (9), названия со словами «сыр»"))

    def test_tag_the_site_lacks_goes_into_the_text_search(self):
        found = [{"type": "PRODUCT", "id": "p9", "slug": "kefir-1", "name": "Кефир 1%", "price": 9900, "isAvailable": False},
                 {"type": "CATEGORY", "id": "c9", "name": "Кефир"}]
        got, calls = search({"categoriesList": None, "searchProducts": found}, "кефир", tag="Без глютена")
        self.assertEqual(calls, [("categoriesList", "SC"), ("searchProducts", {"query": "кефир Без глютена", "showcaseId": "SC"})])
        self.assertEqual(got, {"items": [row("p9", "Кефир 1%", 99.0, available=False, slug="kefir-1")], "total": 1,
                               "note": "раздела «Без глютена» у Самоката нет — искал «кефир Без глютена» текстом", "facets": [],
                               "url": "https://samokat.ru/search?value=кефир+Без+глютена"})

    def test_text_search_page_and_sort(self):
        found = [{"type": "PRODUCT", "id": f"p{i}", "name": f"Кефир {i}", "price": price, "oldPrice": old}
                 for i, (price, old) in enumerate([(10000, None), (None, None), (5000, 10000), (20000, 25000)])]
        got, calls = search({"categoriesList": CATS, "searchProducts": found}, "кефир  2,5%", sort="price", page=2, limit=2)
        self.assertEqual(calls[1], ("searchProducts", {"query": "кефир  2,5%", "showcaseId": "SC"}))
        self.assertEqual(got, {"items": [row("p3", "Кефир 3", 200.0, 250.0, available=False), row("p1", "Кефир 1", None, available=False)],
                               "total": 4, "note": "Самокат не сортирует: отсортированы полученные товары", "facets": DIET,
                               "url": "https://samokat.ru/search?value=кефир+2,5%"})

    def test_sorts(self):
        found = [{"type": "PRODUCT", "id": f"p{i}", "price": price, "oldPrice": old}
                 for i, (price, old) in enumerate([(10000, None), (None, None), (5000, 10000), (20000, 25000)])]
        order = {}
        for sort in ("popular", "price", "price_desc", "discount", "rating"):
            got, _ = search({"searchProducts": found}, "кефир", sort=sort)
            order[sort] = [x["id"] for x in got["items"]]
        self.assertEqual(order, {"popular": ["p0", "p1", "p2", "p3"], "price": ["p2", "p0", "p3", "p1"],
                                 "price_desc": ["p3", "p0", "p2", "p1"], "discount": ["p1", "p2", "p3", "p0"],
                                 "rating": ["p0", "p1", "p2", "p3"]})

    def test_sorted_tag_search_notes_both(self):
        got, _ = search({"categoriesList": CATS, "categoryByIdOrSlug": SECTIONS, "productsByIds": PRODUCTS}, "сыр", tag="без лактозы",
                        sort="price_desc")
        self.assertEqual(got["note"], "разделы Самоката «без лактозы» (2), названия со словами «сыр»\n"
                                      "Самокат не сортирует: отсортированы полученные товары")

    def test_text_search_without_an_answer_is_a_bot_check(self):
        got, _ = search({"categoriesList": CATS, "searchProducts": None}, "кефир")
        self.assertEqual(got, samokat.BLOCKED)

    def test_no_tab(self):
        with patch.object(samokat, "_tab", return_value=None), patch.object(samokat, "_call") as call:
            self.assertEqual(samokat.search("кефир"), samokat.BLOCKED)
            self.assertEqual(samokat.product("kefir-1"), samokat.BLOCKED)
        call.assert_not_called()


CARD = {
    "id": "0f8b2c9e-1111-4a2b-9c3d-123456789abc", "slug": "kefir-2-5-930-g", "name": "Кефир 2,5%, 930 г", "price": 11500, "oldPrice": 13000,
    "isAvailable": True, "quantity": 7, "discountPercent": 12,
    "attributes": {"Бренд": "Простоквашино", "Жирность": "2.5 %", "Вес": "930 г", "Объём": "900 мл", "Без лактозы": "FALSE",
                   "Без сахара": "true", "Состав": "молоко, закваска", "Примечание": "-", "Документы качества": "-",
                   "Энергетическая ценность на весь продукт": "480 ккал", "Хранение": "<p>при +2…+6 °C</p>"},
    "nutritions": {"kilocalories": "51 ккал", "protein": "2,9", "fats": 2.5, "carbohydrates": "", "fiber": "1"},
    "media": [{"url": "https://img/1.jpg?w=200"}, {"type": "video"}, {"url": "https://img/2.jpg"}],
    "description": "<p>Кефир\n  <b>свежий</b></p>"}


def product(answer, id_or_url="kefir-2-5-930-g"):
    return run(samokat.product, {"productByIdOrSlug": answer}, id_or_url)


class SamokatProductTests(unittest.TestCase):
    def test_full_card(self):
        got, calls = product(CARD, "https://samokat.ru/product/kefir-2-5-930-g?utm=x")
        self.assertEqual(calls, [("productByIdOrSlug", {"showcaseId": "SC", "productIdOrSlug": "kefir-2-5-930-g"})])
        self.assertEqual(got, {
            "id": "kefir-2-5-930-g", "name": "Кефир 2,5%, 930 г", "brand": "Простоквашино", "size": "930 г", "price": 115.0, "old": 130.0,
            "available": True, "url": "https://samokat.ru/product/kefir-2-5-930-g", "rating": None, "reviews": None, "ean": None,
            "photos": ["https://img/1.jpg", "https://img/2.jpg"], "description": "Кефир свежий", "composition": "молоко, закваска",
            "nutrition": {"kcal": 51.0, "protein": 2.9, "fat": 2.5},
            "composition_extra": "Жирность: 2.5 %; Без лактозы: нет; Без сахара: да",
            "extra": [DELIVERY, "на складе 7 шт", "скидка 12%",
                      "характеристики: Жирность: 2.5 %; Вес: 930 г; Объём: 900 мл; Без лактозы: нет; Без сахара: да; Хранение: при +2…+6 °C"]})

    def test_bare_card(self):
        got, _ = product({"id": "a1", "name": "Вода", "price": 4990, "quantity": 0}, " a1 ")
        self.assertEqual(got, {
            "id": "a1", "name": "Вода", "brand": "", "size": "", "price": 49.9, "old": None, "available": False,
            "url": "https://samokat.ru/product/a1", "rating": None, "reviews": None, "ean": None, "photos": [], "description": "",
            "composition": "", "nutrition": {}, "composition_extra": "", "extra": [DELIVERY]})

    def test_unknown_product(self):
        for answer in (None, {}):
            self.assertEqual(product(answer, "nope")[0], "Самокат: товар nope не найден на витрине для адреса пользователя")


class SamokatUuidTests(unittest.TestCase):
    """The cart's product uuid for an id, slug or link (a read: the cart itself is not touched here)."""
    def uuid(self, answer, id_or_url):
        call, calls = site({"productByIdOrSlug": answer})
        with patch.object(samokat, "_call", side_effect=call):
            return samokat._uuid(MagicMock(), id_or_url), calls

    def test_uuid_is_its_own_answer(self):
        self.assertEqual(self.uuid(None, CARD["id"]), ((CARD["id"], CARD["id"]), []))

    def test_slug_is_looked_up(self):
        got, calls = self.uuid(CARD, "https://samokat.ru/product/kefir-2-5-930-g")
        self.assertEqual(got, (CARD["id"], "Кефир 2,5%, 930 г"))
        self.assertEqual(calls, [("productByIdOrSlug", {"showcaseId": "SC", "productIdOrSlug": "kefir-2-5-930-g"})])

    def test_unknown_slug(self):
        self.assertEqual(self.uuid(None, "nope")[0], (None, "nope"))
        self.assertEqual(self.uuid({"id": "u1"}, "nope")[0], ("u1", "nope"))


if __name__ == "__main__":
    unittest.main()
