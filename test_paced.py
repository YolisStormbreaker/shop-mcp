"""Every channel to a shop asks the shared budget (pace) for its slot before it goes out: the requests inside a page,
the site's API from the host (WB's public JSON, ВкусВилл's API), and Авито's in-page batch at its size.
cdp's page loads and page_json are in test_cdp, the modules' own fetch helpers in their tests.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_paced"""
import io
import json
import unittest
from unittest.mock import MagicMock, call, patch

import avito
import orders
import reviews
import wb
from grocery import lavka, samokat, vkusvill


class PacedTests(unittest.TestCase):
    def asks(self, module, fn, want):
        with patch.object(module, "pace") as pace:
            fn()
        self.assertEqual(pace.acquire.call_args_list, want)

    def test_page_requests(self):
        tab = MagicMock()
        tab.js.return_value = {}
        cases = [(avito, lambda: avito._shipping(tab, ["/a", "/b", "/c"]), [call("avito", cost=3)]),   # one slot per item
                 (avito, lambda: avito._shipping(tab, []), []),
                 (lavka, lambda: lavka._post(tab, "cart/v1/retrieve", {}), [call("lavka")]),
                 (samokat, lambda: samokat._call(tab, "cart", {}), [call("samokat")]),
                 (vkusvill, lambda: vkusvill._cart(tab), [call("vkusvill")]),
                 (orders, lambda: orders._ali_detail(tab, "8100"), [call("ali")]),
                 (reviews, lambda: reviews._ali_first_page(tab), [call("ali")])]
        for module, fn, want in cases:
            with self.subTest(module.__name__, want=want):
                self.asks(module, fn, want)

    def test_the_site_s_api_from_this_host(self):
        reply = MagicMock()
        reply.__enter__.return_value = io.BytesIO(b'{"result": {"content": [{"text": "{\\"ok\\": true, \\"data\\": 1}"}]}}')
        with patch.object(wb.urllib.request, "urlopen", return_value=reply):
            self.asks(wb, lambda: wb._get("https://card.wb.ru/x"), [call("wb")])
        reply.__enter__.return_value = io.BytesIO(json.dumps({"result": {"content": [{"text": json.dumps({"ok": True, "data": 1})}]}}).encode())
        with patch.object(vkusvill.urllib.request, "urlopen", return_value=reply):
            self.asks(vkusvill, lambda: vkusvill._mcp("vkusvill_shops", {}), [call("vkusvill")])


if __name__ == "__main__":
    unittest.main()
