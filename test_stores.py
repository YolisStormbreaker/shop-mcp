"""stores.py: which store sells what — a store is a specialist (its categories) or broad (everything but); the answers
of shop_stores() and the routing lines of the server's instructions come from that one table.
Run: .venv/bin/python -B -m unittest -v test_stores"""
import unittest

import stores
from stores import Store

TABLE = {"ozon": Store("Ozon", lacks={"used"}, note="маркетплейс"),
         "dns": Store("DNS", sells={"phones", "computers"}, note="техника"),
         "drhead": Store("Dr.Head", sells={"audio"}, note="наушники и Hi-Fi"),
         "avito": Store("Авито", sells={"used"})}


class StoreTests(unittest.TestCase):
    def test_a_store_is_either_a_specialist_or_broad_with_known_categories(self):
        for kw in ({}, {"sells": {"audio"}, "lacks": {"used"}}, {"sells": {"sound"}}, {"lacks": {"sound"}}, {"sells": set()}):
            with self.subTest(kw), self.assertRaises(ValueError):
                Store("X", **kw)
        self.assertTrue(Store("X", lacks=set()).has("food"))          # a broad store that sells everything

    def test_has(self):
        self.assertEqual([TABLE["ozon"].has("audio"), TABLE["ozon"].has("used"), TABLE["dns"].has("phones"), TABLE["dns"].has("audio")],
                         [True, False, True, False])

    def test_the_real_table_is_well_formed(self):
        self.assertGreater(len(stores.STORES), 10)
        for key, s in stores.STORES.items():
            with self.subTest(key):
                self.assertTrue(s.name and s.note, key)
        for cat in stores.CATEGORIES:                                 # every category has somewhere to go
            self.assertTrue(stores.where(cat), cat)


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, stores, "STORES", stores.STORES)
        stores.STORES = TABLE

    def test_where_puts_the_specialists_first(self):
        self.assertEqual(stores.where("audio"), ["drhead", "ozon"])
        self.assertEqual(stores.where("phones"), ["dns", "ozon"])
        self.assertEqual(stores.where("used"), ["avito"])

    def test_one_category(self):
        self.assertEqual(stores.answer("audio").splitlines(),
                         ["audio — наушники, колонки, Hi-Fi и плееры, усилители и ЦАП, микрофоны",
                          "специализированные: Dr.Head (drhead_*) — наушники и Hi-Fi",
                          "широкий ассортимент: Ozon (ozon_*) — маркетплейс"])

    def test_the_whole_map(self):
        lines = stores.answer().splitlines()
        self.assertEqual(lines[0], "магазины и что в них искать (category — для shop_stores(category)):")
        self.assertIn("Ozon (ozon_*): всё, кроме used — маркетплейс", lines)
        self.assertIn("DNS (dns_*): phones, computers — техника", lines)
        self.assertIn("категории:", lines)
        self.assertIn("audio — наушники, колонки, Hi-Fi и плееры, усилители и ЦАП, микрофоны", lines)

    def test_an_unknown_category_lists_the_known_ones(self):
        self.assertTrue(stores.answer("sound").startswith("нет такой категории «sound»: phones, computers, "), stores.answer("sound"))

    def test_routing_lines_name_the_specialists_of_each_category(self):
        self.assertEqual(stores.routing(), ["phones, computers: DNS", "audio: Dr.Head", "used: Авито",   # one line for one set
                                            "везде, кроме названного у них: Ozon"])


if __name__ == "__main__":
    unittest.main()
