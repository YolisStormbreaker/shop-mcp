"""Chrome on demand: started by the first tool that needs a tab, once across processes.
No requests to shops, no changes to their accounts.  Run: uv run --with 'websockets>=13' python -B -m unittest -v test_chrome_start"""
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cdp

PAGE = {"type": "page", "url": "https://example.test/", "webSocketDebuggerUrl": "ws://test"}
DOWN = OSError("connection refused")


class ChromeStartTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        for p in (patch.object(cdp, "LOCKS", self.dir), patch.object(cdp, "AGENT", self.dir / "agent.plist"),
                  patch.object(cdp.time, "sleep"), patch.object(cdp, "log"),  # not into the real logs/shop.log
                  patch.object(cdp, "_lock_site")):  # a mocked Tab never frees the site lock
            p.start()
            self.addCleanup(p.stop)
        (self.dir / "agent.plist").touch()

    def ok(self):
        return subprocess.CompletedProcess([], 0, "", "")

    def test_import_does_not_open_browser(self):
        with patch("subprocess.run") as run, patch("urllib.request.urlopen") as http:
            runpy.run_path(str(Path(__file__).with_name("cdp.py")))
        run.assert_not_called()
        http.assert_not_called()

    def test_running_browser_is_reused(self):
        with patch.object(cdp, "_http", return_value=[PAGE]), patch.object(cdp.subprocess, "run") as run, \
                patch.object(cdp, "Tab") as tab:
            cdp.tab_for("example.test")
        run.assert_not_called()
        tab.assert_called_once()
        self.assertEqual(tab.call_args.args[0], "ws://test")

    def test_closed_browser_is_started_once(self):
        # list fails, re-probe under the lock fails, start, probe ok, list; then the second call just lists
        with patch.object(cdp, "_http", side_effect=[DOWN, DOWN, {}, [PAGE], [PAGE]]), \
                patch.object(cdp.subprocess, "run", return_value=self.ok()) as run, patch.object(cdp, "Tab"):
            cdp.tab_for("example.test")
            cdp.tab_for("example.test")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], [str(Path(cdp.__file__).parent / "shop-chrome"), "start"])

    def test_browser_started_by_another_process_is_reused(self):
        with patch.object(cdp, "_http", return_value={"Browser": "Chrome/155"}), \
                patch.object(cdp.subprocess, "run") as run:
            cdp._start_chrome()
        run.assert_not_called()

    def test_first_use_on_this_mac_runs_setup(self):
        (self.dir / "agent.plist").unlink()
        with patch.object(cdp, "_http", side_effect=[DOWN, {}]), \
                patch.object(cdp.subprocess, "run", return_value=self.ok()) as run:
            cdp._start_chrome()
        self.assertEqual(run.call_args.args[0][1:], ["setup"])

    def test_failed_start_says_why_and_does_not_retry(self):
        bad = subprocess.CompletedProcess([], 1, "", "Load failed: 5: Input/output error")
        with patch.object(cdp, "_http", side_effect=DOWN), patch.object(cdp.subprocess, "run", return_value=bad) as run:
            with self.assertRaisesRegex(RuntimeError, "Input/output error"):
                cdp._start_chrome()
        run.assert_called_once()

    def test_wait_for_the_port_is_bounded(self):
        with patch.object(cdp, "_http", side_effect=DOWN) as http, \
                patch.object(cdp.subprocess, "run", return_value=self.ok()) as run:
            with self.assertRaisesRegex(RuntimeError, "30 с"):
                cdp._start_chrome()
        run.assert_called_once()
        self.assertLessEqual(http.call_count, 32)

    def test_no_chrome_app_is_reported_without_launching(self):
        with patch.object(cdp, "CHROME_APP", self.dir / "nope.app"), patch.object(cdp, "_http", side_effect=DOWN), \
                patch.object(cdp.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "не установлен"):
                cdp._start_chrome()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
