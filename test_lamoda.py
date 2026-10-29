"""Lamoda search rows from the page state (window.__NUXT__), in the shape the site has used since 2026-10.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_lamoda"""
import unittest
from unittest.mock import MagicMock, patch

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


if __name__ == "__main__":
    unittest.main()
