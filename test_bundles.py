"""bundles.py: a site's scripts fetched once, each by a slot of the shared budget, kept on disk and searched there.
A fake tab and a temp cache; no requests to shops.  Run: .venv/bin/python -B -m unittest -v test_bundles"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import bundles
import pace

PAGE = "https://www.perekrestok.ru/cart"
SCRIPTS = {"https://www.perekrestok.ru/a.js": "x;setItem:(e)=>f.put(\"/basket/\".concat(t,\"/amount\"),{amount:r});y",
           "https://cdn.test/b.js": "nothing here"}


def fake_tab():
    tab = MagicMock()

    def js(expr, timeout=None):
        if expr == bundles.SCRIPTS_JS:
            return list(SCRIPTS)
        return SCRIPTS[json.loads(expr[len("fetch("):expr.index(", {")])]
    tab.js.side_effect = js
    return tab


class BundleTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.tab = fake_tab()
        for p in (patch.object(bundles, "CACHE", Path(d.name)), patch.object(bundles.cdp, "tab_for", return_value=self.tab)):
            p.start()
            self.addCleanup(p.stop)
        self.pace = patch.object(bundles, "pace").start()
        self.pace.Refused, self.pace.POLICY = pace.Refused, pace.POLICY      # the budget's slots are faked, not its words
        self.addCleanup(patch.stopall)

    def fetched(self):
        return [c.args[0] for c in self.tab.js.call_args_list if c.args[0].startswith("fetch(")]

    def test_each_script_is_fetched_once_by_a_slot_and_then_read_from_disk(self):
        self.assertEqual(bundles.scripts("perekrestok", PAGE), SCRIPTS)
        self.assertEqual(len(self.fetched()), 2)
        self.assertEqual(self.pace.acquire.call_args_list, [call("perekrestok", "api")] * 2)
        bundles.cdp.tab_for.assert_called_with("perekrestok.ru")
        self.tab.goto.assert_called_once_with(PAGE, "perekrestok", wait_js="document.readyState === 'complete'")
        self.tab.close.assert_called_once()
        self.tab.reset_mock()
        self.pace.reset_mock()
        self.assertEqual(bundles.scripts("perekrestok", PAGE), SCRIPTS)
        self.assertEqual((self.fetched(), self.pace.acquire.call_args_list), ([], []))

    def test_a_refusal_keeps_what_was_fetched(self):
        self.pace.acquire.side_effect = [None, pace.Refused("⏸ Перекрёсток: предел")]
        with self.assertRaisesRegex(pace.Refused, "предел"):
            bundles.scripts("perekrestok", PAGE)
        self.tab.close.assert_called_once()
        self.pace.acquire.side_effect = None
        bundles.scripts("perekrestok", PAGE)
        self.assertEqual(len(self.fetched()), 2)              # the first was not fetched again

    def test_search_shows_each_hit_in_its_context(self):
        hits = bundles.search(SCRIPTS, r"/amount", context=12)
        self.assertEqual(hits, [("https://www.perekrestok.ru/a.js", '".concat(t,"/amount"),{amount:r')])   # 12 on each side

    def run_cli(self, *argv):
        with patch("builtins.print") as out:
            code = bundles.main(list(argv))
        return code, [str(c.args[0]) for c in out.call_args_list]

    def test_the_command(self):
        code, said = self.run_cli("perekrestok", PAGE, "amount", "8")
        self.assertEqual(code, 0)
        self.assertEqual(said[0], "скриптов: 2, совпадений: 2")

    def test_the_command_says_why_the_budget_refused(self):
        self.pace.acquire.side_effect = pace.Refused("⏸ Перекрёсток: блокировка по IP")
        self.assertEqual(self.run_cli("perekrestok", PAGE, "amount"), (1, ["⏸ Перекрёсток: блокировка по IP"]))

    def test_a_site_outside_the_budget_is_wrong_use(self):
        """A typo in the site would count the page's requests to no site's budget and walk past its stop."""
        for argv in (["perekrestk", PAGE, "amount"], ["perekrestok", PAGE], ["perekrestok", PAGE, "amount", "8", "x"]):
            with self.subTest(argv):
                code, said = self.run_cli(*argv)
                self.assertEqual((code, said), (2, ["Run: .venv/bin/python bundles.py <site> <page url> <regex> [context]"]))
        self.assertEqual(self.tab.js.call_args_list, [])


if __name__ == "__main__":
    unittest.main()
