"""Пятёрочка read paths: search, product card and reviews from the site's API answers; the tab and the fetch.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_pyaterochka"""
import time
import unittest
from unittest.mock import MagicMock, call, patch
from urllib.parse import quote

from grocery import pyaterochka

API, REVIEWS = pyaterochka.API, pyaterochka.REVIEWS
STATE = {"store": "S1", "address": "Тестовая ул., 1"}
DEFAULT = ("⚠️ на 5ka.ru не задан адрес доставки: цены и наличие — для магазина по умолчанию сайта (35XY). "
           "Выбрать адрес можно на сайте.")
TREE = [{"id": "251C1", "name": "Молочное", "categories": [{"id": "251C2", "name": "Кефир"}]},
        {"id": "73C1", "name": "Здоровый выбор", "categories": [{"id": "73C2", "name": "Без лактозы, халяль"},
                                                                {"id": "73C3", "name": "Веган, без глютена"}]},
        {"id": "9C1", "name": "Сладости"}]
FACETS = ["Без лактозы, халяль", "Веган, без глютена"]
TREE_URL = f"{API}/v4/stores/S1/categories?mode=delivery&include_subcategories=1&include_restrict=true"
NOT_SORTED = "поиск сайта не сортирует: отсортирована полученная страница"


def listed(plu, name, regular=None, discount=None, **more):
    return {"plu": plu, "name": name, "prices": {"regular": regular, "discount": discount}, **more}


def row(plu, name, price, old=None, available=True, size="", rating=None, reviews=None):
    return {"id": str(plu), "name": name, "brand": "", "size": size, "price": price, "old": old, "available": available,
            "url": f"https://5ka.ru/product/{plu}/", "rating": rating, "reviews": reviews, "ean": None}


def site(answers, state=STATE):
    """_tab and _get stand-ins: _get answers with the value of the first key found in the URL, else None."""
    tab = MagicMock()
    tab.js.return_value = state
    get = MagicMock(side_effect=lambda t, url: next((a for k, a in answers.items() if k in url), None))
    return tab, get, patch.object(pyaterochka, "_tab", return_value=tab), patch.object(pyaterochka, "_get", get)


def run(fn, answers, *args, state=STATE, **kw):
    tab, get, p_tab, p_get = site(answers, state)
    with p_tab, p_get:
        got = fn(*args, **kw)
    tab.close.assert_called_once()
    return got, [c.args[1] for c in get.call_args_list]


class SearchTests(unittest.TestCase):
    def setUp(self):
        p = patch.dict(pyaterochka._tree, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def search(self, answers, query="кефир", state=STATE, **kw):
        return run(pyaterochka.search, {"/categories?": TREE, **answers}, query, state=state, **kw)

    def test_text_search(self):
        got, urls = self.search({"&offset=0": {"products": [
            listed(101, "Кефир Тестовый 2,5% 900г", "99.99", "79.99", property_clarification="900г",
                   rating={"rating_average": 4.9, "rates_count": 120}),
            listed(102, "Кефир 1%", "60", is_available=False),
            listed(103, "Кефир 3,2%", "", "70", stock_limit="0"),
            {"plu": 104}]}})
        self.assertEqual(urls, [TREE_URL, f"{API}/v3/stores/S1/search?mode=delivery&include_restrict=true&q={quote('кефир')}&limit=12&offset=0"])
        self.assertEqual(got, {
            "items": [row(101, "Кефир Тестовый 2,5% 900г", 79.99, 99.99, size="900г", rating=4.9, reviews=120),
                      row(102, "Кефир 1%", 60.0, available=False), row(103, "Кефир 3,2%", 70.0, available=False), row(104, "", None)],
            "total": None, "facets": FACETS, "note": "", "url": "https://5ka.ru/search/?text=" + quote("кефир")})

    def test_text_search_reads_pages_of_12_until_a_short_one(self):
        full = [listed(200 + i, f"Кефир {i}", "50") for i in range(12)]
        got, urls = self.search({"&offset=0": {"products": full}, "&offset=12": {"products": full[:2]}, "&offset=24": {"products": full}})
        self.assertEqual([u.split("&")[-1] for u in urls[1:]], ["offset=0", "offset=12"])
        self.assertEqual(len(got["items"]), 14)

    def test_page_and_limit(self):
        full = [listed(200 + i, f"Кефир {i}", "50") for i in range(12)]
        got, urls = self.search({"&offset=12": {"products": full}}, page=2, limit=5)
        self.assertEqual([u.split("&")[-1] for u in urls[1:]], ["offset=12"])
        self.assertEqual([r["id"] for r in got["items"]], ["200", "201", "202", "203", "204"])

    def test_blocked_search(self):
        self.assertEqual(self.search({})[0], pyaterochka.BLOCKED)

    def test_the_page_is_sorted_here(self):
        page = {"&offset=0": {"products": [listed(1, "A", "200", "100", rating={"rating_average": 4.5}), listed(2, "B", "50"),
                                           {"plu": 3, "name": "C", "rating": {"rating_average": 5.0}},
                                           listed(4, "D", "100", "80", rating={"rating_average": 4.9})]}}
        for sort, ids in {"price": "2413", "price_desc": "1423", "discount": "3142", "rating": "3412"}.items():
            with self.subTest(sort):
                got, _ = self.search(page, sort=sort)
                self.assertEqual("".join(r["id"] for r in got["items"]), ids)
                self.assertEqual(got["note"], NOT_SORTED)

    def test_unknown_tag_is_searched_as_text(self):
        got, urls = self.search({"&offset=0": {"products": [listed(101, "Кефир фермерское", "90")]}}, tag="фермерское",
                                state={"store": "S1", "address": ""})
        self.assertEqual(urls[1], f"{API}/v3/stores/S1/search?mode=delivery&include_restrict=true&q={quote('кефир фермерское')}&limit=12&offset=0")
        self.assertEqual(got, {"items": [row(101, "Кефир фермерское", 90.0)], "total": None, "facets": FACETS,
                               "note": "тега «фермерское» среди разделов сайта нет — искал «кефир фермерское» текстом",
                               "url": "https://5ka.ru/search/?text=" + quote("кефир фермерское")})

    def test_tag_lists_the_site_section_filtered_by_the_query_words(self):
        got, urls = self.search({"&offset=0": {"products": [listed(1, "Кефир безлактозный 1%", "90"), listed(2, "Молоко безлактозное", "80")]},
                                 "&offset=12": {"products": []}, "&offset=24": {"products": [listed(3, "Биокефирный продукт", "70")]}},
                                query="Кефиры", tag="лактоз", sort="price")
        base = f"{API}/v2/stores/S1/categories/73C2/products?mode=delivery&include_restrict=true&order_by=price_asc&limit=12"
        self.assertEqual(urls, [TREE_URL, base + "&offset=0", base + "&offset=12"])
        self.assertEqual(got, {"items": [row(1, "Кефир безлактозный 1%", 90.0)], "total": None, "facets": FACETS,
                               "note": "раздел сайта «Без лактозы, халяль», отобраны названия со словами «Кефиры»",
                               "url": "https://5ka.ru/search/?text=" + quote("Кефиры")})

    def test_tag_alone_in_the_default_store(self):
        got, urls = self.search({"&offset=36": {"products": [listed(7, "Тофу", "120")]}}, query="", tag="ВЕГАН", page=2,
                                state={"store": "35XY", "address": "Уточните адрес доставки"})
        base = f"{API}/v2/stores/35XY/categories/73C3/products?mode=delivery&include_restrict=true&order_by=popularity&limit=12"
        self.assertEqual(urls[1:], [base + "&offset=36", base + "&offset=48"])
        self.assertEqual(got, {"items": [row(7, "Тофу", 120.0)], "total": None, "facets": FACETS,
                               "note": DEFAULT + "\nраздел сайта «Веган, без глютена»", "url": "https://5ka.ru/search/?text="})

    def test_site_sections_are_read_once_per_store(self):
        self.search({"&offset=0": {"products": []}})
        _, urls = self.search({"&offset=0": {"products": []}})
        self.assertNotIn(TREE_URL, urls)

    def test_no_site_sections(self):
        got, _ = run(pyaterochka.search, {"&offset=0": {"products": []}}, "кефир")
        self.assertEqual((got["items"], got["facets"]), ([], []))


CARD = {"plu": 97001, "name": "Кефир 2,5%", "property_clarification": "900 г", "is_available": True,
        "prices": [{"placement_type": "regular_primary", "value": "99.99"}, {"placement_type": "promotional_primary", "value": "79.99"},
                   {"placement_type": "regular_secondary", "value": 99.99}],
        "attributes": [{"name": "Бренд", "value": "Тестовая ферма"}, {"name": "Вес", "value": "0.9", "uom": "кг"},
                       {"name": "Жирность молочного продукта", "value": "2,5%"}, {"name": "Белки", "value": "3", "uom": "г"},
                       {"name": "Страна производства", "value": "Россия", "uom": None}],
        "nutrients": [{"text": "Белки", "value": "3"}, {"text": "жиры", "value": "2.5"}, {"text": "Углеводы", "value": "4"},
                      {"text": "ккал", "value": 53}, {"text": "Кальций", "value": "120"}, {"text": "Жиры", "value": "н/д"}, {"value": "1"}],
        "rating": {"rating_average": 4.9, "rates_count": 120},
        "image_links": {"normal": ["https://img/1.jpg?w=800", "https://img/2.jpg"]},
        "description": "  Кефир\n\n свежий  ", "ingredients": "молоко нормализованное, закваска"}
COUNT = {"content": {"rating": 4.8, "rating_count": 10, "reviews_count": 7, "five": 5, "four": 1, "one": 1}}
DELIVERY = "доставка: срок и цена — только в корзине на сайте после выбора адреса"


class ProductTests(unittest.TestCase):
    def product(self, card, count, id_or_url="97001", state=STATE):
        return run(pyaterochka.product, {"/products/": card, "/count?": count}, id_or_url, state=state)

    def test_full_card(self):
        got, urls = self.product(CARD, COUNT)
        self.assertEqual(urls, [f"{API}/v2/stores/S1/products/97001?mode=delivery&include_restrict=true",
                                f"{REVIEWS}/product-reviews/count?plu_id=97001"])
        self.assertEqual(got, {
            "id": "97001", "name": "Кефир 2,5%", "brand": "Тестовая ферма", "size": "900 г", "price": 79.99, "old": 99.99,
            "available": True, "url": "https://5ka.ru/product/97001/", "rating": 4.9, "reviews": 120, "ean": None,
            "photos": ["https://img/1.jpg", "https://img/2.jpg"], "description": "Кефир свежий",
            "composition": "молоко нормализованное, закваска", "nutrition": {"protein": 3.0, "fat": 2.5, "carbs": 4.0, "kcal": 53.0},
            "composition_extra": "Жирность молочного продукта: 2,5%",
            "extra": ["характеристики: Вес: 0.9 кг; Жирность молочного продукта: 2,5%; Страна производства: Россия",
                      "отзывов с текстом 7 (grocery_reviews), звёзды: 5★ 5 4★ 1 3★ 0 2★ 0 1★ 1", DELIVERY]})

    def test_bare_card_in_the_default_store(self):
        got, urls = self.product({"plu": 5, "prices": [{"placement_type": "regular_primary", "value": 49.9}]}, ["unexpected"],
                                 "https://5ka.ru/product/voda--5/", {"store": "35XY", "address": ""})
        self.assertEqual(urls[0], f"{API}/v2/stores/35XY/products/5?mode=delivery&include_restrict=true")
        self.assertEqual(got, {
            "id": "5", "name": "", "brand": "", "size": "", "price": 49.9, "old": None, "available": False,
            "url": "https://5ka.ru/product/5/", "rating": None, "reviews": None, "ean": None, "photos": [], "description": "",
            "composition": "", "nutrition": {}, "composition_extra": "", "extra": [DEFAULT, "характеристики: ", DELIVERY]})

    def test_promotion_without_a_regular_price(self):
        got, _ = self.product({"plu": 5, "prices": [{"placement_type": "promotional_primary", "value": "40"}]}, None)
        self.assertEqual((got["price"], got["old"]), (40.0, None))

    def test_any_link_or_plu(self):
        for id_or_url in (" 97001 ", "https://5ka.ru/product/97001/", "https://5ka.ru/product/kefir-2-5--97001/", "5ka.ru/product/kefir--97001"):
            with self.subTest(id_or_url):
                self.assertEqual(self.product(CARD, None, id_or_url)[0]["id"], "97001")

    def test_not_a_plu(self):
        with patch.object(pyaterochka, "_tab") as tab, self.assertRaises(ValueError):
            pyaterochka.product("https://5ka.ru/catalog/kefir/")
        tab.assert_not_called()

    def test_unknown_product(self):
        self.assertEqual(self.product({"code": "not_found"}, None)[0], "Пятёрочка: товар 97001 не найден")

    def test_site_did_not_answer(self):
        self.assertEqual(self.product(None, None)[0], pyaterochka.BLOCKED)


class ReviewsTests(unittest.TestCase):
    def reviews(self, count, listing, *args, **kw):
        return run(pyaterochka.reviews, {"/count?": count, "/product-reviews?": listing}, *args, **kw)

    def test_a_page_of_reviews(self):
        got, urls = self.reviews(COUNT, {"items": [{"date": "2026-09-01T10:00:00Z", "rate": 5, "likes": 3, "dislikes": 1,
                                                    "text": "Вкусный\n кефир "}, {"rate": 2, "text": None}], "has_next_page": True},
                                 "97001", sort="new", with_media=True, page=2, limit=2)
        self.assertEqual(urls, [f"{REVIEWS}/product-reviews/count?plu_id=97001",
                                f"{REVIEWS}/product-reviews?plu_id=97001&page=2&page_size=2&sort=newest"])
        self.assertEqual(got, "Пятёрочка · plu 97001: рейтинг 4.8 (10 оценок), отзывов с текстом 7 · 5★ 5 4★ 1 3★ 0 2★ 0 1★ 1\n"
                              "страница 2 по 2, сортировка new. Фото и имён авторов у отзывов Пятёрочки нет (with_media не применим)\n"
                              "дата\t★\tполезно +/−\tтекст\n"
                              "2026-09-01\t5\t+3/−1\tВкусный кефир\n"
                              "\t2\t+0/−0\t\n"
                              "есть ещё: page=3")

    def test_no_reviews(self):
        got, urls = self.reviews(None, None, "https://5ka.ru/product/voda--5/")
        self.assertEqual(urls[1], f"{REVIEWS}/product-reviews?plu_id=5&page=1&page_size=20&sort=useful")
        self.assertEqual(got, "Пятёрочка · plu 5: рейтинг — (0 оценок), отзывов с текстом 0 · 5★ 0 4★ 0 3★ 0 2★ 0 1★ 0\n"
                              "страница 1 по 20, сортировка useful. Фото и имён авторов у отзывов Пятёрочки нет\n"
                              "дата\t★\tполезно +/−\tтекст\n(отзывов нет)")

    def test_unknown_sort(self):
        with patch.object(pyaterochka, "_tab") as tab:
            self.assertEqual(pyaterochka.reviews("97001", sort="best"), "sort: одно из useful, new, high, low")
        tab.assert_not_called()


CHECK_PAGE = "!!document.getElementById('__NEXT_DATA__') || location.pathname.includes('/xpvnsulc/')"
HOME = call("https://5ka.ru/", "5ka", wait_js="!!document.getElementById('__NEXT_DATA__')")


class TabTests(unittest.TestCase):
    def tab(self, paths, host="5ka.ru"):
        tab = MagicMock()
        paths = iter(paths)
        tab.js.side_effect = lambda expr: next(paths) if expr == "location.pathname" else host
        with patch.object(pyaterochka, "tab_for", return_value=tab) as tab_for:
            got = pyaterochka._tab()
        tab_for.assert_called_once_with("5ka.ru")
        self.assertIs(got, tab)
        return tab

    def test_tab_on_the_site_stays(self):
        tab = self.tab(["/catalog/"], "5ka.ru")
        tab.goto.assert_not_called()
        tab.close.assert_not_called()

    def test_tab_elsewhere_goes_home(self):
        self.assertEqual(self.tab([None], None).goto.call_args_list, [HOME])

    def test_a_stale_bot_check_page_is_reloaded_once(self):
        tab = self.tab(["/xpvnsulc/abc", "/"])
        self.assertEqual(tab.goto.call_args_list, [call("https://5ka.ru/", "5ka", wait_js=CHECK_PAGE)])
        tab.close.assert_not_called()

    def test_a_bot_check_that_stays_is_reported(self):
        tab = MagicMock()
        tab.js.return_value = "/xpvnsulc/abc"
        with patch.object(pyaterochka, "tab_for", return_value=tab), self.assertRaises(RuntimeError) as e:
            pyaterochka._tab()
        self.assertEqual(str(e.exception), pyaterochka.CHECKED)
        tab.close.assert_called_once()


class GetTests(unittest.TestCase):
    def get(self, *answers, last=0.0):
        tab = MagicMock()
        tab.js.side_effect = list(answers)
        with patch.object(pyaterochka, "_last", last), patch.object(pyaterochka.time, "sleep") as sleep, \
                patch.object(pyaterochka, "log") as log:
            got = pyaterochka._get(tab, "https://5d.5ka.ru/api/x")
        return got, tab, sleep, log

    def test_json_answer(self):
        got, tab, sleep, log = self.get({"s": 200, "b": '{"products": []}'})
        self.assertEqual(got, {"products": []})
        self.assertIn('fetch("https://5d.5ka.ru/api/x", {credentials: \'include\'})', tab.js.call_args.args[0])
        sleep.assert_not_called()
        tab.goto.assert_not_called()
        log.warning.assert_not_called()

    def test_requests_are_spaced(self):
        _, _, sleep, _ = self.get({"s": 200, "b": "[]"}, last=time.time())
        self.assertGreater(sleep.call_args.args[0], 0.5)

    def test_waf_page_renews_the_cookies_once(self):
        got, tab, _, log = self.get({"s": 403, "b": "<html>"}, {"s": 200, "b": "[1]"})
        self.assertEqual(got, [1])
        self.assertEqual(tab.goto.call_args_list, [HOME])
        log.warning.assert_called_once_with("5ka %s: %s non-JSON%s", "https://5d.5ka.ru/api/x", 403, "")

    def test_waf_page_twice_is_no_answer(self):
        got, tab, _, log = self.get({"s": 403, "b": "<html>"}, {"s": 0, "b": "TypeError: Failed to fetch"})
        self.assertIsNone(got)
        self.assertEqual(tab.goto.call_args_list, [HOME])
        self.assertEqual(log.warning.call_args_list[1], call("5ka %s: %s non-JSON%s", "https://5d.5ka.ru/api/x", 0, " again"))


if __name__ == "__main__":
    unittest.main()
