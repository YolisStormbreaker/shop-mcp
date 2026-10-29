"""Яндекс Маркет search, product card and reviews: what the page scripts hand over -> the tool's text.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_ym"""
import unittest
from unittest.mock import MagicMock, patch

import ym

ORIGIN = 1761.5       # performance.timeOrigin of the page before navigation


def call(fn, page, /, *args, captcha=False, **kw):
    """fn(*args, **kw) with a fake Market tab whose js() answers the page scripts with page."""
    tab = MagicMock()

    def js(expr):
        if expr == "performance.timeOrigin":
            return ORIGIN
        if expr == ym.CAPTCHA_JS:
            return captcha
        if expr in (ym.SEARCH_JS, ym.ITEM_JS, ym.REVIEWS_JS):
            return page
        return True       # clicks, and «has the first review changed?» in the reviews redraw
    tab.js.side_effect = js
    with patch.object(ym, "tab_for", return_value=tab) as tab_for, patch.object(ym, "dump", return_value="saved") as dump, \
            patch.object(ym, "log"), patch.object(ym.time, "sleep"):
        got = fn(*args, **kw)
    return got, tab, tab_for, dump


def snippet(zone, title="", delivery="", reviews="", href=""):
    return {"zone": zone, "title": title, "delivery": delivery, "reviews": reviews, "href": href}


def prices(card, nocard):
    return [{"priceType": "yaBank", "priceValue": card}, {"priceType": "withDiscount", "priceValue": nocard}]


SNIPPETS = [  # data-zone-data as the site has it: sponsored is a boolean, isCrossBorder a string
    snippet({"marketSku": "101", "title": "Кабель A", "price": 500, "additionalPrices": prices(480, 490), "sponsored": True,
             "isCrossBorder": "false", "signals": [{"type": "brand", "title": "Vitumi"}, {"type": "shop", "title": "Магазин 1"}]},
            "Кабель A на карточке", "Завтра , ПВЗ", "4.8 (10) · 100 купили", "/card/kabel-a/1?do-waremd5=x"),
    snippet({"marketSku": "101", "title": "Кабель A ещё раз"}, href="/card/kabel-a/1"),
    snippet({"price": 300, "sponsored": False, "isCrossBorder": "true"}, "Кабель B", href="/card/kabel-b/2"),  # no sku, title on the card only
    snippet({}, "Кабель B ещё раз", href="/card/kabel-b/2"),  # nothing in its zone
    snippet({"marketSku": "103", "title": "Кабель C", "price": 990, "additionalPrices": prices(900, 950), "sponsored": True,
             "isCrossBorder": "true", "signals": [{"type": "shop", "title": "Магазин 3"}]}, href="/card/kabel-c/3"),
]
SEARCH_HEAD = ("ссылки относительно https://market.yandex.ru; цены и доставка — для региона из профиля\n"
               "#\tsku\tс картой Я Банка ₽\tбез карты ₽\tдо скидок ₽\tназвание\tмагазин\tрейтинг · купили\tдоставка\tпометки\tссылка")
SEARCH_ROWS = ["1\t101\t480\t490\t500\tКабель A\tМагазин 1\t4.8 (10) · 100 купили\tЗавтра , ПВЗ\tпродвижение\t/card/kabel-a/1",
               "2\t\t\t300\t\tКабель B\t\t\t\tиз-за рубежа\t/card/kabel-b/2",
               "3\t103\t900\t950\t990\tКабель C\tМагазин 3\t\t\tпродвижение, из-за рубежа\t/card/kabel-c/3"]


class YmSearchTests(unittest.TestCase):
    def test_page_of_cards_without_duplicates(self):
        got, tab, tab_for, _ = call(ym.search, SNIPPETS, "usb cable")
        self.assertEqual(got, "Яндекс Маркет · страница 1 · карточек: 3, продвигаемых: 2; дальше — page=2 · "
                              "https://market.yandex.ru/search?text=usb+cable\n" + SEARCH_HEAD + "\n" + "\n".join(SEARCH_ROWS))
        tab_for.assert_called_once_with("market.yandex.ru")
        tab.goto.assert_called_once_with(
            "https://market.yandex.ru/search?text=usb+cable", "ym",
            wait_js=f"performance.timeOrigin !== {ORIGIN} && (!!document.querySelector('[data-zone-name=\"productSnippet\"]') || {ym.CAPTCHA_JS})")
        tab.close.assert_called_once()

    def test_prices_sort_and_page_go_into_the_url(self):
        got = call(ym.search, SNIPPETS, "usb cable", price_min=100.7, price_max=2000, sort="price", page=2)[0]
        self.assertEqual(got.splitlines()[0], "Яндекс Маркет · страница 2 · карточек: 3, продвигаемых: 2; дальше — page=3 · "
                                              "https://market.yandex.ru/search?text=usb+cable&pricefrom=100&priceto=2000&how=aprice&page=2")

    def test_limit_cuts_the_rows_not_the_counts(self):
        got = call(ym.search, SNIPPETS, "usb cable", limit=1)[0]
        self.assertEqual(got.splitlines()[0].split(" · ")[2], "карточек: 3, продвигаемых: 2; дальше — page=2")
        self.assertEqual(got.splitlines()[3:], SEARCH_ROWS[:1])

    def test_empty_page(self):
        got = call(ym.search, [], "usb cable")[0]
        self.assertEqual(got, "Яндекс Маркет · страница 1 · карточек: 0, продвигаемых: 0; дальше — page=2 · "
                              "https://market.yandex.ru/search?text=usb+cable\n" + SEARCH_HEAD + "\n(пусто)")

    def test_unknown_sort(self):
        got, _, tab_for, _ = call(ym.search, SNIPPETS, "usb cable", sort="cheap")
        self.assertEqual(got, "sort: одно из default, price, price_desc, rating, with_reviews, new")
        tab_for.assert_not_called()

    def test_captcha(self):
        got, tab, _, dump = call(ym.search, SNIPPETS, "usb cable", captcha=True)
        self.assertEqual(got, ym.BLOCKED)
        dump.assert_called_once_with("ym", "captcha", True)
        tab.close.assert_called_once()


CARD = "https://market.yandex.ru/card/kabel-a/101"
PHOTOS = [f"https://avatars.mds.yandex.net/get-mpic/{n}/pic{n}/orig" for n in range(12)]
DESCRIPTION = "Описание кабеля. " * 200      # 3400 characters
FULL_ITEM = {"title": "Кабель A", "vendor": "Бренд", "rating": "4.9 (13K) ·", "price": "939 ₽", "old": "1 561 ₽", "pay": True,
             "shop": "Магазин 1", "trust": "4.8 · 3 года на Маркете",
             "delivery": ["Завтра,\nпо клику\n0 ₽\nул. Примерная, 1", "Послезавтра,  курьер\n\n 99 ₽ "],  # then the pickup address
             "specs": "Длина\n1.2 м\n\nРазъём\nUSB Type-C\nВсе характеристики\nбез пары",
             "zone": {"marketSku": "5713677624", "isCrossBorder": "true"},
             "description": DESCRIPTION + "Всё описание",
             "photos": [f"https://avatars.mds.yandex.net/get-mpic/{n}/pic{n}/{size}" for n in range(12) for size in ("50x50", "200x200")]
             + ["https://yastatic.net/market/icon.svg"]}
BARE_ITEM = {"title": "Кабель B", "vendor": "", "rating": "", "price": "", "old": "", "pay": False, "shop": "", "trust": "4.8 оценок",
             "delivery": [], "specs": "", "zone": {}, "description": "", "photos": []}


class YmItemTests(unittest.TestCase):
    def test_full_card(self):
        got, tab, _, _ = call(ym.item, FULL_ITEM, CARD + "?sku=5713677624")
        self.assertEqual(got, "\n".join([
            "Кабель A — 939 ₽ с Яндекс Пэй (до скидок 1 561 ₽)", CARD, "⚠️ из-за рубежа",
            "sku: 5713677624", "бренд: Бренд", "рейтинг: 4.9 (13K)", "магазин: Магазин 1 · 4.8 · 3 года на Маркете",
            "доставка: Завтра, по клику 0 ₽; Послезавтра, курьер 99 ₽", "фото (shop_images): " + " ".join(PHOTOS[:10]),
            "отзывы: ym_reviews", "характеристики: Длина: 1.2 м; Разъём: USB Type-C", "", DESCRIPTION[:2500]]))
        tab.goto.assert_called_once_with(CARD + "?sku=5713677624", "ym",
                                         wait_js=f"performance.timeOrigin !== {ORIGIN} && (!!document.querySelector('h1') || {ym.CAPTCHA_JS})")
        tab.close.assert_called_once()

    def test_full_description(self):
        self.assertTrue(call(ym.item, FULL_ITEM, CARD, full=True)[0].endswith("\n\n" + DESCRIPTION))

    def test_delivery_without_a_price_keeps_its_first_line(self):
        got = call(ym.item, {**BARE_ITEM, "delivery": ["Самовывоз\nиз магазина"]}, CARD)[0]
        self.assertIn("\nдоставка: Самовывоз\n", got)

    def test_bare_card_by_relative_link(self):
        got, tab, _, _ = call(ym.item, BARE_ITEM, "/card/kabel-b/102")
        self.assertEqual(got, "Кабель B — нет цены\nhttps://market.yandex.ru/card/kabel-b/102\nмагазин: 4.8 оценок\nотзывы: ym_reviews\n\n")
        self.assertEqual(tab.goto.call_args.args[0], "https://market.yandex.ru/card/kabel-b/102")

    def test_not_a_market_link(self):
        got, _, tab_for, _ = call(ym.item, FULL_ITEM, "https://www.ozon.ru/product/1")
        self.assertEqual(got, "нужна ссылка на товар Яндекс Маркета (https://market.yandex.ru/card/...)")
        tab_for.assert_not_called()

    def test_captcha(self):
        got, tab, _, _ = call(ym.item, FULL_ITEM, CARD, captcha=True)
        self.assertEqual(got, ym.BLOCKED)
        tab.close.assert_called_once()


UGC = "https://avatars.mds.yandex.net/get-market-ugc/1234/abc"
REVIEWS = {"summary": "4.9 13K оценок • 2K отзывов", "dist": "5 ★ 90% 4 ★ 6%", "reviews": [
    {"zone": {"grade": 5, "date": "17 октября 2024", "votesAgree": 7, "votesDisagree": 1}, "date": "17 октября", "author": "Покупатель А",
     "text": "Достоинства:  прочный\n\nНедостатки: нет\n", "variant": "Цвет товара: серый\nДлина кабеля: 1.2 м",
     "photos": [UGC + "/100x100?size=s", UGC + "/orig", "https://avatars.mds.yandex.net/get-mpic/1/pic/50x50", "https://yastatic.net/avatar.png"]},
    {"zone": {"grade": 3, "votesAgree": 0}, "date": "5 мая", "author": "Покупатель Б", "text": "Комментарий: средне", "variant": "",
     "photos": []}]}
REVIEW_ROWS = [f"17 октября 2024\t5\t+7/−1\tЦвет товара: серый, Длина кабеля: 1.2 м\tПокупатель А\tДостоинства: прочный | Недостатки: нет\t{UGC}/orig",
               "5 мая\t3\t+0/−0\t\tПокупатель Б\tКомментарий: средне\t"]
REVIEWS_URL = CARD + "/reviews"
REVIEWS_NOTE = (". Видны первые 10 отзывов на сортировку: следующие сайт подгружает прокруткой видимой страницы, а браузер скрыт. "
                "Год у дат текущего года сайт не пишет.\nдата\t★\tполезно +/−\tвариант\tавтор\tтекст\tфото (shop_images)")
ITEMS = "document.querySelectorAll('[data-auto=\"review-item\"]')"


def clicks(tab):
    return [c.args[0] for c in tab.js.call_args_list if "click()" in c.args[0]]


class YmReviewsTests(unittest.TestCase):
    def test_useful_reviews_of_all_variants(self):
        got, tab, _, _ = call(ym.reviews, REVIEWS, CARD + "/?utm=1")
        self.assertEqual(got, f"Яндекс Маркет · {REVIEWS_URL}\n4.9 13K оценок • 2K отзывов · 5 ★ 90% 4 ★ 6%\n"
                              f"все варианты, сортировка useful{REVIEWS_NOTE}\n" + "\n".join(REVIEW_ROWS))
        tab.goto.assert_called_once_with(
            REVIEWS_URL, "ym", wait_js=f"performance.timeOrigin !== {ORIGIN} && ({ITEMS}.length > 0 || "
                                       f"/нет отзывов|Отзывов пока нет/i.test(document.body.innerText) || {ym.CAPTCHA_JS})")
        self.assertEqual(clicks(tab), [])
        tab.close.assert_called_once()

    def test_this_variant_sorted_low_with_photos(self):
        got, tab, _, _ = call(ym.reviews, REVIEWS, "/card/kabel-a/101/reviews", sort="low", with_media=True, this_variant=True)
        self.assertEqual(got, f"Яндекс Маркет · {REVIEWS_URL}\n4.9 13K оценок • 2K отзывов · 5 ★ 90% 4 ★ 6%\n"
                              f"только этот вариант, сортировка low, только с фото{REVIEWS_NOTE}\n" + REVIEW_ROWS[0])
        self.assertEqual(clicks(tab), [
            "document.querySelector('[data-zone-name=thisOptionTab]')?.querySelector('button,a,input,label')?.click()"
            " || document.querySelector('[data-zone-name=thisOptionTab]')?.click()",
            "document.querySelector('[data-auto=\"product-reviews-sort\"]')?.click()",
            "document.querySelector('[data-auto=\"more-actions-grade-0\"]')?.click()"])

    def test_redraw_waits_for_the_first_review_to_change(self):
        _, tab, _, _ = call(ym.reviews, REVIEWS, CARD, sort="new")
        exprs = [c.args[0] for c in tab.js.call_args_list]
        k = exprs.index("document.querySelector('[data-auto=\"more-actions-date-1\"]')?.click()")
        self.assertEqual(exprs[k - 1], f"{ITEMS}[0]?.innerText || ''")
        self.assertEqual(exprs[k + 1], f"({ITEMS}[0]?.innerText || '') !== true")

    def test_review_without_zone_data_has_no_grade(self):
        bare = {"zone": {}, "date": "5 мая", "author": "Покупатель Б", "text": "Комментарий: средне", "variant": "", "photos": []}
        got = call(ym.reviews, {**REVIEWS, "reviews": [bare]}, CARD)[0]
        self.assertEqual(got.splitlines()[-1], "5 мая\t\t+0/−0\t\tПокупатель Б\tКомментарий: средне\t")

    def test_no_reviews(self):
        got = call(ym.reviews, {"summary": "", "dist": "", "reviews": []}, CARD, with_media=True)[0]
        self.assertEqual(got, f"Яндекс Маркет · {REVIEWS_URL}\n\nвсе варианты, сортировка useful, только с фото{REVIEWS_NOTE}\n(отзывов нет)")

    def test_unknown_sort(self):
        got, _, tab_for, _ = call(ym.reviews, REVIEWS, CARD, sort="best")
        self.assertEqual(got, "sort: одно из useful, new, high, low")
        tab_for.assert_not_called()

    def test_not_a_card_link(self):
        got, _, tab_for, _ = call(ym.reviews, REVIEWS, "https://market.yandex.ru/search?text=usb")
        self.assertEqual(got, "нужна ссылка на товар Яндекс Маркета (https://market.yandex.ru/card/...)")
        tab_for.assert_not_called()

    def test_captcha(self):
        got, tab, _, _ = call(ym.reviews, REVIEWS, CARD, captcha=True)
        self.assertEqual(got, ym.BLOCKED)
        self.assertEqual(clicks(tab), [])
        tab.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
