"""Ozon read paths: the site's composer JSON (widgetStates) -> the text the tools return.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_ozon"""
import json
import time
import unittest
from unittest.mock import MagicMock, patch

import ozon


def answer(body, status=200):
    return {"s": status, "b": body if isinstance(body, str) else json.dumps(body)}


class FetchTests(unittest.TestCase):
    def fetch(self, *answers, last_call=0.0):
        tab = MagicMock()
        tab.js.side_effect = list(answers)
        ozon._last_call = last_call
        with patch.object(ozon.time, "sleep") as sleep, patch.object(ozon, "dump", return_value="logs/bodies/x.html"), \
                patch.object(ozon, "log") as log:
            try:
                return ozon._page(tab, "/search/?text=usb c"), tab, sleep, log
            except RuntimeError as e:
                return e, tab, sleep, log

    def test_json_answer_through_the_page_api(self):
        got, tab, sleep, _ = self.fetch(answer({"widgetStates": {}}))
        self.assertEqual(got, {"widgetStates": {}})
        self.assertEqual(tab.js.call_args.args[0],
                         'fetch("/api/entrypoint-api.bx/page/json/v2?url=%2Fsearch%2F%3Ftext%3Dusb%20c", '
                         '{"method": "GET", "credentials": "include"}).then(async r => ({s: r.status, b: await r.text()}))')
        sleep.assert_not_called()

    def test_waits_out_the_gap_since_the_last_call(self):
        _, _, sleep, _ = self.fetch(answer({}), last_call=time.time())
        self.assertGreater(sleep.call_args.args[0], 1.0)
        self.assertLessEqual(sleep.call_args.args[0], 1.5)

    def test_post_sends_json_body(self):
        tab = MagicMock()
        tab.js.return_value = answer({"ok": 1})
        ozon._last_call = 0.0
        with patch.object(ozon.time, "sleep"):
            self.assertEqual(ozon._fetch(tab, "/api/x", "POST", {"pageType": "pdp"}), {"ok": 1})
        self.assertIn('{"method": "POST", "credentials": "include", "headers": {"Content-Type": "application/json"}, '
                      '"body": "{\\"pageType\\": \\"pdp\\"}"}', tab.js.call_args.args[0])

    def test_non_json_reloads_the_tab_and_retries(self):
        got, tab, sleep, log = self.fetch(answer("<html>antibot</html>", 403), answer({"widgetStates": {"a": "{}"}}))
        self.assertEqual(got, {"widgetStates": {"a": "{}"}})
        tab.goto.assert_called_once_with("https://www.ozon.ru/", "ozon", wait_js="document.readyState === 'complete'")
        self.assertEqual(sleep.call_args_list[0].args, (3,))        # then the retry waits out its own gap
        self.assertEqual(log.warning.call_args.args[3:], (403, "logs/bodies/x.html"))

    def test_non_json_twice_raises_with_the_saved_body(self):
        got, tab, _, log = self.fetch(answer("<html>1</html>", 403), answer("<html>2</html>", 403))
        self.assertIsInstance(got, RuntimeError)
        self.assertEqual(str(got), "Ozon ответил 403 не-JSON и после перезагрузки вкладки "
                                   "(вероятно, проверка на бота: shop-chrome show). Ответ целиком: logs/bodies/x.html")
        self.assertEqual(tab.goto.call_count, 1)
        log.error.assert_called_once()


def page(widgets=None, next_page=None):
    """A composer page: every widget state is a JSON string under its id."""
    p = {"widgetStates": {k: json.dumps(v) for k, v in (widgets or {}).items()}}
    if next_page:
        p["nextPage"] = next_page
    return p


def tile(sku, title, price, old=None, labels=(), delivery=None):
    main = [{"type": "textDS", "textDS": {"text": "Оригинал"}},           # a badge before the name
            {"type": "textDS", "id": "name", "textDS": {"text": title}},
            {"type": "textDS", "textDS": {"text": "Осталось 3 шт"}},
            {"type": "priceV2", "priceV2": {"price": [{"text": f"{price} ₽", "textStyle": "PRICE"}]
                                            + ([{"text": f"{old} ₽", "textStyle": "ORIGINAL_PRICE"}] if old else [])
                                            + [{"text": "−56%", "textStyle": "DISCOUNT"}]}},
            {"type": "labelListV2", "labelListV2": {"items": [{"type": "text", "text": {"text": x}} for x in labels]
                                                    + [{"type": "icon", "image": "star"}]}}]
    it = {"sku": sku, "mainState": main, "action": {"link": f"/product/kabel-{sku}/?advert=xyz"}}
    if delivery:
        # what _texts skips (action, common, trackingInfo) holds dates too; a nested text node and a list do not stop it
        it["multiButton"] = {"common": {"text": "Сегодня"}, "trackingInfo": {"title": "Завтра"},
                             "ozonButton": {"items": [{"title": "В корзину", "action": {"text": "Сегодня"}},
                                                      {"text": {"text": delivery}}, {"text": "Завтра"}]}}
    return it


PAGE1 = page({"tileGrid2-1": {"items": [
    tile(1002731400, "hoco Кабель USB Type-A/USB Type-C, 1 м", "149", "340", ["4.9", "336 096 отзывов"], "Послезавтра"),
    tile(None, "Кабель без sku", "10"),
    tile(1393105636, "Кабель " + "очень длинный " * 10, "991", labels=["Хит продаж"])]},
    "infiniteVirtualPaginator-2": {"nextPage": "/search/?text=usb&page=2"}})
PAGE2 = page({"tileGrid2-1": {"items": [tile(1002731400, "дубль", "1"), tile(3070669820, "Кабель type c", "190", "650",
                                                                              ["4.8", "70 485 отзывов"], "29 октября")]},
              "paginator-3": {"nextPage": ""}}, next_page="/search/?text=usb&page=3")
PAGE3 = page({"tileGrid2-1": {"items": []}})
HEAD = "товар: https://www.ozon.ru/product/<sku>\n#\tsku\tцена ₽\tбез скидки\tназвание\tрейтинг\tотзывов\tпривезут"


class SearchTests(unittest.TestCase):
    def search(self, pages, query="кабель usb-c", **kw):
        tab = MagicMock()
        with patch.object(ozon, "_tab", return_value=tab), patch.object(ozon, "_page", side_effect=pages) as get:
            out = ozon.search(query, **kw)
        tab.close.assert_called_once()
        return out, [c.args[1] for c in get.call_args_list]

    def test_rows_across_pages(self):
        out, urls = self.search([PAGE1, PAGE2, PAGE3])
        self.assertEqual(urls, ["/search/?text=%D0%BA%D0%B0%D0%B1%D0%B5%D0%BB%D1%8C+usb-c&sorting=score",
                                "/search/?text=usb&page=2", "/search/?text=usb&page=3"])
        self.assertEqual(out, "Ozon · https://www.ozon.ru/search/?text=%D0%BA%D0%B0%D0%B1%D0%B5%D0%BB%D1%8C+usb-c&sorting=score\n"
                         + HEAD + "\n"
                         "1\t1002731400\t149\t340\thoco Кабель USB Type-A/USB Type-C, 1 м\t4.9\t336096\tПослезавтра\n"
                         "2\t1393105636\t991\t\t" + ("Кабель " + "очень длинный " * 10)[:110] + "\t\t\t\n"
                         "3\t3070669820\t190\t650\tКабель type c\t4.8\t70485\t29 октября")

    def test_price_range_and_sort_go_into_the_url(self):
        out, urls = self.search([PAGE3], "usb", price_max=500, sort="price")
        self.assertEqual(urls, ["/search/?text=usb&sorting=price&currency_price=0.000%3B500.000"])
        self.assertTrue(out.startswith("Ozon · https://www.ozon.ru/search/?text=usb&sorting=price&currency_price=0.000%3B500.000\n"))
        self.assertTrue(out.endswith(HEAD + "\n(пусто)"))
        self.assertEqual(self.search([PAGE3], "usb", price_min=100)[1],
                         ["/search/?text=usb&sorting=score&currency_price=100.000%3B100000000.000"])

    def test_limit_stops_reading_pages(self):
        out, urls = self.search([PAGE1, PAGE2], limit=1)
        self.assertEqual(len(urls), 1)
        self.assertEqual(out.splitlines()[-1], "1\t1002731400\t149\t340\thoco Кабель USB Type-A/USB Type-C, 1 м\t4.9\t336096\tПослезавтра")

    def test_reads_at_most_eight_pages(self):
        pages = [page({"tileGrid2-1": {"items": [tile(n, f"товар {n}", "1")]}}, next_page=f"/p{n + 1}") for n in range(1, 11)]
        out, urls = self.search(pages, limit=100)
        self.assertEqual(len(urls), 8)
        self.assertEqual(out.splitlines()[-1], "8\t8\t1\t\tтовар 8\t\t\t")

    def test_unknown_sort(self):
        with self.assertRaisesRegex(ValueError, "sort: одно из"):
            ozon.search("usb", sort="cheap")


if __name__ == "__main__":
    unittest.main()
