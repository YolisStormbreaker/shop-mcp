"""AliExpress read paths: the site's API JSON and the product page's text -> the text the tools return.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_ali"""
import json
import time
import unittest
from unittest.mock import MagicMock, patch

import ali


def answer(body, status=200):
    return {"s": status, "b": body if isinstance(body, str) else json.dumps(body)}


class FetchTests(unittest.TestCase):
    def fetch(self, *answers, last_call=0.0, call=lambda tab: ali._fetch(tab, "/aer-webapi/v1/search", {"page": 1})):
        tab = MagicMock()
        tab.js.side_effect = list(answers)
        ali._last_call = last_call
        with patch.object(ali.time, "sleep") as sleep, patch.object(ali, "dump", return_value="logs/bodies/x.html"), \
                patch.object(ali, "log") as log:
            try:
                return call(tab), tab, sleep, log
            except RuntimeError as e:
                return e, tab, sleep, log

    def test_post_with_json_body(self):
        got, tab, sleep, _ = self.fetch(answer({"data": {}}))
        self.assertEqual(got, {"data": {}})
        self.assertEqual(tab.js.call_args.args[0],
                         'Promise.race([fetch("/aer-webapi/v1/search", {"method": "POST", "credentials": "include", '
                         '"headers": {"Content-Type": "application/json"}, "body": "{\\"page\\": 1}"})'
                         '.then(async r => ({s: r.status, b: await r.text()})), new Promise(res => setTimeout(() => res(null), 25000))])')
        self.assertEqual(tab.js.call_args.kwargs, {"timeout": 40})
        sleep.assert_not_called()

    def test_product_data_is_a_get_without_body(self):
        got, tab, _, _ = self.fetch(answer({"data": {"reviews": 5}}), call=lambda tab: ali._product_data(tab, "1005006043702745"))
        self.assertEqual(got, {"data": {"reviews": 5}})
        self.assertIn('fetch("/aer-jsonapi/v1/bx/pdp/web/productData?productId=1005006043702745&sourceId=0&sku_id=0", '
                      '{"method": "GET", "credentials": "include", "headers": {"Content-Type": "application/json"}})',
                      tab.js.call_args.args[0])

    def test_waits_out_the_gap_since_the_last_call(self):
        _, _, sleep, _ = self.fetch(answer({}), last_call=time.time())
        self.assertGreater(sleep.call_args.args[0], 1.0)
        self.assertLessEqual(sleep.call_args.args[0], 1.5)

    def test_slider_check_holding_the_request(self):
        got, tab, _, _ = self.fetch(None, True)
        self.assertEqual(str(got), "⚠️ AliExpress показал проверку на бота (слайдер) и держит запросы: shop-chrome show, "
                                   "пройти её во вкладке aliexpress.ru, shop-chrome hide")
        self.assertEqual(tab.js.call_args.args[0], "!!document.querySelector('.baxia-dialog-content')")

    def test_no_answer_in_25_seconds(self):
        got, _, _, _ = self.fetch(None, False)
        self.assertEqual(str(got), "AliExpress не ответил за 25 с на /aer-webapi/v1/search")

    def test_non_json_reloads_the_tab_and_retries(self):
        got, tab, sleep, log = self.fetch(answer("<html>antibot</html>", 403), answer({"data": {"ok": 1}}))
        self.assertEqual(got, {"data": {"ok": 1}})
        tab.goto.assert_called_once_with("https://aliexpress.ru/", "ali", wait_js="document.readyState === 'complete'")
        self.assertEqual(sleep.call_args_list[0].args, (3,))        # then the retry waits out its own gap
        self.assertEqual(log.warning.call_args.args[1:], ("POST", "/aer-webapi/v1/search", 403, "logs/bodies/x.html"))

    def test_non_json_twice_raises_with_the_saved_body(self):
        got, tab, _, log = self.fetch(answer("<html>1</html>", 403), answer("<html>2</html>", 403))
        self.assertEqual(str(got), "AliExpress ответил 403 не-JSON и после перезагрузки вкладки "
                                   "(вероятно, проверка на бота: shop-chrome show). Ответ целиком: logs/bodies/x.html")
        self.assertEqual(tab.goto.call_count, 1)
        log.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
