"""Лента search, product card and reviews: what the page's own requests answer -> the grocery dicts and text.
No requests to shops: site_tab and capture are fakes.  Run: .venv/bin/python -B -m unittest -v test_lenta"""
import json
import re
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from grocery import lenta

ITEM = {"id": 84812, "slug": "kefir-25-930g", "name": "кефир", "display": {"name": "Кефир 2,5%", "package": "930 г"},
        "prices": {"price": 10999, "priceRegular": 12499, "cost": 11827}, "features": {"isWeight": False}, "count": 3,
        "rating": {"rate": 4.9, "votes": 2846}}
WEIGHED = {"id": 3001, "slug": "banany", "display": {"name": "Бананы"}, "prices": {"price": 8999, "priceRegular": 8999, "cost": 17998},
           "features": {"isWeight": True}, "units": {"saleUnitQuantity": 0.5}, "count": 0}
ITEM_ROW = {"id": "84812", "name": "Кефир 2,5%", "brand": "", "size": "930 г", "price": 109.99, "old": 124.99, "available": True,
            "url": "https://lenta.com/product/kefir-25-930g-84812/", "rating": 4.9, "reviews": 2846, "ean": None}
WEIGHED_ROW = {"id": "3001", "name": "Бананы", "brand": "", "size": "0.5 кг", "price": 89.99, "old": None, "available": False,
               "url": "https://lenta.com/product/banany-3001/", "rating": None, "reviews": None, "ean": None}
FOUND = {"total": 47, "items": [ITEM, WEIGHED], "filters": {"multicheckbox": [
    {"key": "brand", "name": "Бренд", "values": [{"id": 1, "value": "Простоквашино"}]},
    {"key": "taste", "name": "Вкус", "values": [{"id": 7, "value": "Клубника"}, {"id": 8, "value": "Малина"}]},
    {"key": "fat", "name": "Жирность, %", "values": [{"id": i, "value": v} for i, v in enumerate([2.5, 1, 3.2, 2.9, 0, 4, 6])]},
    {"key": "rating", "name": "Рейтинг", "values": [{"id": 5, "value": 4}]},
    {"key": "empty", "name": "Пусто", "values": []}]}}
FACETS = list(lenta.DIET) + ["Вкус: Клубника / Малина", "Жирность, %: 2.5 / 1 / 3.2 / 2.9 / 0 / 4"]
STRAWBERRY = {"total": 2, "items": [ITEM]}
KEFIR = "/search/%D0%BA%D0%B5%D1%84%D0%B8%D1%80/"

CARD = dict(ITEM, count=167, attributes=[
    {"id": 232, "name": "Состав", "value": "молоко нормализованное, закваска"},
    {"id": 233, "name": "Пищевая ценность", "value": "белки 3 г, жиры 2,5 г, углеводы 4 г"},
    {"id": 234, "name": "Энергетическая ценность", "value": "51 ккал"},
    {"id": 242, "name": "Описание", "value": "<p>Кефир <b>свежий</b></p>"},
    {"id": 84, "name": "Бренд", "value": "ПРОСТОКВАШИНО", "alias": "brand"},
    {"id": 238, "name": "Срок", "value": "10 суток"}, {"id": 236, "name": "Код", "value": "4600"},
    {"id": 10, "name": "Веганское", "value": "Нет"}, {"id": 11, "name": "Содержание лактозы", "value": "Да"},
    {"id": 12, "name": "Производитель", "value": "АО «Молоко»", "alias": "manufacturer"}, {"id": 13, "name": "Пусто", "value": ""}],
    badges={"discount": [{"title": "-12%"}, {"title": ""}], "other": [{"title": "хит"}]},
    images=[{"large": "https://img/l1.png", "original": "https://img/o1.png"}, {"original": "https://img/o2.png"}, {}],
    reviews=[{"rating": 5, "text": "  Вкусный\n кефир "}, {"rating": 4, "text": ""}, {"rating": 3, "text": "х" * 250}])
ZONES = [{"name": "Супер Лента", "selected": False, "time": "~ 2 часа", "min": 500, "prices": [[199, 500]]},
         {"name": "Гипер Лента", "selected": True, "time": "~ 40 минут", "min": 1000, "prices": [[79, 1000], [0, 4300]]}]
CARD_DICT = dict(ITEM_ROW, brand="ПРОСТОКВАШИНО", photos=["https://img/l1.png", "https://img/o2.png"], description="Кефир  свежий",
                 composition="молоко нормализованное, закваска", nutrition={"kcal": 51.0, "protein": 3.0, "fat": 2.5, "carbs": 4.0},
                 composition_extra="Веганское: Нет; Содержание лактозы: Да",
                 extra=["скидка -12%", "в наличии до 167 шт",
                        "доставка: Гипер Лента ~ 40 минут, заказ от 1000 ₽, доставка 79 ₽ от 1000 ₽, 0 ₽ от 4300 ₽",
                        "характеристики: Веганское: Нет; Содержание лактозы: Да; Производитель: АО «Молоко»",
                        "отзывы (первые 2, ещё — grocery_reviews): 5★ Вкусный кефир | 3★ " + "х" * 200])
BARE = {"id": 5, "name": "Вода", "attributes": [{"id": 1, "name": "Состав", "alias": "ingredients", "value": "вода"}]}
BARE_DICT = {"id": "5", "name": "Вода", "brand": "", "size": "", "price": None, "old": None, "available": False,
             "url": "https://lenta.com/product/x-5/", "rating": None, "reviews": None, "ean": None, "photos": [], "description": "",
             "composition": "вода", "nutrition": {}, "composition_extra": "", "extra": ["характеристики: Состав: вода"]}


def fake_tab(here="/", zones=None, card=None):
    """The page: its path, the delivery zones and the server-rendered card in ng-state."""
    tab = MagicMock()
    tab.js.side_effect = lambda expr: here if expr == "location.pathname" else zones if expr == lenta.ZONES_JS else \
        card if "ng-state" in expr else None
    return tab


@contextmanager
def site(tabs, answers):
    """capture() answers the next of answers ({name: JSON}); sent collects (path navigated to, our request body)."""
    sent, answers = [], list(answers)

    def capture(tab, site, url, patterns, timeout=20, rewrite=None, js=None):
        body = rewrite and json.loads(rewrite[1]("https://lenta.com" + lenta.ITEMS[1:])[1])
        sent.append((json.loads(re.search(r"'', (\".*?\")\)", js).group(1)), patterns, body))
        a = answers.pop(0)
        return {k: v for k, v in a.items() if v is not None}

    with patch.object(lenta, "site_tab", side_effect=tabs), patch.object(lenta, "capture", side_effect=capture), \
            patch.object(lenta, "time") as clock, patch.object(lenta, "log") as log:
        yield sent, clock, log


def body(query="кефир", mc=(), sort=("popular", "desc"), limit=30, offset=0, **cat):
    return dict({"query": query, "filters": {"checkbox": [], "multicheckbox": list(mc), "range": []},
                 "sort": {"type": sort[0], "order": sort[1]}, "limit": limit, "offset": offset}, **cat)


class LentaSearchTests(unittest.TestCase):
    def search(self, answers, *args, here="/", **kw):
        tab = fake_tab(here)
        with site([tab], [{"s": a} for a in answers]) as (sent, _, _):
            got = lenta.search(*args, **kw)
        tab.close.assert_called_once()
        return got, [(path, b) for path, _, b in sent]

    def test_query(self):
        got, sent = self.search([FOUND], "кефир", limit=5)
        self.assertEqual(sent, [(KEFIR, body(limit=5))])
        self.assertEqual(got, {"items": [ITEM_ROW, WEIGHED_ROW], "total": 47, "note": "есть следующая страница: page=2",
                               "facets": FACETS, "url": "https://lenta.com" + KEFIR})

    def test_the_same_query_again_changes_the_path_so_the_app_searches(self):
        _, sent = self.search([FOUND], "кефир", here=KEFIR)
        self.assertEqual(sent[0][0], KEFIR[:-1] + "%20/")

    def test_last_page_sort_and_limit_over_40(self):
        got, sent = self.search([FOUND], "кефир", sort="price_desc", page=2, limit=100)
        self.assertEqual(sent, [(KEFIR, body(sort=("price", "desc"), limit=40, offset=40))])
        self.assertEqual(got["note"], "")

    def test_empty_query_searches_goods(self):
        got, sent = self.search([{}], "")
        self.assertEqual(sent, [("/search/%D1%82%D0%BE%D0%B2%D0%B0%D1%80%D1%8B/", body(""))])
        self.assertEqual(got, {"items": [], "total": None, "note": "", "facets": list(lenta.DIET), "url": "https://lenta.com/search//"})

    def test_diet_tag_is_a_category(self):
        got, sent = self.search([FOUND], "кефир", tag="Веган", limit=5)
        self.assertEqual(sent, [(KEFIR, body(limit=5, categoryId=13616))])
        self.assertEqual(got["note"], "раздел Ленты «вегетарианское» + запрос «кефир»\nесть следующая страница: page=2")

    def test_tag_of_the_search_facets(self):
        got, sent = self.search([FOUND, STRAWBERRY], "кефир", tag="клубн", page=2, limit=10)
        self.assertEqual(sent, [(KEFIR, body(limit=10, offset=10)),
                                (KEFIR, body(mc=[{"key": "taste", "valueIds": [7]}], limit=10, offset=10))])
        self.assertEqual(got, {"items": [ITEM_ROW], "total": 2, "note": "фильтр Ленты «Вкус: Клубника»", "facets": list(lenta.DIET),
                               "url": "https://lenta.com" + KEFIR})

    def test_facet_search_without_answer_keeps_the_first(self):
        got, _ = self.search([FOUND, None], "кефир", tag="Малина", limit=50)
        self.assertEqual((got["items"], got["note"]), ([ITEM_ROW, WEIGHED_ROW], "фильтр Ленты «Вкус: Малина»\nесть следующая страница: page=2"))

    def test_unknown_tag_goes_into_the_text(self):
        got, sent = self.search([FOUND, STRAWBERRY], "кефир", tag="козий")
        self.assertEqual(sent[1], ("/search/%D0%BA%D0%B5%D1%84%D0%B8%D1%80%20%D0%BA%D0%BE%D0%B7%D0%B8%D0%B9/", body("кефир козий")))
        self.assertEqual((got["items"], got["note"]), ([ITEM_ROW], "тега «козий» у Ленты для этого запроса нет — искал «кефир козий» текстом"))

    def test_text_search_without_answer_keeps_the_first(self):
        got, _ = self.search([FOUND, None], "кефир", tag="козий")
        self.assertEqual(got["items"], [ITEM_ROW, WEIGHED_ROW])

    def test_no_answer(self):
        self.assertEqual(self.search([None], "кефир", tag="козий")[0], lenta.BLOCKED)


class CardSite(unittest.TestCase):
    def product(self, card, zones=ZONES, here="/", rendered=None, zones_rendered=None, fn=lenta.product, id_or_url="84812", **kw):
        tabs = [fake_tab(here, zones), fake_tab(zones=zones_rendered, card=rendered)]
        with site(tabs, [{"p": card}]) as (sent, clock, log):
            got = fn(id_or_url, **kw)
        self.sent, self.tabs, self.clock, self.log = sent, tabs, clock, log
        return got


class LentaProductTests(CardSite):
    def test_full_card(self):
        self.assertEqual(self.product(CARD), CARD_DICT)
        self.assertEqual(self.sent, [("/product/x-84812/", {"p": ["re:/api-gateway/v1/catalog/items/84812(\\?|$)"]}, None)])
        self.tabs[0].close.assert_called_once()
        self.tabs[1].close.assert_not_called()
        self.clock.sleep.assert_not_called()

    def test_weighed_card_from_a_link_with_every_zone_when_none_is_selected(self):
        zones = [dict(z, selected=False) for z in ZONES]
        got = self.product(dict(WEIGHED, rating={"rate": 4.5}), zones, id_or_url="https://lenta.com/product/banany-3001/?from=x")
        self.assertEqual(self.sent[0][0], "/product/x-3001/")
        self.assertEqual(got, dict(WEIGHED_ROW, rating=4.5, photos=[], description="", composition="", nutrition={}, composition_extra="", extra=[
            "весовой товар: 179.98 ₽/кг, шаг 0.5 кг",
            "доставка: Супер Лента ~ 2 часа, заказ от 500 ₽, доставка 199 ₽ от 500 ₽; "
            "Гипер Лента ~ 40 минут, заказ от 1000 ₽, доставка 79 ₽ от 1000 ₽, 0 ₽ от 4300 ₽"]))

    def test_the_same_card_again_leaves_it_first(self):
        self.product(CARD, here="/product/kefir-25-930g-84812/")
        self.assertEqual(self.tabs[0].js.call_args_list[1].args, (lenta.NAV_JS % '"/"',))
        self.clock.sleep.assert_called_once_with(1.5)

    def test_card_the_app_did_not_fetch_again_comes_from_a_full_load(self):
        self.assertEqual(self.product(None, zones=None, rendered=BARE, zones_rendered=None), BARE_DICT)
        self.tabs[1].goto.assert_called_once_with("https://lenta.com/product/x-84812/", "lenta", wait_js="!!document.getElementById('ng-state')")
        self.tabs[0].close.assert_called_once()
        self.tabs[1].close.assert_called_once()
        self.log.warning.assert_called_once()

    def test_full_load_keeps_the_zones_already_read(self):
        got = self.product(None, rendered=BARE, zones_rendered=[dict(ZONES[0], selected=True)])
        self.assertEqual(got["extra"][0], "доставка: Гипер Лента ~ 40 минут, заказ от 1000 ₽, доставка 79 ₽ от 1000 ₽, 0 ₽ от 4300 ₽")
        got = self.product(None, zones=[], rendered=BARE, zones_rendered=[dict(ZONES[0], selected=True)])
        self.assertEqual(got["extra"][0], "доставка: Супер Лента ~ 2 часа, заказ от 500 ₽, доставка 199 ₽ от 500 ₽")

    def test_no_card(self):
        self.assertEqual(self.product(None), "Лента: карточка 84812 не пришла (неверный id или проверка на бота)")
        self.assertEqual(self.product({"name": "?"}), "Лента: карточка 84812 не пришла (неверный id или проверка на бота)")

    def test_not_an_id(self):
        with self.assertRaises(ValueError):
            lenta.product("кефир")


class LentaReviewsTests(CardSite):
    def reviews(self, card, **kw):
        return self.product(card, fn=lenta.reviews, **kw)

    def test_reviews_come_with_the_card(self):
        self.assertEqual(self.reviews(CARD, sort="new", page=2), "Лента · Кефир 2,5%: рейтинг 4.9 (2846 оценок)\n"
                         "Лента отдаёт с карточкой 5 последних отзывов; фото в отзывах у Ленты нет\n"
                         "отзывы (первые 2, ещё — grocery_reviews): 5★ Вкусный кефир | 3★ " + "х" * 200)

    def test_no_reviews(self):
        self.assertEqual(self.reviews(BARE), "Лента · Вода: рейтинг — (0 оценок)\n"
                         "Лента отдаёт с карточкой 5 последних отзывов; фото в отзывах у Ленты нет\n(отзывов нет)")

    def test_reviews_without_text(self):
        got = self.reviews(dict(BARE, reviews=[{"rating": 4, "text": ""}, {"rating": 5}]))
        self.assertEqual(got.splitlines()[-1], "(отзывов нет)")

    def test_no_card(self):
        self.assertEqual(self.reviews(None), "Лента: карточка 84812 не пришла (неверный id или проверка на бота)")


class LentaCartLookupTests(unittest.TestCase):
    def test_goods_by_id_without_leading_zeros(self):
        cl = {"PositionsCount": 2, "Goods": [{"GoodsItemId": "052602", "Quantity": 2}, {"GoodsItemId": "000", "Quantity": 1}]}
        self.assertEqual(lenta._goods({"Body": {"CartList": [cl]}}),
                         ({"52602": {"GoodsItemId": "052602", "Quantity": 2}, "0": {"GoodsItemId": "000", "Quantity": 1}}, cl))

    def test_no_cart(self):
        self.assertEqual(lenta._goods(None), ({}, {}))
        self.assertEqual(lenta._goods({"Body": {"CartList": []}}), ({}, {}))


if __name__ == "__main__":
    unittest.main()
