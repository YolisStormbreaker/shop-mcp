"""A product's id from what the user gives: a bare id or a link to the product, for each grocery store.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_ids"""
import unittest

from grocery import lenta, perekrestok, pyaterochka, vkusvill

CASES = {
    lenta._id: [("84812", "84812"), (" 84812 ", "84812"), (84812, "84812"),
                ("https://lenta.com/product/kefir-25-930g-84812/", "84812"), ("https://lenta.com/product/kefir-84812?x=1", "84812")],
    vkusvill._id: [("158", "158"), ("https://vkusvill.ru/goods/kefir-158/", "158"),
                   ("https://vkusvill.ru/goods/kefir-158?from=a", "158")],
    perekrestok._plu: [("2093082", "2093082"), ("plu2093082", "2093082"), (" plu 2093082", None),
                       ("https://www.perekrestok.ru/cat/1589/p/kefir-2093082", "2093082"),
                       ("https://www.perekrestok.ru/cat/1589/p/kefir-2093082/reviews", "2093082")],
    pyaterochka._plu: [("97452", "97452"), ("https://5ka.ru/product/kefir--97452/", "97452"), ("https://5ka.ru/product/97452/", "97452"),
                       ("5ka.ru/product/kefir--97452", "97452")],
}
NOT_IDS = ["кефир", "https://lenta.com/catalog/moloko/", "", "12a"]


class ProductIdTests(unittest.TestCase):
    def test_ids_and_links(self):
        for parse, cases in CASES.items():
            for given, want in cases:
                with self.subTest(store=parse.__module__, given=given):
                    if want is None:
                        self.assertRaises(ValueError, parse, given)
                    else:
                        self.assertEqual(parse(given), want)

    def test_what_is_not_an_id_names_the_store(self):
        for parse, word in ((lenta._id, "Ленты"), (vkusvill._id, "ВкусВилла"), (perekrestok._plu, "Перекрёстка"), (pyaterochka._plu, "Пятёрочки")):
            for given in NOT_IDS:
                with self.subTest(store=word, given=given), self.assertRaisesRegex(ValueError, word):
                    parse(given)


if __name__ == "__main__":
    unittest.main()
