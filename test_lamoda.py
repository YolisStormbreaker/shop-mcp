"""Lamoda: the page state (window.__NUXT__, in the shape the site has used since 2026-10), the reviews and cart APIs -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_lamoda"""
import json
import unittest
from unittest.mock import MagicMock, call, patch

import lamoda


def product(sku, title, prices, sizes, ad=False, rating=4.9, reviews=563):
    p = {"sku": sku, "title": title, "brand": {"title": "Omsa"}, "seo_tail": "clothes-omsa-noski", "prices": prices,
         "average_rating": rating, "counters": {"reviews": reviews},
         "sizes": [{"brand_title": t, "stock_quantity": n} for t, n in sizes]}
    if ad:
        p["ad_params"] = "token"
    return {"type": "product", "product": p, "rating": {"is_show": True}}


STATE = {
    "pagination": {"page": 1, "pages": 226, "found": 13523},
    "products": [
        product("MP002XM01L0O", "Носки 5 пар",
                {"action": {"discount": {"active_to": "2026-10-29T23:59:59.000+03:00", "percent": 30}, "price": "728"},
                 "original": {"price": "1 040"}},
                [("39/41", 233), ("42/44", 0), ("45/47", 289)]),
        {"type": "ads_row_banner", "banner": {"title": "Скидки"}},
        product("RTLADB123456", "Носки 3 пары", {"onsite": {"discount": {"percent": 15}, "price": "660"}, "original": {"price": "777"}},
                [("38", 4)], ad=True, rating=None, reviews=0),
        product("RTLADB654321", "Носки", {"original": {"price": "1 227"}}, [("40", 0)]),
    ],
}


class LamodaSearchTests(unittest.TestCase):
    def search(self, state, **kw):
        return self.search_with_mocks(state, **kw)[0].splitlines()

    def search_with_mocks(self, state, **kw):
        tab = MagicMock()
        tab.js.side_effect = ["", state, "<html></html>"]  # previous request id, the new page's state, its markup
        with patch.object(lamoda, "tab_for", return_value=tab), patch.object(lamoda, "dump", return_value="saved") as dump, \
                patch.object(lamoda, "log") as log:
            return lamoda.search("носки", **kw), tab, dump, log

    def test_whole_answer(self):
        got, tab, _, _ = self.search_with_mocks(STATE)
        url = "https://www.lamoda.ru/catalogsearch/result/?q=%D0%BD%D0%BE%D1%81%D0%BA%D0%B8"
        self.assertEqual(got, f"Lamoda · 13523 найдено · страница 1 из 226 · {url}\n"
                              "ссылки относительно https://www.lamoda.ru; цена — со всеми скидками, включая вашу скидку лояльности; "
                              "«до» — когда кончается акционная цена; размеры в наличии — в системе бренда\n"
                              "#\tsku\tцена ₽\tбез скидок\tакция до\tбренд\tназвание\tрейтинг\tотзывов\tразмеры в наличии\tпометки\tссылка\n"
                              "1\tMP002XM01L0O\t728\t1040\t2026-10-29\tOmsa\tНоски 5 пар\t4.9\t563\t39/41 45/47\t\t/p/mp002xm01l0o/clothes-omsa-noski/\n"
                              "2\tRTLADB123456\t660\t777\t\tOmsa\tНоски 3 пары\t\t\t38\tреклама\t/p/rtladb123456/clothes-omsa-noski/\n"
                              "3\tRTLADB654321\t1227\t\t\tOmsa\tНоски\t4.9\t563\t\t\t/p/rtladb654321/clothes-omsa-noski/")
        self.assertEqual(tab.goto.call_args.args, (url, "lamoda"))
        self.assertIn('.catalog_request_id !== ""', tab.goto.call_args.kwargs["wait_js"])
        tab.close.assert_called_once()

    def test_sort_price_and_page_go_into_the_url(self):
        _, tab, _, _ = self.search_with_mocks(STATE, price_min=500, sort="price_asc", page=2)
        self.assertEqual(tab.goto.call_args.args[0], "https://www.lamoda.ru/catalogsearch/result/"
                                                     "?q=%D0%BD%D0%BE%D1%81%D0%BA%D0%B8&sort=price_asc&price=500%2C10000000&page=2")
        _, tab, _, _ = self.search_with_mocks(STATE, price_max=900)
        self.assertTrue(tab.goto.call_args.args[0].endswith("&price=0%2C900"))

    def test_unknown_sort(self):
        self.assertEqual(lamoda.search("носки", sort="cheap"), "sort: одно из default, new, price_asc, price_desc, new_sale, discount")

    def test_no_products_and_no_pagination(self):
        self.assertEqual(self.search({"pagination": {}, "products": []})[0::3],
                         ["Lamoda · 0 найдено · страница 1 из 1 · https://www.lamoda.ru/catalogsearch/result/?q=%D0%BD%D0%BE%D1%81%D0%BA%D0%B8",
                          "(пусто)"])

    def test_bare_product(self):
        state = {"pagination": {}, "products": [{"type": "product", "product": {"sku": "AB123"}}]}
        self.assertEqual(self.search(state)[3], "1\tAB123\t0\t\t\t\t\t\t\t\t\t/p/ab123//")

    def test_blocked_page_is_saved(self):
        got, tab, dump, log = self.search_with_mocks(None)
        self.assertEqual(got, lamoda.BLOCKED)
        dump.assert_called_once_with("lamoda", "search", "<html></html>")
        self.assertEqual(log.warning.call_args.args[2:], ("saved",))
        tab.close.assert_called_once()

    def test_header_counts_the_site_results(self):
        self.assertTrue(self.search(STATE)[0].startswith("Lamoda · 13523 найдено · страница 1 из 226 · https://www.lamoda.ru/"))

    def test_discounted_product_row(self):
        self.assertEqual(self.search(STATE)[3], "1\tMP002XM01L0O\t728\t1040\t2026-10-29\tOmsa\tНоски 5 пар\t4.9\t563\t"
                                                "39/41 45/47\t\t/p/mp002xm01l0o/clothes-omsa-noski/")

    def test_banners_are_skipped_and_ads_marked(self):
        rows = self.search(STATE)[3:]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1].split("\t")[1:5], ["RTLADB123456", "660", "777", ""])
        self.assertEqual(rows[1].split("\t")[7:11], ["", "", "38", "реклама"])

    def test_full_price_has_no_old_price(self):
        self.assertEqual(self.search(STATE)[5].split("\t")[2:5], ["1227", "", ""])

    def test_limit(self):
        self.assertEqual(len(self.search(STATE, limit=1)), 4)

    def test_page_without_products_is_reported(self):
        self.assertTrue(self.search(None)[0].startswith("⚠️ Lamoda не отдала"))


DESCRIPTION = "Свободный свитер. " * 150
ITEM = {
    "sku": "MP002XW0ABCD", "title": "Свитер", "model_title": "Oversize Knit", "brand": {"title": "Befree", "name": "befree"},
    "prices": {"original": {"price": "4 999"}, "loyalty": {"price": "4 499", "discount": {"percent": 10}},
               "promocode": {"price": "3 999", "discount": {"percent": 20, "promocode": "AUTUMN"}}},
    "seller": {"title": "Lamoda"}, "is_returnable": True, "is_in_stock": True,
    "sizes": [{"title": "42", "brand_title": "XS", "brand_size_system": "INT", "stock_quantity": 3},
              {"title": "44", "brand_title": "44", "brand_size_system": "RU", "stock_quantity": 0}, {"title": "46", "stock_quantity": 1}],
    "attributes": [{"title": "Состав", "value": "Хлопок - 100%"}, {"title": "Сезон", "value": "мульти"}],
    "description": DESCRIPTION,
    "delivery": {"best_delivery_info": {"description": "Доставка в Москву: завтра",
                                        "delivery_data": [{"type": "courier", "courier": {"info": {"title": "Курьером — завтра, бесплатно"}}},
                                                          {"type": "pickup", "pickup": {}}, {"type": "post"}]}},
    "gallery": [f"/M/P/MP002XW0ABCD_{i}_v1.jpg" for i in range(1, 12)], "average_rating": 4.7, "counters": {"reviews": 12}}
BARE_ITEM = {"sku": "AB123XY45678", "title": "Шарф"}
NAMED_ITEM = {"sku": "AB123XY45678", "title": "Шарф", "brand": {"name": "Noname"}, "is_in_stock": True, "prices": {"original": {"price": 1500}},
              "delivery": {"best_delivery_info": {"delivery_data": [{"type": "courier", "courier": {"info": {"title": "Курьером"}}}]}}}


class LamodaItemTests(unittest.TestCase):
    def item(self, product, sku_or_url="MP002XW0ABCD", full=False):
        tab = MagicMock()
        tab.js.side_effect = [product, "<html></html>"]  # the page's __NUXT__ product, its markup
        with patch.object(lamoda, "tab_for", return_value=tab), patch.object(lamoda, "dump", return_value="saved") as dump, \
                patch.object(lamoda, "log") as log:
            return lamoda.item(sku_or_url, full), tab, dump, log

    def test_full_card(self):
        got, tab, _, _ = self.item(ITEM)
        self.assertEqual(got, "Befree Oversize Knit (Свитер) — 3999 ₽, без скидок 4999 ₽\n"
                              "https://www.lamoda.ru/p/mp002xw0abcd/\n"
                              "sku: MP002XW0ABCD · продавец: Lamoda · можно вернуть\n"
                              "размеры: 42 (INT XS): 3 шт; 44: нет; 46: 1 шт\n"
                              "цены: original 4 999 ₽; loyalty 4 499 ₽ (−10%); promocode 3 999 ₽ (−20%, промокод AUTUMN)\n"
                              "доставка: Доставка в Москву: завтра; Курьером — завтра, бесплатно\n"
                              "рейтинг 4.7, отзывов на этот цвет 12 (все цвета — lamoda_reviews)\n"
                              "фото (shop_images): " + " ".join(f"https://a.lmcdn.ru/product/M/P/MP002XW0ABCD_{i}_v1.jpg" for i in range(1, 11)) + "\n"
                              "характеристики: Состав: Хлопок - 100%; Сезон: мульти\n"
                              "\n" + DESCRIPTION[:2500])
        self.assertEqual(tab.goto.call_args.args, ("https://www.lamoda.ru/p/mp002xw0abcd/", "lamoda"))
        self.assertTrue(tab.goto.call_args.kwargs["wait_js"].endswith('?.product?.sku?.toLowerCase() === "mp002xw0abcd"'))
        tab.close.assert_called_once()

    def test_full_description(self):
        self.assertTrue(self.item(ITEM, full=True)[0].endswith("\n\n" + DESCRIPTION))

    def test_a_marketplace_seller_is_named_from_the_owner(self):
        # the site's seller.title for a partner is the link text «подробнее»; the name is in product.owner
        partner = {**ITEM, "seller": {"title": "подробнее", "id": "426"},
                   "owner": {"id": "426", "shop_name": "ТМ Тест", "company_name": 'ООО "Тест"'}}
        got, _, _, _ = self.item(partner)
        self.assertIn('sku: MP002XW0ABCD · продавец: ТМ Тест (ООО "Тест") · можно вернуть', got.splitlines())
        got, _, _, _ = self.item({**partner, "owner": {"company_name": 'ООО "Тест"'}})
        self.assertIn('sku: MP002XW0ABCD · продавец: ООО "Тест" · можно вернуть', got.splitlines())

    def test_bare_card_by_relative_link(self):
        got, tab, _, _ = self.item(BARE_ITEM, " /p/ab123xy45678/sharf/?utm_source=x ")
        self.assertEqual(tab.goto.call_args.args[0], "https://www.lamoda.ru/p/ab123xy45678/sharf/?utm_source=x")
        self.assertEqual(got, "Шарф (Шарф)\nhttps://www.lamoda.ru/p/ab123xy45678/sharf/\n"
                              "sku: AB123XY45678 · продавец:  · ⚠️ без возврата\nнет в наличии\n"
                              "рейтинг —, отзывов на этот цвет 0 (все цвета — lamoda_reviews)\n\n")

    def test_in_stock_without_sizes_at_one_price(self):
        got, tab, _, _ = self.item(NAMED_ITEM, "https://www.lamoda.ru/c/355/clothes-sharfy/")
        self.assertTrue(tab.goto.call_args.kwargs["wait_js"].startswith("!!window.__NUXT__"))
        self.assertEqual(got.splitlines()[:6], ["Noname Шарф (Шарф) — 1500 ₽", "https://www.lamoda.ru/c/355/clothes-sharfy/",
                                                "sku: AB123XY45678 · продавец:  · ⚠️ без возврата", "в наличии",
                                                "цены: original 1500 ₽", "доставка: Курьером"])

    def test_blocked_page_is_saved(self):
        got, tab, dump, log = self.item(None)
        self.assertEqual(got, lamoda.BLOCKED)
        dump.assert_called_once_with("lamoda", "item", "<html></html>")
        self.assertEqual(log.warning.call_args.args[1:], ("https://www.lamoda.ru/p/mp002xw0abcd/", "saved"))
        tab.close.assert_called_once()


REVIEWS = {"total": 45, "total_photos": 3, "reviews": [
    {"created_time": "2026-09-01T12:00:00+03:00", "rating": 5, "like_count": 4, "dislike_count": 1, "text": "Хорошие\n  носки",
     "snippet": {"purchase": {"value": "42/44", "combines": {"color": "чёрный", "pattern": ""}}, "header": {"author": "Покупатель А."},
                 "item_params": [{"title": "Размер: в размер"}, {"title": ""}, {"title": "Полнота: нормальная"}]},
     "photos": [{"url": "https://a.lmcdn.ru/photoreview/?key=a1"}, {"url": ""}, {}]},
    {}]}
REVIEWS_INFO = {"average_rating": 4.8, "total_review_count": 563, "total_photos_count": 7,
                "average_fittings": {"size": {"title": "в размер"}, "width": {"title": ""}, "note": "x", "fit": {"title": "по фигуре"}}}


class LamodaReviewsTests(unittest.TestCase):
    def reviews(self, d, info, sku_or_url="MP002XM01L0O", **kw):
        tab = MagicMock()
        with patch.object(lamoda, "_lm_tab", return_value=tab), patch.object(lamoda, "_api", side_effect=[d, info]) as api:
            return lamoda.reviews(sku_or_url, **kw), api, tab

    def test_page_with_reviews(self):
        got, api, tab = self.reviews(REVIEWS, REVIEWS_INFO)
        self.assertEqual(got, "Lamoda · MP002XM01L0O: рейтинг 4.8, отзывов 563, фото в отзывах 7 · по отзывам: в размер; по фигуре\n"
                              "все цвета модели: 45, страница 1 из 3 по 20, сортировка useful\n"
                              "дата\t★\tполезно +/−\tкуплено (размер, цвет)\tавтор\tтекст\tфото (shop_images)\n"
                              "2026-09-01\t5\t+4/−1\t42/44, чёрный\tПокупатель А.\tХорошие носки | Размер: в размер; Полнота: нормальная\t"
                              "https://a.lmcdn.ru/photoreview/?key=a1\n"
                              "\t\t+0/−0\t\t\t\t")
        self.assertEqual([c.args[1:] for c in api.call_args_list], [
            ("POST", "/api/v1/product/reviews_v2", {"limit": 20, "offset": 0, "sku": "MP002XM01L0O", "with_related": True,
                                                    "sort": "ranking_score", "sort_direction": "desc"}),
            ("GET", "/api/v1/product/reviews_info?sku=MP002XM01L0O&with_related=true")])
        self.assertIs(api.call_args.args[0], tab)
        tab.close.assert_called_once()

    def test_this_color_with_photos_without_info(self):
        got, api, _ = self.reviews({"total": 0, "reviews": []}, None, "https://www.lamoda.ru/p/mp002xm01l0o/clothes-omsa/",
                                   sort="low", with_media=True, page=2, this_color=True, limit=10)
        self.assertEqual(got, "Lamoda · MP002XM01L0O: рейтинг —, отзывов 0, фото в отзывах 0\n"
                              "только этот цвет: 0 с фото, страница 2 из 1 по 10, сортировка low\n"
                              "дата\t★\tполезно +/−\tкуплено (размер, цвет)\tавтор\tтекст\tфото (shop_images)\n(отзывов нет)")
        self.assertEqual([c.args[1:] for c in api.call_args_list], [
            ("POST", "/api/v1/product/reviews_v2", {"limit": 10, "offset": 10, "sku": "MP002XM01L0O", "with_related": False,
                                                    "sort": "rating", "sort_direction": "asc", "only_with_photos": True}),
            ("GET", "/api/v1/product/reviews_info?sku=MP002XM01L0O&with_related=false")])

    def test_counts_from_the_list_when_info_has_none(self):
        got, _, _ = self.reviews({"total": 41, "total_photos": 2, "reviews": None}, {}, " mp002xm01l0o ")
        self.assertEqual(got.splitlines()[:2], ["Lamoda · MP002XM01L0O: рейтинг —, отзывов 41, фото в отзывах 2",
                                                "все цвета модели: 41, страница 1 из 3 по 20, сортировка useful"])

    def test_blocked(self):
        got, _, tab = self.reviews(None, None)
        self.assertEqual(got, lamoda.BLOCKED)
        tab.close.assert_called_once()

    def test_bad_arguments(self):
        self.assertEqual(lamoda.reviews("MP002XM01L0O", sort="best"), "sort: одно из useful, new, high, low")
        self.assertEqual(lamoda.reviews("носки"), "нужен sku Lamoda или ссылка https://www.lamoda.ru/p/<sku>/...")


SWEATER = {"size": {"sku": "MP002XW0ABCDE420", "title": "42"}, "quantity": 1, "total_price": 3999, "original_price": 4999,
           "product": {"brand": {"title": "Befree"}, "title": "Свитер"}}
SCARF = {"size": {"sku": "AB123XY45678ONE"}, "quantity": 2, "total_price": 3000, "original_price": 3000, "product": {"title": "Шарф"}}
CART = {"total_quantity": 3, "total_price": 6999, "packages": [{"items": [SWEATER]}, {"items": [SCARF, {"size": {}}]}, {}]}
CART_HEAD = "sku размера\tшт\tсумма ₽\tбез скидок\tбренд\tназвание\tразмер\n"
CART_TEXT = ("корзина Lamoda: 3 шт, итого 6999 ₽ (со всеми скидками)\n" + CART_HEAD +
             "MP002XW0ABCDE420\t1\t3999\t4999\tBefree\tСвитер\t42\n"
             "AB123XY45678ONE\t2\t3000\t\t\tШарф\t\n"
             "None\tNone\tNone\t\t\t\t")
SCARF_CART = {"total_quantity": 2, "total_price": 3000, "packages": [{"items": [SCARF]}]}
SCARF_TEXT = "корзина Lamoda: 2 шт, итого 3000 ₽ (со всеми скидками)\n" + CART_HEAD + "AB123XY45678ONE\t2\t3000\t\t\tШарф\t"
SIZES = [{"sku": "MP002XW0ABCDE420", "title": "42", "brand": "XS", "stock": 3}, {"sku": "MP002XW0ABCDE440", "title": "44", "brand": "44", "stock": 0},
         {"sku": "MP002XW0ABCDE460", "title": "46", "brand": "", "stock": 1}]
SIZE_NAMES = "42 (XS): 3 шт, 44: 0 шт, 46: 1 шт"
SIZES_JS = ("(window.__NUXT__?.payload?.state?.payload?.product?.sizes || [])"
            ".map(s => ({sku: s.sku, title: s.title, brand: s.brand_title || '', stock: s.stock_quantity || 0}))")
GEO_JS = "decodeURIComponent((document.cookie.match(/(?:^|; )gd_aoid=([^;]+)/) || [])[1] || '')"
GET = ("GET", "/api/v1/cart/get", None)


class LamodaCartTests(unittest.TestCase):
    """The cart tools with the site mocked: the answer, and every request that would go to Lamoda (bodies as sent)."""

    def call(self, fn, *args, answers=(), js=()):
        tab = MagicMock()
        tab.js.side_effect = list(js)  # a page read the test did not expect raises StopIteration
        with patch.object(lamoda, "_lm_tab", return_value=tab) as lm_tab, patch.object(lamoda, "_api", side_effect=list(answers)) as api:
            got = fn(*args)
        for c in api.call_args_list:
            self.assertIs(c.args[0], tab)
        sent = [(c.args[1], c.args[2], None if len(c.args) < 4 else json.dumps(c.args[3])) for c in api.call_args_list]
        self.assertEqual(tab.close.call_count, lm_tab.call_count)
        return got, sent, tab, lm_tab

    def test_cart(self):
        got, sent, tab, _ = self.call(lamoda.cart, answers=[CART])
        self.assertEqual(got, CART_TEXT)
        self.assertEqual(sent, [GET])
        tab.close.assert_called_once()

    def test_empty_cart(self):
        for d in ({"total_quantity": 0, "packages": []}, {}, {"packages": [{"items": None}]}):
            self.assertEqual(self.call(lamoda.cart, answers=[d])[0], "корзина Lamoda пуста")

    def test_cart_blocked(self):
        got, _, tab, _ = self.call(lamoda.cart, answers=[None])
        self.assertEqual(got, lamoda.BLOCKED)
        tab.close.assert_called_once()

    def add(self, sku_or_url="MP002XW0ABCD", size=None, sizes=SIZES, geo="test-aoid", answers=({}, CART)):
        return self.call(lamoda.add_to_cart, sku_or_url, size, answers=answers, js=[sizes, geo])

    def test_add_a_size_by_its_brand_name(self):
        got, sent, tab, _ = self.add(size="xs")
        self.assertEqual(got, "добавлено: MP002XW0ABCDE420, размер 42\n" + CART_TEXT)
        self.assertEqual(sent, [("POST", "/api/v1/cart/add", '{"sku": "MP002XW0ABCDE420", "geo": {"aoid": "test-aoid"}}'), GET])
        self.assertEqual(tab.goto.call_args_list, [call(
            "https://www.lamoda.ru/p/mp002xw0abcd/", "lamoda", wait_js='window.__NUXT__?.payload?.state?.payload?.product?.sku === "MP002XW0ABCD"')])
        self.assertEqual([c.args for c in tab.js.call_args_list], [(SIZES_JS,), (GEO_JS,)])
        tab.close.assert_called_once()

    def test_add_a_size_by_its_title_or_sku_from_a_link(self):
        cart = {"total_quantity": 1, "total_price": 2500, "packages": [{"items": [{**SWEATER, "size": {"sku": "MP002XW0ABCDE460", "title": "46"}}]}]}
        for size in (" 46 ", "mp002xw0abcde460"):
            got, sent, tab, _ = self.add(" https://www.lamoda.ru/p/mp002xw0abcd/clothes-befree-sviter/?utm=x ", size, answers=[{}, cart])
            self.assertEqual(got.splitlines()[0], "добавлено: MP002XW0ABCDE460, размер 46")
            self.assertEqual(sent[0], ("POST", "/api/v1/cart/add", '{"sku": "MP002XW0ABCDE460", "geo": {"aoid": "test-aoid"}}'))
            self.assertEqual(tab.goto.call_args.args[0], "https://www.lamoda.ru/p/mp002xw0abcd/")

    def test_add_the_only_size_without_naming_it(self):
        got, sent, _, _ = self.add(" mp002xw0abcd ", sizes=SIZES[:1])
        self.assertEqual(got, "добавлено: MP002XW0ABCDE420, размер 42\n" + CART_TEXT)
        self.assertEqual(sent[0][2], '{"sku": "MP002XW0ABCDE420", "geo": {"aoid": "test-aoid"}}')

    def test_add_not_confirmed(self):
        got, sent, _, _ = self.add(size="46", answers=[None, SCARF_CART])
        self.assertEqual(got, "⚠️ Lamoda не подтвердила добавление: MP002XW0ABCDE460, размер 46\n" + SCARF_TEXT)
        self.assertEqual(len(sent), 2)

    def test_add_then_the_cart_is_blocked(self):
        got, sent, tab, _ = self.add(size="42", answers=[{}, None])
        self.assertEqual(got, lamoda.BLOCKED)
        self.assertEqual([s[:2] for s in sent], [("POST", "/api/v1/cart/add"), GET[:2]])
        tab.close.assert_called_once()

    def test_add_sends_nothing_without_a_size_in_stock(self):
        for size, sizes, want in [
                (None, SIZES, "у товара несколько размеров, укажи size: " + SIZE_NAMES),
                ("XL", SIZES, "нет размера «XL»; есть: " + SIZE_NAMES),
                ("44", SIZES, "размер 44 закончился; есть: " + SIZE_NAMES),
                (None, [{**SIZES[0], "stock": 0}], "размер 42 закончился; есть: 42 (XS): 0 шт"),
                ("42", [], lamoda.BLOCKED), ("42", None, lamoda.BLOCKED)]:
            got, sent, tab, _ = self.call(lamoda.add_to_cart, "MP002XW0ABCD", size, js=[sizes])
            self.assertEqual(got, want)
            self.assertEqual(sent, [])
            tab.close.assert_called_once()

    def test_add_sends_nothing_without_the_delivery_region(self):
        got, sent, tab, _ = self.add(size="42", geo="")
        self.assertEqual(got, "⚠️ не нашёл регион доставки Lamoda (cookie gd_aoid): открой сайт и выбери город")
        self.assertEqual(sent, [])
        tab.close.assert_called_once()

    def test_add_needs_a_sku_or_a_link(self):
        for s in ("носки", "MP002XW0ABC", "MP002XW0ABCDE", "https://www.lamoda.ru/c/355/clothes-sharfy/"):
            got, _, _, lm_tab = self.call(lamoda.add_to_cart, s, "42")
            self.assertEqual(got, "нужен sku товара (из lamoda_search) или ссылка на товар")
            lm_tab.assert_not_called()

    def test_remove(self):
        got, sent, tab, _ = self.call(lamoda.remove_from_cart, " mp002xw0abcde420 ", answers=[CART, {}, SCARF_CART], js=["test-aoid"])
        self.assertEqual(got, "удалено: MP002XW0ABCDE420\n" + SCARF_TEXT)
        self.assertEqual(sent, [GET, ("POST", "/api/v1/cart/remove", '{"skus": ["MP002XW0ABCDE420"], "geo": {"aoid": "test-aoid"}}'), GET])
        self.assertEqual([c.args for c in tab.js.call_args_list], [(GEO_JS,)])
        tab.goto.assert_not_called()
        tab.close.assert_called_once()

    def test_remove_without_the_delivery_region_sends_no_geo(self):
        _, sent, _, _ = self.call(lamoda.remove_from_cart, "MP002XW0ABCDE420", answers=[CART, {}, SCARF_CART], js=[""])
        self.assertEqual(sent[1], ("POST", "/api/v1/cart/remove", '{"skus": ["MP002XW0ABCDE420"], "geo": null}'))

    def test_remove_not_confirmed(self):
        got, _, _, _ = self.call(lamoda.remove_from_cart, "MP002XW0ABCDE420", answers=[CART, None, CART], js=["test-aoid"])
        self.assertEqual(got, "⚠️ Lamoda не подтвердила удаление: MP002XW0ABCDE420\n" + CART_TEXT)

    def test_remove_what_is_not_in_the_cart(self):
        got, sent, tab, _ = self.call(lamoda.remove_from_cart, "MP002XW0ABCDE440", answers=[CART])
        self.assertEqual(got, "такого sku размера в корзине нет\n" + CART_TEXT)
        self.assertEqual(sent, [GET])
        tab.close.assert_called_once()

    def test_remove_blocked(self):
        got, sent, tab, _ = self.call(lamoda.remove_from_cart, "MP002XW0ABCDE420", answers=[None])
        self.assertEqual((got, sent), (lamoda.BLOCKED, [GET]))
        tab.close.assert_called_once()
        got, sent, tab, _ = self.call(lamoda.remove_from_cart, "MP002XW0ABCDE420", answers=[CART, {}, None], js=["test-aoid"])
        self.assertEqual((got, len(sent)), (lamoda.BLOCKED, 3))
        tab.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
