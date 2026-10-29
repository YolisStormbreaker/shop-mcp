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
        tab = MagicMock()
        tab.js.side_effect = ["", state, "<html></html>"]  # previous request id, the new page's state, its markup
        with patch.object(lamoda, "tab_for", return_value=tab), patch.object(lamoda, "dump", return_value="saved"), \
                patch.object(lamoda, "log"):
            return lamoda.search("носки", **kw).splitlines()

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
