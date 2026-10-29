"""site_tab: the site's tab, sent to its home page only when it shows something else.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_site_tab"""
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


if __name__ == "__main__":
    unittest.main()
