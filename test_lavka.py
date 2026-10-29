"""Яндекс Лавка product card: the site's product JSON and delivery info -> the grocery product dict.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_lavka"""
import unittest
from unittest.mock import MagicMock, patch

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


if __name__ == "__main__":
    unittest.main()
