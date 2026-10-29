"""Avito watch for Orange Pi Zero3: which titles count, which listings get reported, what is remembered as seen.
No requests to shops and no Telegram messages.  Run: .venv/bin/python -B -m unittest -v test_watch"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import avito
import watch

WAIT = "document.querySelector('[data-marker=\"item\"], [data-marker=\"page-title/count\"]')"


def url(n):
    return "https://www.avito.ru" + path(n)


def path(n):
    return f"/moskva/bytovaya_elektronika/plata_{1000000000 + n}"


def listed(n, title, price="3000", link=True):
    """An item as LIST_JS returns it."""
    return {"id": str(1000000000 + n), "title": title, "price": price, "date": "вчера", "city": "moskva",
            "delivery": "Доставка", "rating": "", "url": url(n) if link else ""}


def page(items, blocked=False):
    return {"blocked": blocked, "total": str(len(items)), "url": "https://www.avito.ru/all?q=orange+pi", "items": items}


def ship(full, wallet=None, reserved=False, broken=False):
    """A delivery offer as SHIP_JS returns it."""
    return {"text": f"Доставка в Москву от {wallet or full} ₽", "reserved": reserved, "broken": broken, "full": full, "wallet": wallet}


NO_LINE = {"reserved": False, "broken": False}


def line(n, total, price, cheapest, title, ram):
    return f'<b>{total} ₽</b> ({price} + доставка {cheapest}) · <a href="{url(n)}">{title}</a> · moskva · {ram}'


class TitleTests(unittest.TestCase):
    def test_boards(self):
        for title in ("Orange Pi Zero 3 2GB", "Orange Pi Zero3", "Orange Pi 3 Zero 1.5GB", "Оранж Пи Zero-3", "OPi Zero 3 4гб",
                      "Orange Pi Zero 3 в корпусе", "Orange Pi Zero 3 & корпус",
                      # a board sold with its accessories is a board: «+ БП», «с блоком питания», «в комплекте с БП»
                      "Orange Pi Zero 3 + БП", "Orange Pi Zero 3 4GB с блоком питания и корпусом", "Orange Pi Zero 3 в комплекте с БП",
                      "Orange Pi Zero 3 2GB + кабель + радиатор"):
            self.assertTrue(watch.wanted(title), title)

    def test_not_boards(self):
        for title in ("Zero 3 1GB", "Orange Pi Zero 2W", "Orange Pi Zero 3W", "Orange Pi 3 LTS", "Orange Pi 3B", "Orange Pi Zero 32",
                      "Orange Pi Zero 3 512MB", "Orange Pi Zero 3 H2+", "Raspberry Pi Zero 3 orange", "Корпус для Orange Pi Zero 3",
                      "Кейс Orange Pi Zero3", "Orange Pi Zero 3 для проекта", "Блок питания Orange Pi Zero 3",
                      # an accessory sold with others is still an accessory
                      "Блок питания для Orange Pi Zero 3 + кабель", "Корпус + вентилятор для Orange Pi Zero3",
                      "Кабель USB-C и блок питания Orange Pi Zero 3"):
            self.assertFalse(watch.wanted(title), title)

    def test_ram(self):
        for title, ram in (("Orange Pi Zero 3 2GB", "2 ГБ"), ("Orange Pi Zero3 1,5 гб", "1.5 ГБ"), ("Orange Pi Zero 3 1.5GB", "1.5 ГБ"),
                           ("Orange Pi Zero 3 4 G", "4 ГБ"), ("Orange Pi Zero 3 512 MB", "память не указана"),
                           ("Orange Pi Zero 3", "память не указана")):
            self.assertEqual(watch.ram(title), ram, title)


class ScanTests(unittest.TestCase):
    def test_boards_with_a_link(self):
        tab = MagicMock()
        tab.js.return_value = page([listed(1, "Orange Pi Zero 3 1GB"), listed(2, "Корпус для Orange Pi Zero 3"),
                                    listed(3, "Orange Pi Zero 3 2GB", link=False), listed(4, "Orange Pi Zero3 4GB")])
        got = watch.scan(tab, "orange pi zero 3")
        tab.goto.assert_called_once_with("https://www.avito.ru/all?q=orange+pi+zero+3&pmin=2000&pmax=5000&s=104&d=1", "avito", wait_js=WAIT)
        tab.js.assert_called_once_with(avito.LIST_JS)
        self.assertEqual([x["id"] for x in got], ["1000000001", "1000000004"])

    def test_block_or_captcha(self):
        tab = MagicMock()
        tab.js.return_value = page([], blocked=True)
        with self.assertRaisesRegex(RuntimeError, r"^Авито показал блокировку или капчу: https://www.avito.ru/all\?q=orange\+pi$"):
            watch.scan(tab, "orange pi zero 3")


class MainTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.seen = Path(tmp.name) / "logs" / "watch_seen.json"

    def remember(self, *ns):
        self.seen.parent.mkdir()
        self.seen.write_text(json.dumps([str(1000000000 + n) for n in ns]))

    def remembered(self):
        return [int(i) - 1000000000 for i in json.loads(self.seen.read_text())]

    def main(self, answers):
        """watch.main with the tab answering LIST_JS for each query and then SHIP_JS from answers."""
        tab = MagicMock()
        tab.js.side_effect = answers
        with patch.object(watch, "tab_for", return_value=tab) as tab_for, patch.object(watch, "log") as log, \
                patch.object(watch, "SEEN", self.seen):
            got = watch.main()
        tab_for.assert_called_once_with("avito.ru")
        tab.close.assert_called_once_with()
        return got, tab, log

    def test_new_listings_working_first_then_cheapest(self):
        self.remember(4)
        first = [listed(11, "Orange Pi Zero 3 4GB", "4600"), listed(1, "Orange Pi Zero 3 2GB"), listed(2, "Orange Pi Zero3 1,5 гб", "2500"),
                 listed(3, "Корпус для Orange Pi Zero 3", "500"), listed(4, "Orange Pi Zero 3"),
                 listed(10, "Orange Pi Zero 3", link=False)]
        second = [listed(1, "Orange Pi Zero 3 2GB"), listed(5, "Orange Pi Zero 3 4GB", "4800"), listed(6, "Orange Pi Zero 3"),
                  listed(7, "Orange Pi Zero 3", ""), listed(8, "Orange Pi Zero 3"), listed(9, "Orange Pi Zero 3 1GB & корпус", "2700")]
        offers = [ship(400), ship(400), ship(300, broken=True), ship(400), ship(400, reserved=True), ship(400), NO_LINE, ship(900, 800)]
        got, tab, log = self.main([page(first), page(second), offers])
        self.assertEqual(tab.goto.call_args_list, [call(avito.search_url(q, "all", 2000, 5000, "date", 1, True), "avito", wait_js=WAIT)
                                                   for q in watch.QUERIES])
        paths = [path(n) for n in (11, 1, 2, 5, 6, 7, 8, 9)]
        self.assertEqual(tab.js.call_args_list[2], call(f"{avito.SHIP_JS}({json.dumps(paths)})", timeout=47))
        self.assertEqual(got, [
            line(1, 3400, 3000, 400, "Orange Pi Zero 3 2GB", "2 ГБ"),
            line(9, 3500, 2700, 800, "Orange Pi Zero 3 1GB &amp; корпус", "1 ГБ"),
            line(11, 5000, 4600, 400, "Orange Pi Zero 3 4GB", "4 ГБ"),
            line(2, 2800, 2500, 300, "Orange Pi Zero3 1,5 гб", "1.5 ГБ") + "\n⚠️ по описанию не работает или продаётся как есть"])
        self.assertEqual(self.remembered(), [1, 2, 4, 5, 7, 8, 9, 11])  # the reserved one may come back
        log.info.assert_called_once_with("watch: %d matching, %d not seen before, %d new under %d ₽", 9, 8, 4, 5000)

    def test_security_check_stops_the_run(self):
        got, _, _ = self.main([page([listed(1, "Orange Pi Zero 3"), listed(2, "Orange Pi Zero 3"), listed(3, "Orange Pi Zero 3")]),
                               page([]), [ship(400), {"blocked": True}]])
        self.assertEqual(got, [line(1, 3400, 3000, 400, "Orange Pi Zero 3", "память не указана")])
        self.assertEqual(self.remembered(), [1])

    def test_a_failed_delivery_lookup_is_asked_again_next_run(self):
        # not marked seen: a listing whose lookup failed once would otherwise never be reported
        listings = [listed(1, "Orange Pi Zero 3"), listed(2, "Orange Pi Zero 3"), listed(3, "Orange Pi Zero 3")]
        got, _, _ = self.main([page(listings), page([]), [{"error": "timeout"}, None, NO_LINE]])
        self.assertEqual((got, self.remembered()), ([], [3]))   # 3 answered: it has no delivery line

    def test_nothing_new(self):
        self.remember(1)
        got, tab, _ = self.main([page([listed(1, "Orange Pi Zero 3")]), page([listed(1, "Orange Pi Zero 3")])])
        self.assertEqual((got, tab.js.call_count, self.remembered()), ([], 2, [1]))

    def test_block_leaves_seen_untouched(self):
        tab = MagicMock()
        tab.js.return_value = page([], blocked=True)
        with patch.object(watch, "tab_for", return_value=tab), patch.object(watch, "SEEN", self.seen), \
                self.assertRaises(RuntimeError):
            watch.main()
        tab.close.assert_called_once_with()
        self.assertFalse(self.seen.exists())


class NotifyTests(unittest.TestCase):
    def test_sends_to_telegram(self):
        with patch.object(sys, "argv", ["watch.py"]), patch.object(watch.tg, "send") as send:
            watch.notify("<b>3400 ₽</b>")
        send.assert_called_once_with("<b>3400 ₽</b>")

    def test_print_instead(self):
        out = io.StringIO()
        with patch.object(sys, "argv", ["watch.py", "--print"]), patch.object(watch.tg, "send") as send, redirect_stdout(out):
            watch.notify("<b>3400 ₽</b>")
        send.assert_not_called()
        self.assertEqual(out.getvalue(), "<b>3400 ₽</b>\n")


if __name__ == "__main__":
    unittest.main()
