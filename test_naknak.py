"""НакНак: what the site's pages show (a menu section's models, a model's card) -> the tools' text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_naknak"""
import unittest
from unittest.mock import MagicMock, patch

import naknak
import pace

ORIGIN = 1700000000123.5


def run(fn, shown, *args, **kw):
    """fn with a tab whose js() answers performance.timeOrigin before the load and then the page's extraction."""
    tab = MagicMock()
    tab.js.side_effect = lambda expr, **k: ORIGIN if expr == "performance.timeOrigin" else shown
    with patch.object(naknak, "tab_for", return_value=tab) as tab_for, patch.object(naknak, "log") as log:
        got = fn(*args, **kw)
    return got, tab, tab_for, log


def model(href, name, price, label=""):
    return {"href": href, "name": f" {name} ", "label": label, "price": f" от {price} руб. "}


SECTION = {"path": "/phones/", "oid": None, "title": "Купить", "h1": "Телефоны", "ld": None,
           "models": [model("/iphone/fon-2-pro/", "Фон 2 Pro", "108 600", "новинка"), model("/iphone/fon-2/", "Фон 2", "75 000"),
                      model("/iphone/fon-1-pro/", "Фон 1 Pro", "61 200"), {"href": "/iphone/x/", "name": "X", "label": "", "price": ""}]}
HEAD = "#\tid\tцена от ₽\tназвание\tссылка\n"
NOTE = ("; цена — «от», за самую дешёвую конфигурацию; точная цена, варианты и наличие — naknak_item; "
        "ссылки относительно https://naknak.ru; магазин в Москве\n")


class NaknakSearchTests(unittest.TestCase):
    def test_the_section_named_and_its_models_with_the_other_words(self):
        got, tab, tab_for, _ = run(naknak.search, SECTION, "Айфон 2 PRO")
        self.assertEqual(got, "НакНак · 1 найдено · страница 1 (по 50) · https://naknak.ru/iphone/\n"
                              "поиска у сайта нет: это модели его раздела iPhone со словами «2 pro»" + NOTE + HEAD +
                              "1\tiphone/fon-2-pro\t108600\tФон 2 Pro (новинка)\t/iphone/fon-2-pro/")
        tab_for.assert_called_once_with("naknak.ru")
        self.assertEqual(tab.goto.call_args.args, ("https://naknak.ru/iphone/", "naknak"))
        self.assertEqual(tab.goto.call_args.kwargs["wait_js"],
                         f"performance.timeOrigin !== {ORIGIN} && (document.readyState === 'complete')")
        self.assertEqual(tab.js.call_args.args, (naknak.PAGE_JS,))
        tab.close.assert_called_once()

    def test_the_whole_section_and_limit(self):
        got = run(naknak.search, SECTION, "iphone")[0]
        self.assertEqual(got.splitlines()[1], "поиска у сайта нет: это модели его раздела iPhone" + NOTE.rstrip("\n"))
        self.assertEqual(got.splitlines()[-1], "4\tiphone/x\t\tX\t/iphone/x/")
        self.assertEqual(len(got.splitlines()), 7)
        self.assertEqual(len(run(naknak.search, SECTION, "iphone", limit=2)[0].splitlines()), 5)

    def test_no_model_with_the_other_words_shows_the_whole_section(self):
        got = run(naknak.search, SECTION, "iphone 99")[0].splitlines()
        self.assertEqual(got[0], "НакНак · 4 найдено · страница 1 (по 50) · https://naknak.ru/iphone/")
        self.assertEqual(got[1], "⚠️ в разделе iPhone нет моделей со словами «99»: ниже весь раздел")
        self.assertEqual(len(got), 8)

    def test_a_menu_entry_that_is_a_model(self):
        page = {"path": "/homepod/homepod-2023/", "oid": "5", "title": "HomePod", "h1": " HomePod ", "models": [],
                "ld": {"name": "HomePod", "offers": {"lowPrice": 30000}}}
        got, tab, _, _ = run(naknak.search, page, "homepod")
        self.assertEqual(tab.goto.call_args.args[0], "https://naknak.ru/homepod/homepod-2023/")
        self.assertTrue(got.endswith(HEAD + "1\thomepod/homepod-2023\t30000\tHomePod\t/homepod/homepod-2023/"))

    def test_accessories_come_before_the_phone_they_fit(self):
        self.assertEqual(naknak._section("чехол iphone 17"), ("aksessuary", ["iphone", "17"]))
        page = {"path": "/aksessuary/", "oid": None, "title": "Аксессуары", "h1": "", "ld": None,
                "models": [model("/aksessuary/fon-2/chekhol/", "Чехол", "1 000", "Фон 2"), model("/aksessuary/fon-1/chekhol/", "Чехол", "900", "Фон 1")]}
        got = run(naknak.search, page, "чехол фон 2")[0]
        self.assertTrue(got.endswith(HEAD + "1\taksessuary/fon-2/chekhol\t1000\tЧехол (Фон 2)\t/aksessuary/fon-2/chekhol/"), got)

    def test_sections_are_found_by_whole_words(self):
        self.assertEqual(naknak._section("MacBook Air"), ("macbook", ["air"]))
        self.assertEqual(naknak._section("mac mini"), ("mac", ["mini"]))
        self.assertEqual(naknak._section("часы apple watch ultra"), ("apple-watch", ["часы", "ultra"]))
        self.assertEqual(naknak._section("ps5 slim"), ("playstation", ["slim"]))
        self.assertIsNone(naknak._section("наушники"))

    def test_no_site_search(self):
        with patch.object(naknak, "tab_for") as tab_for:
            got = naknak.search("наушники")
        tab_for.assert_not_called()
        self.assertEqual(got, "⚠️ на naknak.ru нет поиска по сайту (его страница поиска отдаёт 404), а в запросе не назван раздел "
                              "его меню. Разделы: Аксессуары, iPhone, Samsung, Google, MacBook, Mac, iPad, AirPods, Apple Watch, "
                              "Dyson, PlayStation, HomePod, Apple TV, Apple Vision Pro")

    def test_what_the_site_has_not(self):
        with patch.object(naknak, "tab_for") as tab_for:
            for kw in ({"price_min": 1}, {"price_max": 1}, {"sort": "price_asc"}, {"page": 2}):
                self.assertEqual(naknak.search("iphone", **kw), naknak.NO_OPTIONS, kw)
        tab_for.assert_not_called()

    def test_not_found_and_blocked(self):
        got, tab, _, log = run(naknak.search, {"path": "/iphone/", "title": "Страница не найдена", "models": [], "ld": None}, "iphone")
        self.assertEqual(got, "⚠️ НакНак: такой страницы нет (404): https://naknak.ru/iphone/")
        tab.close.assert_called_once()
        got, _, _, log = run(naknak.search, {"path": "/iphone/", "title": "?", "models": [], "ld": None}, "iphone")
        self.assertEqual(got, naknak.BLOCKED)
        self.assertEqual(log.warning.call_args.args, ("naknak %s: neither models nor a product", "https://naknak.ru/iphone/"))
        self.assertEqual(run(naknak.search, None, "iphone")[0], naknak.BLOCKED)

    def test_a_refusal_goes_up_and_frees_the_tab(self):
        tab = MagicMock()
        tab.js.return_value = ORIGIN
        tab.goto.side_effect = pace.Refused("⏸")
        with patch.object(naknak, "tab_for", return_value=tab):
            self.assertRaises(pace.Refused, naknak.search, "iphone")
        tab.close.assert_called_once()


OFFERS = {"offerCount": 27, "lowPrice": 94300, "highPrice": 182900,
          "offers": [{"url": "/iphone/fon-2/?oid=11", "availability": "http://schema.org/OutOfStock"},
                     {"url": "/iphone/fon-2/?oid=12", "availability": "http://schema.org/InStock"}]}
SPECS = "Характеристики:\n\n Экран: 6.3\"\n Память: 256 ГБ, 512 ГБ\n" + "Длинно. " * 400
PROPS = [{"title": " Цвет ", "values": [{"name": "Серый", "on": True}, {"name": "Синий", "on": False}]},
         {"title": "Память", "values": [{"name": "256 ГБ", "on": False}, {"name": "512 ГБ", "on": True}]}]
CARD = {"path": "/iphone/fon-2/", "oid": "12", "title": "Фон 2 купить", "h1": " Фон 2 ", "ld": {"name": "Фон 2 ", "offers": OFFERS},
        "models": [], "price": " 98 200 руб. ", "old": " 100 000 руб. ", "props": PROPS + PROPS,      # the page draws the block twice
        "config": [" Серый ", "512 ГБ"], "photos": [f"/upload/{i % 11}.png" for i in range(14)], "specs": SPECS}
CARD_URL = "https://naknak.ru/iphone/fon-2/?oid=12"
CARD_TEXT = ("Фон 2\n" + CARD_URL + "\nid: iphone/fon-2 · вариант (oid): 12\n"
             "цена: 98200 ₽ (было 100000, −2%) — выбранная конфигурация: Серый; 512 ГБ\n"
             "конфигураций 27, от 94300 до 182900 ₽; цену другой сайт показывает только после выбора на странице\n"
             "Цвет: Серый*, Синий\nПамять: 256 ГБ, 512 ГБ*\n"
             "наличие: в наличии\n"
             "получение: на странице товара не указано; условия доставки и самовывоза — https://naknak.ru/help/delivery/\n"
             "фото (shop_images): " + " ".join(f"https://naknak.ru/upload/{i}.png" for i in range(10)) + "\n"
             "отзывы: naknak_reviews (у товаров сайта отзывов нет)\n\n")
SPECS_TEXT = "Характеристики:\nЭкран: 6.3\"\nПамять: 256 ГБ, 512 ГБ\n" + ("Длинно. " * 400).strip()


class NaknakItemTests(unittest.TestCase):
    def test_full_card(self):
        got, tab, _, _ = run(naknak.item, CARD, CARD_URL)
        self.assertEqual(got, CARD_TEXT + SPECS_TEXT[:2500])
        self.assertEqual(tab.goto.call_args.args, (CARD_URL, "naknak"))
        self.assertEqual(tab.js.call_args.args, (naknak.PAGE_JS,))
        tab.close.assert_called_once()

    def test_full_description(self):
        self.assertEqual(run(naknak.item, CARD, CARD_URL, full=True)[0], CARD_TEXT + SPECS_TEXT)

    def test_bare_card_by_its_id(self):
        page = {"path": "/iphone/x/", "oid": None, "title": "X", "h1": "", "ld": {"name": "X"}, "models": [], "price": "",
                "old": "", "props": [], "config": [], "photos": [], "specs": ""}
        got, tab, _, _ = run(naknak.item, page, " iphone/x ")
        self.assertEqual(tab.goto.call_args.args[0], "https://naknak.ru/iphone/x/")
        self.assertEqual(got, "X\nhttps://naknak.ru/iphone/x/\nid: iphone/x\nцена: — ₽\nналичие: —\n"
                              "получение: на странице товара не указано; условия доставки и самовывоза — https://naknak.ru/help/delivery/\n"
                              "отзывы: naknak_reviews (у товаров сайта отзывов нет)\n\n")

    def test_old_price_only_when_higher_and_one_configuration(self):
        page = dict(CARD, old="98 200", ld={"name": "Фон 2", "offers": dict(OFFERS, offerCount=1)})
        got = run(naknak.item, page, CARD_URL)[0].splitlines()
        self.assertEqual(got[3], "цена: 98200 ₽ — выбранная конфигурация: Серый; 512 ГБ")
        self.assertEqual(got[4], "Цвет: Серый*, Синий")

    def test_a_one_offer_product_at_its_bare_address(self):
        ld = {"name": "Адаптер", "url": "/aksessuary/a/b/?oid=41", "additionalProperty": [{"name": "Материал", "value": "Пластик"}],
              "offers": {"offerCount": 1, "offers": [{"url": "/aksessuary/a/b/?oid=41", "availability": "http://schema.org/InStock"}]}}
        page = dict(CARD, path="/aksessuary/a/b/", oid=None, ld=ld, props=[], config=[], specs="", photos=[], old="", h1="Адаптер")
        got = run(naknak.item, page, "aksessuary/a/b")[0]
        self.assertEqual(got.splitlines()[:6], ["Адаптер", "https://naknak.ru/aksessuary/a/b/?oid=41", "id: aksessuary/a/b · вариант (oid): 41",
                                                "цена: 98200 ₽", "наличие: в наличии", naknak.DELIVERY])
        self.assertIn("\nхарактеристики: Материал: Пластик\n", got)

    def test_availability_of_a_product_without_offers(self):
        page = dict(CARD, oid=None, ld={"name": "Кабель", "offers": {"@type": "Offer", "availability": "http://schema.org/InStock"}})
        self.assertIn("\nналичие: в наличии\n", run(naknak.item, page, CARD_URL)[0])

    def test_availability_of_the_chosen_offer(self):
        self.assertIn("\nналичие: нет в наличии\n", run(naknak.item, dict(CARD, oid="11"), CARD_URL)[0])
        self.assertIn("\nналичие: —\n", run(naknak.item, dict(CARD, oid="99"), CARD_URL)[0])
        offers = dict(OFFERS, offers=[{"url": "/iphone/fon-2/?oid=12", "availability": "http://schema.org/LimitedAvailability"}])
        self.assertIn("\nналичие: LimitedAvailability\n", run(naknak.item, dict(CARD, ld={"offers": offers}), CARD_URL)[0])

    def test_a_section_shows_its_models(self):
        got, tab, _, _ = run(naknak.item, SECTION, "/aksessuary/chehly/")
        self.assertEqual(tab.goto.call_args.args[0], "https://naknak.ru/aksessuary/chehly/")
        self.assertEqual(got.splitlines()[:2], ["НакНак · 4 найдено · страница 1 (по 50) · https://naknak.ru/aksessuary/chehly/",
                                                "поиска у сайта нет: это модели его раздела Телефоны" + NOTE.rstrip("\n")])

    def test_wrong_id_takes_no_slot(self):
        with patch.object(naknak, "tab_for") as tab_for:
            for bad in ("iphone", "айфон 17", "https://example.com/iphone/x/", "https://naknak.ru/iphone/x/?utm=1"):
                self.assertEqual(naknak.item(bad), naknak.NO_ID, bad)
        tab_for.assert_not_called()

    def test_not_found_and_blocked(self):
        got = run(naknak.item, {"path": "/iphone/x/", "title": "Страница не найдена", "models": [], "ld": None}, "iphone/x")[0]
        self.assertEqual(got, "⚠️ НакНак: такой страницы нет (404): https://naknak.ru/iphone/x/")
        self.assertEqual(run(naknak.item, None, "iphone/x")[0], naknak.BLOCKED)


class NaknakReviewsTests(unittest.TestCase):
    def test_the_site_has_none(self):
        with patch.object(naknak, "tab_for") as tab_for:
            self.assertEqual(naknak.reviews("iphone/fon-2", "new", True, 2, 5), naknak.NO_REVIEWS)
            self.assertEqual(naknak.reviews("iphone/fon-2"),
                             "НакНак: отзывов о товарах на сайте нет (на странице товара их нет); есть только отзывы о самом "
                             "магазине — https://naknak.ru/reviews")
        tab_for.assert_not_called()


if __name__ == "__main__":
    unittest.main()
