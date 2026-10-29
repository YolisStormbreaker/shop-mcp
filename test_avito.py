"""Avito search table and item card from what LIST_JS, ITEM_JS and SHIP_JS read off the page.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_avito"""
import json
import unittest
from unittest.mock import MagicMock, call, patch

import avito

PAGE = "https://www.avito.ru/sankt-peterburg?q=orange+pi"
HEAD = ("ссылки относительно https://www.avito.ru; доставка ₽ — в город из профиля Авито; итого = цена + самая дешёвая доставка\n"
        "#\tцена\tдоставка ₽\tитого\tназвание\tгород\tдоставка\tрейтинг продавца\tкогда\tссылка")
BLOCK = (f"Авито показал блокировку или капчу: {PAGE}. Попроси пользователя: shop-chrome show, пройти проверку "
         "во вкладке Авито, затем shop-chrome hide.")


def path(n):
    return f"/sankt-peterburg/bytovaya_elektronika/plata_{1000000000 + n}"


def listed(n, title="Orange Pi Zero 3", price="4500", delivery="Доставка за 1–2 дня"):
    """An item as LIST_JS returns it."""
    return {"id": str(1000000000 + n), "title": title, "price": price, "date": "2 часа назад", "city": "sankt-peterburg",
            "delivery": delivery, "rating": "4,9", "url": "https://www.avito.ru" + path(n)}


def tail(n, delivery="Доставка за 1–2 дня"):
    """The search row's columns after the title."""
    return f"sankt-peterburg\t{delivery}\t4,9\t2 часа назад\t{path(n)}"


def ship(full, wallet=None, reserved=False, broken=False):
    """A delivery offer as SHIP_JS returns it for a page with a delivery line."""
    return {"text": f"Доставка в Санкт-Петербург от {wallet or full} ₽", "reserved": reserved, "broken": broken,
            "full": full, "wallet": wallet}


NO_LINE = {"reserved": False, "broken": False}  # a page without a delivery line
BLOCKED = {"blocked": True}


def page(items, total="1 234", blocked=False):
    return {"blocked": blocked, "total": total, "url": PAGE, "items": items}


class ShipCellTests(unittest.TestCase):
    def test_security_check(self):
        self.assertEqual(avito._ship_cell(BLOCKED), ("проверка Авито", None))

    def test_no_offer(self):
        for s in (None, {}, {"error": "TypeError: Failed to fetch"}, NO_LINE, {**ship(300), "full": None}):
            self.assertEqual(avito._ship_cell(s), ("", None), s)

    def test_wallet_discount(self):
        self.assertEqual(avito._ship_cell(ship(450, 300)), ("300 кошельком / 450", 300))

    def test_cheapest_even_if_wallet_costs_more(self):
        self.assertEqual(avito._ship_cell(ship(300, 450)), ("450 кошельком / 300", 300))

    def test_full_price_only(self):
        self.assertEqual(avito._ship_cell(ship(390)), ("390", 390))


class SearchUrlTests(unittest.TestCase):
    def test_every_filter(self):
        self.assertEqual(avito.search_url("orange pi", "moskva", 2000.5, 5000, "date", 2, True),
                         "https://www.avito.ru/moskva?q=orange+pi&pmin=2000&pmax=5000&s=104&p=2&d=1")

    def test_no_filters(self):
        for sort in ("default", "rating"):
            self.assertEqual(avito.search_url("orange pi", "all", None, 0, sort, 1, False), "https://www.avito.ru/all?q=orange+pi")

    def test_sort_orders(self):
        for sort, s in (("price", "1"), ("price_desc", "2")):
            self.assertTrue(avito.search_url("x", "all", None, None, sort, 1, False).endswith(f"&s={s}"))


class ShippingTests(unittest.TestCase):
    def test_no_paths_no_request(self):
        tab = MagicMock()
        self.assertEqual(avito._shipping(tab, []), [])
        tab.js.assert_not_called()

    def test_paths_go_to_the_page_script(self):
        tab = MagicMock()
        tab.js.return_value = [ship(300), NO_LINE]
        self.assertEqual(avito._shipping(tab, [path(1), path(2)]), [ship(300), NO_LINE])
        tab.js.assert_called_once_with(f"{avito.SHIP_JS}({json.dumps([path(1), path(2)])})", timeout=23)


def search(answers, **kw):
    """avito.search with the tab answering LIST_JS and then SHIP_JS (or the page markup) from answers."""
    tab = MagicMock()
    tab.js.side_effect = answers
    with patch.object(avito, "tab_for", return_value=tab) as tab_for, \
            patch.object(avito, "dump", return_value="saved.html") as dump, patch.object(avito, "log") as log:
        out = avito.search("orange pi", **kw)
    tab_for.assert_called_once_with("avito.ru")
    tab.close.assert_called_once_with()
    return out, tab, dump, log


class SearchTests(unittest.TestCase):
    def test_table_with_delivery_prices(self):
        items = [listed(1, "Orange Pi Zero 3 2GB"), listed(2, price=""), listed(3, delivery=""), listed(4, "Резерв"),
                 listed(5), listed(6)]
        offers = [ship(450, 300), ship(390), ship(350, reserved=True), NO_LINE, {"error": "TypeError: Failed to fetch"}]
        out, tab, _, _ = search([page(items), offers])
        self.assertEqual(tab.goto.call_args, call(
            PAGE, "avito", wait_js="document.querySelector('[data-marker=\"item\"], [data-marker=\"page-title/count\"]')"))
        paths = [path(n) for n in (1, 2, 4, 5, 6)]
        self.assertEqual(tab.js.call_args_list[1], call(f"{avito.SHIP_JS}({json.dumps(paths)})", timeout=35))
        self.assertEqual(out, "\n".join([
            f"1 234 найдено · {PAGE}", HEAD,
            f"1\t4500\t300 кошельком / 450\t4800\tOrange Pi Zero 3 2GB\t{tail(1)}",
            f"2\t\t390\t\tOrange Pi Zero 3\t{tail(2)}",
            f"3\t4500\t\t\tOrange Pi Zero 3\t{tail(3, '')}",
            f"4\t4500\t\t\tOrange Pi Zero 3\t{tail(5)}",
            f"5\t4500\t\t\tOrange Pi Zero 3\t{tail(6)}",
            "скрыто зарезервированных: 1 (1000000004)"]))

    def test_security_check_midway(self):
        out, _, _, log = search([page([listed(1), listed(2), listed(3)]), [ship(390), BLOCKED]])
        log.warning.assert_called_once_with("avito shipping: 439 after %d of %d items, search %s", 1, 3, PAGE)
        self.assertEqual(out, "\n".join([
            f"1 234 найдено · {PAGE}", HEAD,
            f"1\t4500\t390\t4890\tOrange Pi Zero 3\t{tail(1)}",
            f"2\t4500\tпроверка Авито\t\tOrange Pi Zero 3\t{tail(2)}",
            f"3\t4500\t\t\tOrange Pi Zero 3\t{tail(3)}",
            "⚠️ Авито включил проверку безопасности — цену доставки узнали не для всех; подождать 10–30 минут."]))

    def test_delivery_price_for_the_first_items_only(self):
        out, tab, _, _ = search([page([listed(1), listed(2)]), [ship(390)]], shipping=1)
        self.assertEqual(tab.js.call_args_list[1].kwargs, {"timeout": 19})
        self.assertEqual(out.splitlines()[3:], [
            f"1\t4500\t390\t4890\tOrange Pi Zero 3\t{tail(1)}",
            f"2\t4500\t\t\tOrange Pi Zero 3\t{tail(2)}",
            "цена доставки — только у первых 1 объявлений с доставкой (shipping=1)"])

    def test_no_delivery_prices(self):
        out, tab, _, _ = search([page([listed(1)])], shipping=0)
        self.assertEqual(tab.js.call_count, 1)
        self.assertEqual(out, "\n".join([f"1 234 найдено · {PAGE}", HEAD, f"1\t4500\t\t\tOrange Pi Zero 3\t{tail(1)}"]))

    def test_limit_and_a_page_without_a_count(self):
        out, _, _, _ = search([page([listed(1), listed(2), listed(3)], total=""), [ship(390)]], limit=1)
        self.assertEqual(out, "\n".join([f"3 найдено · {PAGE}", HEAD, f"1\t4500\t390\t4890\tOrange Pi Zero 3\t{tail(1)}"]))

    def test_everything_reserved(self):
        out, _, _, _ = search([page([listed(7)]), [ship(390, reserved=True)]])
        self.assertEqual(out, "\n".join([f"1 234 найдено · {PAGE}", HEAD, "(пусто)", "скрыто зарезервированных: 1 (1000000007)"]))

    def test_block_or_captcha(self):
        out, tab, dump, log = search([page([listed(1)], blocked=True), "<html>captcha</html>"])
        self.assertEqual(out, BLOCK)
        self.assertEqual(tab.js.call_args_list[1], call("document.documentElement.outerHTML"))
        dump.assert_called_once_with("avito", "block", "<html>captcha</html>")
        log.warning.assert_called_once_with("avito search %s: block or captcha, page %s", PAGE, "saved.html")


class RevealAddressTests(unittest.TestCase):
    BEFORE = "Orange Pi Zero 3\nАдрес\nУзнать подробности"

    def reveal(self, pages, clicked=True):
        tab = MagicMock()
        tab.js.side_effect = [self.BEFORE] + pages
        tab.click.return_value = clicked
        with patch.object(avito.time, "sleep") as sleep:
            got = avito._reveal_address(tab)
        if clicked:
            tab.click.assert_called_once_with('[data-marker="item-map-button"]')
        self.assertEqual(tab.js.call_args_list, [call("document.body.innerText")] * (len(pages) + 1))
        return got, sleep.call_count

    def test_map_button_missing(self):
        self.assertEqual(self.reveal([], clicked=False), (("", ""), 0))

    def test_address_after_the_metro(self):
        metro = self.BEFORE + "\nПлощадь Восстаниядо 5 мин.\nМаяковскаядо 10 мин"
        got = self.reveal([metro, metro + "\n  Санкт-Петербург  \nЦентральный район\n© Яндекс Карты\nул. Примерная, 1"])
        self.assertEqual(got, (("ул. Примерная, 1", "Площадь Восстания (до 5 мин), Маяковская (до 10 мин)"), 2))

    def test_gives_up_after_eight_tries(self):
        got = self.reveal([self.BEFORE + "\nПлощадь Восстаниядо 5 мин."] * 8)
        self.assertEqual(got, (("", "Площадь Восстания (до 5 мин)"), 8))


CARD = {"title": "Orange Pi Zero 3 2GB", "price": "4500", "address": "Санкт-Петербург, ул. Примерная, 1",
        "date": "· 28 октября в 10:00", "seller": "Продавец", "seller_rating": "4,9",
        "params": ["Состояние: Б/у", "Тип: одноплатный компьютер"], "description": "Плата рабочая.",
        "photos": [f"https://00.img.avito.st/image/1/{n}.jpg" for n in range(11)]}


def item(card, offers, html=None, visible=True, reveal=("", ""), **kw):
    """avito.item with the tab answering ITEM_JS, the page markup when html is given, then SHIP_JS."""
    tab = MagicMock()
    tab.js.side_effect = [card] + ([html] if html is not None else []) + [offers]
    tab.visible.return_value = visible
    with patch.object(avito, "tab_for", return_value=tab) as tab_for, \
            patch.object(avito, "dump", return_value="saved.html") as dump, patch.object(avito, "log") as log, \
            patch.object(avito, "_reveal_address", return_value=reveal) as rev:
        out = avito.item("https://www.avito.ru" + path(1), **kw)
    tab_for.assert_called_once_with("avito.ru")
    tab.goto.assert_called_once_with("https://www.avito.ru" + path(1), "avito", wait_js="document.querySelector('h1')")
    tab.close.assert_called_once_with()
    return out, tab, dump, log, rev


class ItemTests(unittest.TestCase):
    def test_full_card(self):
        out, tab, dump, _, rev = item(CARD, [ship(450, 300)])
        self.assertEqual(tab.js.call_args_list[1], call(f"{avito.SHIP_JS}([location.pathname])"))
        dump.assert_not_called()
        rev.assert_not_called()
        self.assertEqual(out, "\n".join([
            "Orange Pi Zero 3 2GB — 4500 ₽",
            "адрес: Санкт-Петербург, ул. Примерная, 1",
            "дата: 28 октября в 10:00",
            "продавец: Продавец 4,9",
            "доставка: Доставка в Санкт-Петербург от 300 ₽ → итого от 4800 ₽",
            "параметры: Состояние: Б/у; Тип: одноплатный компьютер",
            "фото (shop_images): " + " ".join(CARD["photos"][:10]),
            "",
            "Плата рабочая."]))

    def test_reserved_and_spaced_price(self):
        out, *_ = item({**CARD, "price": "4 500 ₽"}, [ship(390, reserved=True)])
        self.assertEqual(out.splitlines()[:2], ["Orange Pi Zero 3 2GB — 4 500 ₽", "⛔ ЗАРЕЗЕРВИРОВАН другим покупателем — сейчас купить нельзя"])
        self.assertIn("доставка: Доставка в Санкт-Петербург от 390 ₽ → итого от 4890 ₽", out.splitlines())

    def test_bare_card(self):
        card = {**CARD, "price": "Договорная", "date": "", "seller": "", "seller_rating": "", "params": [], "photos": []}
        out, *_ = item(card, [ship(390)])
        self.assertEqual(out, "\n".join(["Orange Pi Zero 3 2GB — Договорная ₽", "адрес: Санкт-Петербург, ул. Примерная, 1",
                                         "доставка: Доставка в Санкт-Петербург от 390 ₽", "", "Плата рабочая."]))

    def test_delivery_line_without_a_price(self):
        out, *_ = item(CARD, [{"text": "Доставка в Санкт-Петербург", "reserved": False, "broken": False, "full": None, "wallet": None}])
        self.assertIn("доставка: Доставка в Санкт-Петербург", out.splitlines())

    def test_no_delivery_line(self):
        for offers in ([], [BLOCKED], [NO_LINE], [{"error": "TypeError: Failed to fetch"}]):
            out, *_ = item({**CARD, "seller": "", "photos": []}, offers)
            self.assertEqual(out.splitlines()[1:5], ["адрес: Санкт-Петербург, ул. Примерная, 1", "дата: 28 октября в 10:00",
                                                     "продавец: 4,9", "параметры: Состояние: Б/у; Тип: одноплатный компьютер"], offers)

    def test_address_behind_the_map_button(self):
        out, tab, _, _, rev = item({**CARD, "address": ""}, [], reveal=("ул. Примерная, 1", "Площадь Восстания (до 5 мин)"))
        rev.assert_called_once_with(tab)
        self.assertEqual(out.splitlines()[1:3], ["адрес: ул. Примерная, 1", "метро: Площадь Восстания (до 5 мин)"])

    def test_address_needs_a_tab_on_screen(self):
        out, _, _, _, rev = item({**CARD, "address": ""}, [], visible=False)
        rev.assert_not_called()
        self.assertEqual(out.splitlines()[1], "адрес: не раскрыт: вкладка Авито не на экране (нужно shop-chrome show и открыть вкладку avito.ru)")

    def test_page_without_a_title_is_saved(self):
        out, tab, dump, log, _ = item({**CARD, "title": ""}, [], html="<html>empty</html>")
        self.assertEqual(tab.js.call_args_list[1], call("document.documentElement.outerHTML"))
        dump.assert_called_once_with("avito", "item", "<html>empty</html>")
        log.warning.assert_called_once_with("avito item %s: no title, page %s", "https://www.avito.ru" + path(1), "saved.html")
        self.assertEqual(out.splitlines()[0], " — 4500 ₽")

    def test_long_description(self):
        card = {**CARD, "description": "а" * 2600}
        self.assertTrue(item(card, [])[0].endswith("\n\n" + "а" * 2500))
        self.assertTrue(item(card, [], full=True)[0].endswith("\n\n" + "а" * 2600))


if __name__ == "__main__":
    unittest.main()
