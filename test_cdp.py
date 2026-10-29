"""site_tab: the site's tab, sent to its home page only when it shows something else.
page_json: fetch() from the page, with one retry after a home page load when the answer is not JSON.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_cdp"""
import unittest
from unittest.mock import MagicMock, patch

import cdp


class SiteTabTests(unittest.TestCase):
    def site_tab(self, on_site, **kw):
        tab = MagicMock()
        tab.js.return_value = on_site
        with patch.object(cdp, "tab_for", return_value=tab) as tab_for:
            got = cdp.site_tab("ozon.ru", "https://www.ozon.ru/", "ozon", **kw)
        tab_for.assert_called_once_with("ozon.ru")
        self.assertIs(got, tab)
        return tab

    def test_tab_on_the_site_stays_where_it_is(self):
        self.site_tab(True).goto.assert_not_called()

    def test_tab_elsewhere_loads_the_home_page(self):
        tab = self.site_tab(False)
        tab.goto.assert_called_once_with("https://www.ozon.ru/", "ozon", wait_js="document.readyState === 'complete'")

    def test_hostname_is_checked_by_its_ending(self):
        expr = self.site_tab(True).js.call_args.args[0]
        self.assertIn('location.hostname.endsWith("ozon.ru")', expr)

    def test_a_page_not_ready_is_loaded_again_and_awaited(self):
        tab = self.site_tab(False, ready="!!window.__STATE__")
        self.assertIn("!!window.__STATE__", tab.js.call_args.args[0])
        tab.goto.assert_called_once_with("https://www.ozon.ru/", "ozon", wait_js="!!window.__STATE__")


class PageJsonTests(unittest.TestCase):
    def page_json(self, *answers, method="GET", body=None):
        tab = MagicMock()
        tab.js.side_effect = [{"s": s, "b": b} for s, b in answers]
        with patch.object(cdp, "log") as log:
            got = cdp.page_json(tab, method, "/api/x", body, "https://shop.test/", "shop")
        return got, tab, log

    def test_json_answer(self):
        got, tab, _ = self.page_json((200, '{"ok": 1}'))
        self.assertEqual(got, {"ok": 1})
        tab.goto.assert_not_called()
        self.assertIn('fetch("/api/x", {"method": "GET", "credentials": "include"})', tab.js.call_args.args[0])

    def test_body_is_sent_as_json(self):
        _, tab, _ = self.page_json((200, "{}"), method="POST", body={"sku": "A"})
        self.assertIn('"headers": {"Content-Type": "application/json"}, "body": "{\\"sku\\": \\"A\\"}"', tab.js.call_args.args[0])

    def test_anti_bot_page_is_passed_by_one_home_page_load(self):
        got, tab, log = self.page_json((403, "<html>"), (200, "[1]"))
        self.assertEqual(got, [1])
        tab.goto.assert_called_once_with("https://shop.test/", "shop", wait_js="document.readyState === 'complete'")
        self.assertEqual(log.warning.call_args.args, ("%s %s %s: %s non-JSON%s", "shop", "GET", "/api/x", 403, ""))

    def test_second_non_json_answer_gives_none(self):
        got, tab, log = self.page_json((403, "<html>"), (403, "<html>"))
        self.assertIsNone(got)
        tab.goto.assert_called_once()
        self.assertEqual(log.warning.call_args.args[-1], " again after reload")


if __name__ == "__main__":
    unittest.main()
