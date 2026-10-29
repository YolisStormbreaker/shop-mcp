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


if __name__ == "__main__":
    unittest.main()
