"""netlog.py: one paced page load, the page's JSON answers (XHR and fetch) kept with their addresses, a block page
recognised. A scripted CDP websocket, a fake clock, a temp folder; no browser.  Run: .venv/bin/python -B -m unittest -v test_netlog"""
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import netlog
from test_capture import FakeWs, body, finished

URL = "https://www.shop.test/search?q=tv"


def response(rid, url, kind="Fetch", status=200):
    return {"method": "Network.responseReceived", "params": {"requestId": rid, "type": kind, "response": {"url": url, "status": status}}}


class NetlogTests(unittest.TestCase):
    def run_page(self, script, state=None):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        ws, clock = FakeWs(script), MagicMock()
        clock.time.side_effect = itertools.count(1000.0, 1.0)
        tab = MagicMock(ws=ws)
        tab.js.return_value = state or {}
        tab._probe.return_value = {"url": URL}
        with patch.object(netlog, "time", clock), patch.object(netlog, "pace") as pace, \
                patch.object(netlog.cdp, "tab_for", return_value=tab) as tab_for, patch.object(netlog, "CACHE", Path(d.name)):
            got = netlog.record("eldorado", URL, wait=10)
        return got, tab, pace, tab_for, Path(d.name)

    def test_the_page_s_json_answers_with_their_addresses(self):
        script = [response("1", "https://api.shop.test/search?q=tv"), finished("1"), body('{"items": [1, 2]}'),
                  response("2", "https://www.shop.test/app.js", kind="Script"), finished("2"),
                  response("3", "https://api.shop.test/broken", status=500), finished("3"), body("<html>oops"),
                  response("4", "https://api.shop.test/late")]                     # never finished: no body
        got, tab, pace, tab_for, folder = self.run_page(script, state={"__NEXT_DATA__": {"props": {}}})
        self.assertEqual([(r["url"], r["status"], r["json"]) for r in got["responses"]],
                         [("https://api.shop.test/search?q=tv", 200, {"items": [1, 2]}),
                          ("https://api.shop.test/broken", 500, None)])
        self.assertEqual(got["responses"][1]["text"], "<html>oops")
        self.assertEqual(got["state"], {"__NEXT_DATA__": {"props": {}}})
        tab_for.assert_called_once_with("shop.test")
        pace.acquire.assert_called_once_with("eldorado", "page")
        pace.check_page.assert_called_once_with("eldorado", {"url": URL})
        tab.close.assert_called_once()
        self.assertEqual(json.loads((folder / "eldorado" / "last.json").read_text()), got)

    def test_the_summary_names_each_answer_and_its_keys(self):
        got = {"url": URL, "responses": [{"url": "https://api.shop.test/search?q=tv", "status": 200, "json": {"items": [], "total": 3}},
                                          {"url": "https://api.shop.test/broken", "status": 500, "json": None, "text": "<html>oops"}],
               "state": {"__NEXT_DATA__": {"props": {}, "page": "/search"}}}
        self.assertEqual(netlog.summary(got).splitlines(),
                         ["https://www.shop.test/search?q=tv: 2 ответа",
                          "200 https://api.shop.test/search?q=tv — {items, total}",
                          "500 https://api.shop.test/broken — не JSON: <html>oops",
                          "window.__NEXT_DATA__ — {page, props}"])


if __name__ == "__main__":
    unittest.main()
