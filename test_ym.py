"""Яндекс Маркет search, product card, reviews and cart: what the page scripts hand over -> the tool's text,
and for the cart every step it takes in the tab.  No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_ym"""
import json
import re
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

    def test_a_title_with_the_word_is_not_promoted(self):
        book = snippet({"marketSku": "104", "title": "Книга: продвижение в соцсетях", "price": 700, "sponsored": False}, href="/card/kniga/4")
        got = call(ym.search, SNIPPETS + [book], "usb cable")[0]
        self.assertEqual(got.splitlines()[0].split(" · ")[2], "карточек: 4, продвигаемых: 2; дальше — page=2")

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
        self.assertTrue(call(ym.item, FULL_ITEM, CARD, full=True)[0].endswith("\n\n" + DESCRIPTION.rstrip()))  # no space left by «Всё описание»

    def test_delivery_without_a_price_keeps_its_first_line(self):
        got = call(ym.item, {**BARE_ITEM, "delivery": ["Самовывоз\nиз магазина"]}, CARD)[0]
        self.assertIn("\nдоставка: Самовывоз\n", got)

    def test_bare_card_by_relative_link(self):
        got, tab, _, _ = call(ym.item, BARE_ITEM, "/card/kabel-b/102")
        self.assertEqual(got, "Кабель B — нет цены\nhttps://market.yandex.ru/card/kabel-b/102\nмагазин: 4.8 оценок\nотзывы: ym_reviews")
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


class Market:
    """The Market tab as the cart code drives it: every step lands in .log, in order.
    carts and minus: the answers of the cart's rows script and of the «−» finder, one per run; the last one stays.
    captcha: the navigations (1, 2, …) that show a captcha."""
    def __init__(self, carts, captcha=(), visible=True, clicked=True, minus=(True,)):
        self.log, self.carts, self.minus, self.captcha = [], list(carts), list(minus), set(captcha)
        self.shown, self.clicked, self.pages = visible, clicked, 0

    def goto(self, url, site, wait_js=None):
        self.pages += 1
        self.log.append(("goto", url, site, wait_js))

    def js(self, expr):
        sku = re.search(r'r\.sku === ("[^"]*")', expr)
        if sku and js_lines(expr) == js_lines(minus_js(json.loads(sku.group(1)))):
            self.log.append(("minus", json.loads(sku.group(1))))
            return _next(self.minus)
        name, answer = {"performance.timeOrigin": ("origin", lambda: ORIGIN),
                        ym.CAPTCHA_JS: ("captcha?", lambda: self.pages in self.captcha),
                        "document.documentElement.outerHTML": ("html", lambda: "<html>"),
                        ym.ROWS_JS: ("rows", lambda: _next(self.carts)),
                        RECT_JS: ("rect", lambda: [640.5, 360.0])}.get(expr, (None, None))
        if not name:
            raise AssertionError(f"unexpected page script: {expr[:100]}")
        self.log.append(("js", name))
        return answer()

    def click(self, selector):
        self.log.append(("click", selector))
        return self.clicked

    def visible(self):
        self.log.append(("visible",))
        return self.shown

    def call(self, method, **params):
        self.log.append(("call", method, params))

    def close(self):
        self.log.append(("close",))


def _next(answers):
    return answers.pop(0) if len(answers) > 1 else answers[0]


def js_lines(s):
    """A script's lines with their spaces collapsed: indentation is free, a line break is not (a // comment ends there)."""
    return [" ".join(x.split()) for x in s.splitlines()]


def minus_js(sku):
    """Finds the «−» before the row's own quantity field and marks it for the mouse."""
    return f"""(() => {{ const r = (window.__ymRows || []).find(r => r.sku === {json.dumps(sku)}); if (!r) return null;
const q = r.el.querySelector('input[type=number]'); if (!q) return null;
const b = [...r.el.querySelectorAll('button')].filter(b => b.compareDocumentPosition(q) & Node.DOCUMENT_POSITION_FOLLOWING).pop();  // «−» sits right before the field
if (!b) return null; b.scrollIntoView({{block: 'center'}}); window.__ymMinus = b; return true; }})()"""


RECT_JS = "(() => { const r = window.__ymMinus.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()"


def drive(fn, market, *args):
    """fn(*args) in the fake tab; the reply, the steps, and the dump mock."""
    def tab_for(domain):
        market.log.append(("tab_for", domain))
        return market
    with patch.object(ym, "tab_for", side_effect=tab_for), patch.object(ym, "dump", return_value="saved") as dump, \
            patch.object(ym, "log"), patch.object(ym.time, "sleep", side_effect=lambda s: market.log.append(("sleep", s))):
        got = fn(*args)
    return got, market.log, dump


def page(url, ready, captcha=False):
    """One navigation: the old page's timeOrigin, goto until ready (or a captcha), the captcha check."""
    return [("js", "origin"), ("goto", url, "ym", f"performance.timeOrigin !== {ORIGIN} && ({ready} || {ym.CAPTCHA_JS})"),
            ("js", "captcha?")] + ([("js", "html")] if captcha else [])


CART_READY = "!!document.querySelector('input[type=checkbox]') || /пуст/i.test(document.body.innerText)"
ITEM_READY = "!!document.querySelector('h1')"
OPEN = page(ym.CART_URL, CART_READY) + [("js", "rows")]
TAB, CLOSE = [("tab_for", "market.yandex.ru")], [("close",)]
FRONT = [("call", "Page.bringToFront", {})]   # cart changes are clicks: this tab comes to the front of the shown window
ITEM_PAGE = "https://market.yandex.ru/card/zaryadka-b/1002"
BUY = [("click", '[data-auto="main"] [data-auto="cartButton"]')]
MOUSE = [("call", "Input.dispatchMouseEvent", {"type": t, "x": 640.5, "y": 360.0, "button": "left", "clickCount": 1})
         for t in ("mouseMoved", "mousePressed", "mouseReleased")]


def minus_click(sku):
    return [("minus", sku), ("sleep", 0.6), ("js", "rect")] + MOUSE + [("sleep", 1.5), ("js", "rows")]


ROW_A = {"sku": "1001", "qty": "1", "checked": True, "text": "Кабель A 480 ₽ 500 ₽", "price": "480₽"}
ROW_B = {"sku": "1002", "qty": "2", "checked": False, "text": "Зарядка B 1 200 ₽", "price": "1200₽"}
ROW_C = {"sku": "1003", "qty": "1", "checked": None, "text": "Чехол C", "price": ""}
CART_HEAD = "корзина Яндекс Маркета (✓ — выбрано к оформлению; цена с картой Яндекс Пэй, как её показывает строка)\nsku\tшт\tцена\t✓\tтовар"
LINE_A, LINE_B, LINE_C = "1001\t1\t480₽\t✓\tКабель A 480 ₽ 500 ₽", "1002\t2\t1200₽\t\tЗарядка B 1 200 ₽", "1003\t1\t\t\tЧехол C"


def cart_text(*lines):
    return CART_HEAD + "\n" + "\n".join(lines)


class YmCartTests(unittest.TestCase):
    def test_lines_of_the_cart(self):
        got, steps, _ = drive(ym.cart, Market([[ROW_A, ROW_B, ROW_C]]))
        self.assertEqual(got, cart_text(LINE_A, LINE_B, LINE_C))
        self.assertEqual(steps, TAB + OPEN + CLOSE)

    def test_empty_cart(self):
        self.assertEqual(drive(ym.cart, Market([[]]))[0], "корзина Яндекс Маркета пуста")

    def test_captcha(self):
        got, steps, dump = drive(ym.cart, Market([[ROW_A]], captcha={1}))
        self.assertEqual(got, ym.BLOCKED)
        self.assertEqual(steps, TAB + page(ym.CART_URL, CART_READY, captcha=True) + CLOSE)
        dump.assert_called_once_with("ym", "captcha", "<html>")


class YmAddToCartTests(unittest.TestCase):
    def test_adds_the_offer_by_a_relative_link(self):
        got, steps, _ = drive(ym.add_to_cart, Market([[ROW_A], [ROW_A, {**ROW_B, "qty": "1"}]]), "/card/zaryadka-b/1002")
        self.assertEqual(got, "добавлено: sku 1002\n" + cart_text(LINE_A, "1002\t1\t1200₽\t\tЗарядка B 1 200 ₽"))
        self.assertEqual(steps, TAB + FRONT + OPEN + page(ITEM_PAGE, ITEM_READY) + BUY + [("sleep", 2)] + OPEN + CLOSE)

    def test_one_more_piece_counts_as_added(self):
        got = drive(ym.add_to_cart, Market([[ROW_A, ROW_B], [{**ROW_A, "qty": "2"}, ROW_B]]), ITEM_PAGE)[0]
        self.assertEqual(got, "добавлено: sku 1001\n" + cart_text("1001\t2\t480₽\t✓\tКабель A 480 ₽ 500 ₽", LINE_B))

    def test_unchanged_cart(self):
        got = drive(ym.add_to_cart, Market([[ROW_A]]), ITEM_PAGE)[0]
        self.assertEqual(got, "⚠️ Маркет не подтвердил добавление (или товар уже был в корзине)\n" + cart_text(LINE_A))

    def test_hidden_tab(self):
        got, steps, _ = drive(ym.add_to_cart, Market([[ROW_A]], visible=False, clicked=False), ITEM_PAGE)
        self.assertEqual(got, "не добавлено: " + ym.NOT_ON_SCREEN)
        self.assertEqual(steps, TAB + FRONT + OPEN + page(ITEM_PAGE, ITEM_READY) + BUY + [("visible",)] + CLOSE)

    def test_no_button(self):
        got = drive(ym.add_to_cart, Market([[ROW_A]], clicked=False), ITEM_PAGE)[0]
        self.assertEqual(got, "не добавлено: не нашёл кнопку «В корзину» у основного предложения")

    def test_a_foreign_link_is_not_opened(self):
        got, steps, _ = drive(ym.add_to_cart, Market([[ROW_A]]), "https://www.ozon.ru/product/1")
        self.assertEqual(got, "нужна ссылка на товар Яндекс Маркета (https://market.yandex.ru/card/...)")
        self.assertEqual(steps, [])

    def test_captcha_on_each_page(self):
        steps_to = {1: page(ym.CART_URL, CART_READY, captcha=True),
                    2: OPEN + page(ITEM_PAGE, ITEM_READY, captcha=True),
                    3: OPEN + page(ITEM_PAGE, ITEM_READY) + BUY + [("sleep", 2)] + page(ym.CART_URL, CART_READY, captcha=True)}
        for n, steps in steps_to.items():
            with self.subTest(page=n):
                got, log, _ = drive(ym.add_to_cart, Market([[ROW_A]], captcha={n}), ITEM_PAGE)
                self.assertEqual(got, ym.BLOCKED)
                self.assertEqual(log, TAB + FRONT + steps + CLOSE)

class YmRemoveFromCartTests(unittest.TestCase):
    def test_takes_off_every_piece(self):
        market = Market([[ROW_A, ROW_B], [ROW_A, {**ROW_B, "qty": "1"}], [ROW_A]])
        got, steps, _ = drive(ym.remove_from_cart, market, 1002)
        self.assertEqual(got, "удалено: sku 1002\n" + cart_text(LINE_A))
        self.assertEqual(steps, TAB + FRONT + OPEN + [("visible",)] + minus_click("1002") * 2 + OPEN + CLOSE)

    def test_a_line_without_a_quantity_takes_one_click(self):
        got, steps, _ = drive(ym.remove_from_cart, Market([[ROW_A, {**ROW_B, "qty": ""}], [ROW_A]]), "1002")
        self.assertEqual(got, "удалено: sku 1002\n" + cart_text(LINE_A))
        self.assertEqual(steps, TAB + FRONT + OPEN + [("visible",)] + minus_click("1002") + OPEN + CLOSE)

    def test_no_minus_button(self):
        got, steps, _ = drive(ym.remove_from_cart, Market([[ROW_A, ROW_B]], minus=(None,)), " 1002 ")
        self.assertEqual(got, "⚠️ Маркет не подтвердил удаление: sku 1002\n" + cart_text(LINE_A, LINE_B))
        self.assertEqual(steps, TAB + FRONT + OPEN + [("visible",), ("minus", "1002")] + OPEN + CLOSE)

    def test_unknown_sku_is_not_clicked(self):
        got, steps, _ = drive(ym.remove_from_cart, Market([[ROW_A]]), "999")
        self.assertEqual(got, "такого sku в корзине нет\n" + cart_text(LINE_A))
        self.assertEqual(steps, TAB + FRONT + OPEN + CLOSE)

    def test_hidden_tab(self):
        got, steps, _ = drive(ym.remove_from_cart, Market([[ROW_A, ROW_B]], visible=False), "1002")
        self.assertEqual(got, "не удалено: " + ym.NOT_ON_SCREEN)
        self.assertEqual(steps, TAB + FRONT + OPEN + [("visible",)] + CLOSE)

    def test_captcha(self):
        steps_to = {1: page(ym.CART_URL, CART_READY, captcha=True),
                    2: OPEN + [("visible",)] + minus_click("1001") + page(ym.CART_URL, CART_READY, captcha=True)}
        for n, steps in steps_to.items():
            with self.subTest(page=n):
                got, log, _ = drive(ym.remove_from_cart, Market([[ROW_A]], captcha={n}), "1001")
                self.assertEqual(got, ym.BLOCKED)
                self.assertEqual(log, TAB + FRONT + steps + CLOSE)


class OtherSitesTests(unittest.TestCase):
    """The Market tab, logged in, never goes to another site: the host decides, not a substring of the link."""
    LINKS = ("https://market.yandex.ru.evil.test/card/x/1", "https://evil.test/?u=https://market.yandex.ru/card/x/1",
             "https://evil.test/market.yandex.ru/card/x/1")

    def test_links_to_other_hosts_are_refused_without_a_tab(self):
        for fn in (ym.item, ym.add_to_cart, ym.reviews):
            for url in self.LINKS:
                with self.subTest(fn=fn.__name__, url=url), patch.object(ym, "tab_for") as tab_for:
                    self.assertEqual(fn(url), ym.NOT_A_CARD)
                    tab_for.assert_not_called()

if __name__ == "__main__":
    unittest.main()
