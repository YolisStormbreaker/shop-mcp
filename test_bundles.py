"""bundles.py: one paced page load, the page's scripts read from its debugger (no requests), kept on disk, searched.
A fake tab and a temp cache; no requests to shops.  Run: .venv/bin/python -B -m unittest -v test_bundles"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import bundles
import pace
from test_capture import FakeWs

PAGE = "https://www.perekrestok.ru/cart"
SCRIPTS = {"https://www.perekrestok.ru/a.js": "x;setItem:(e)=>f.put(\"/basket/\".concat(t,\"/amount\"),{amount:r});y",
           "https://cdn.test/b.js": "nothing here"}


def parsed(sid, url):
    return {"method": "Debugger.scriptParsed", "params": {"scriptId": sid, "url": url}}


def fake_tab():
    """A tab whose debugger reports the page's scripts on Debugger.enable — two files, an inline one, an eval'd one
    without an address — and gives each one's source by its id."""
    enabled = lambda sent: {"id": sent[-1]["id"], "result": {}}            # the answer to Debugger.enable comes after the report
    noise = {"method": "Network.dataReceived", "params": {}}               # a busy page never falls silent
    ws = FakeWs([parsed("1", "https://www.perekrestok.ru/a.js"), noise, parsed("2", "https://cdn.test/b.js"), parsed("3", ""),
                 parsed("4", "debugger://VM12"), enabled, parsed("5", "https://late.test/c.js")] + [noise] * 50)
    sources = dict(zip(("1", "2"), SCRIPTS.values()))
    tab = MagicMock(ws=ws)
    tab.call.side_effect = lambda method, **p: {"scriptSource": sources[p["scriptId"]]} if method == "Debugger.getScriptSource" else {}
    return tab


class BundleTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.tab = fake_tab()
        for p in (patch.object(bundles, "CACHE", Path(d.name) / "cache" / "bundles"),       # not there yet, as on a fresh copy
                  patch.object(bundles.cdp, "tab_for", return_value=self.tab)):
            p.start()
            self.addCleanup(p.stop)
        self.pace = patch.object(bundles, "pace").start()
        self.pace.Refused, self.pace.POLICY = pace.Refused, pace.POLICY      # the budget's slots are faked, not its words
        self.addCleanup(patch.stopall)

    def test_the_page_s_scripts_come_from_its_debugger_with_no_request_of_their_own(self):
        """A CDN that refuses a fetch from the page (CORS) cannot fail it, and the page load is the only slot."""
        self.assertEqual(bundles.scripts("perekrestok", PAGE), SCRIPTS)
        bundles.cdp.tab_for.assert_called_with("perekrestok.ru")
        self.tab.goto.assert_called_once_with(PAGE, "perekrestok", wait_js="document.readyState === 'complete'")
        self.tab.js.assert_not_called()                                   # no fetch() in the page
        self.pace.acquire.assert_not_called()                             # goto took the page's slot
        self.assertEqual(self.tab.ws.sent[0]["method"], "Debugger.enable")
        self.tab.close.assert_called_once()
        kept = sorted(f.read_text() for f in (bundles.CACHE / "perekrestok").iterdir())
        self.assertEqual(kept, sorted(SCRIPTS.values()))                 # for reading again with other tools

    def test_a_refused_page_load_reads_nothing(self):
        self.tab.goto.side_effect = pace.Refused("⏸ Перекрёсток: предел")
        with self.assertRaisesRegex(pace.Refused, "предел"):
            bundles.scripts("perekrestok", PAGE)
        self.tab.call.assert_not_called()
        self.tab.close.assert_called_once()

    def test_search_shows_each_hit_in_its_context(self):
        hits = bundles.search(SCRIPTS, r"/amount", context=12)
        self.assertEqual(hits, [("https://www.perekrestok.ru/a.js", '".concat(t,"/amount"),{amount:r')])   # 12 on each side
        self.assertEqual(bundles.search({"c.js": "amount=1;rest"}, "amount", context=3), [("c.js", "amount=1;")])   # from the start

    def run_cli(self, *argv):
        with patch("builtins.print") as out:
            code = bundles.main(list(argv))
        return code, [str(c.args[0]) for c in out.call_args_list]

    def test_the_command(self):
        code, said = self.run_cli("perekrestok", PAGE, "amount", "8")
        self.assertEqual(code, 0)
        self.assertEqual(said, ["скриптов: 2, совпадений: 2", '- a.js: cat(t,"/amount"),{amou', '- a.js: ount"),{amount:r});y'])

    def test_the_command_says_why_the_budget_refused(self):
        self.tab.goto.side_effect = pace.Refused("⏸ Перекрёсток: блокировка по IP")
        self.assertEqual(self.run_cli("perekrestok", PAGE, "amount"), (1, ["⏸ Перекрёсток: блокировка по IP"]))

    def test_a_site_outside_the_budget_is_wrong_use(self):
        """A typo in the site would count the page's requests to no site's budget and walk past its stop."""
        for argv in (["perekrestk", PAGE, "amount"], ["perekrestok", PAGE], ["perekrestok", PAGE, "amount", "8", "x"]):
            with self.subTest(argv):
                code, said = self.run_cli(*argv)
                self.assertEqual((code, said), (2, ["Run: .venv/bin/python bundles.py <site> <page url> <regex> [context]"]))
        bundles.cdp.tab_for.assert_not_called()


if __name__ == "__main__":
    unittest.main()
