"""site_tab: the site's tab, sent to its home page only when it shows something else.
page_json: fetch() from the page, with one retry after a home page load when the answer is not JSON.
Tab: what goes over the DevTools socket (a scripted fake, no Chrome) and how long each wait lasts (a fake clock).
_lock_site with real flock() in a temp dir, _find_tab / tab_for on scripted /json answers, _http.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_cdp"""
import fcntl
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import cdp


class Clock:
    """time.time() and time.sleep() for cdp: sleeping moves the clock, so every deadline loop ends."""
    def __init__(self, now=1000.0):
        self.now, self.slept, self.on_sleep = now, [], None

    def time(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s
        if self.on_sleep:
            self.on_sleep()


class FakeWS:
    """A tab's DevTools socket: send() records the messages, recv() answers the last one with the next reply.
    A reply with "method" (an event) or "id" goes out as is; out of replies, recv() times out like a silent Chrome."""
    def __init__(self, *replies):
        self.replies, self.sent, self.timeouts, self.closed = list(replies), [], [], 0

    def send(self, text):
        self.sent.append(json.loads(text))

    def recv(self, timeout):
        self.timeouts.append(timeout)
        if not self.replies:
            raise TimeoutError
        r = self.replies.pop(0)
        return json.dumps(r if "method" in r or "id" in r else {"id": self.sent[-1]["id"], **r})

    def close(self):
        self.closed += 1

    def methods(self):
        return [m["method"] for m in self.sent]

    def expressions(self):
        return [m["params"]["expression"] for m in self.sent if m["method"] == "Runtime.evaluate"]


def value(v):
    """Chrome's answer to Runtime.evaluate of an expression whose value is v."""
    return {"result": {"result": {"type": "object", "value": v}}}


OK = {"result": {}}
FAILED = {"error": {"code": -32000, "message": "Execution context was destroyed."}}


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


class TabTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        for p in (patch.object(cdp, "time", self.clock), patch.object(cdp, "log"), patch.dict(cdp._last_nav, clear=True)):
            self.addCleanup(p.stop)
            p.start()

    def tab(self, *replies, lock=None):
        ws = FakeWS(*replies)
        with patch.object(cdp, "connect", return_value=ws) as connect:
            tab = cdp.Tab("ws://127.0.0.1:9222/devtools/page/T", lock)
        connect.assert_called_once_with("ws://127.0.0.1:9222/devtools/page/T", max_size=64 * 1024 * 1024, open_timeout=10)
        self.addCleanup(tab.close)
        return tab, ws

    # call
    def test_call_sends_the_method_and_returns_its_result(self):
        tab, ws = self.tab({"result": {"frameId": "F1"}})
        self.assertEqual(tab.call("Page.navigate", url="https://shop.test/"), {"frameId": "F1"})
        self.assertEqual(ws.sent, [{"id": ws.sent[0]["id"], "method": "Page.navigate", "params": {"url": "https://shop.test/"}}])

    def test_call_waits_past_events_and_other_answers_for_its_own(self):
        tab, ws = self.tab({"method": "Page.loadEventFired", "params": {}}, {"id": -1, "result": {"n": 1}}, {"result": {"n": 2}})
        self.assertEqual(tab.call("Page.reload"), {"n": 2})

    def test_call_error_names_the_method(self):
        tab, _ = self.tab(FAILED)
        with self.assertRaisesRegex(RuntimeError, "^Page.reload: .*Execution context was destroyed"):
            tab.call("Page.reload")

    def test_answer_without_result_is_empty(self):
        tab, _ = self.tab({})
        self.assertEqual(tab.call("Page.reload"), {})

    def test_call_waits_no_longer_than_its_timeout(self):
        tab, ws = self.tab({"method": "Page.frameNavigated"})
        with self.assertRaises(TimeoutError):
            tab.call("Page.reload", timeout=7)
        self.assertEqual(ws.timeouts, [7, 7])

    def test_late_wait_gets_at_least_a_tenth_of_a_second(self):
        tab, ws = self.tab()
        times = iter([1000.0, 2000.0])          # the deadline is long past when recv() is called
        self.clock.time = lambda: next(times)
        with self.assertRaises(TimeoutError):
            tab.call("Page.reload", timeout=7)
        self.assertEqual(ws.timeouts, [0.1])

    # js
    def test_js_evaluates_awaiting_promises_and_returns_the_value(self):
        tab, ws = self.tab(value({"title": "Ozon"}))
        self.assertEqual(tab.js("fetch('/x').then(r => r.json())"), {"title": "Ozon"})
        self.assertEqual(ws.sent[0]["params"], {"expression": "fetch('/x').then(r => r.json())",
                                                "awaitPromise": True, "returnByValue": True})

    def test_js_exception_is_raised_with_its_description(self):
        tab, _ = self.tab({"result": {"result": {}, "exceptionDetails": {
            "text": "Uncaught", "exception": {"description": "TypeError: x is undefined"}}}})
        with self.assertRaisesRegex(RuntimeError, "^TypeError: x is undefined$"):
            tab.js("x.y")

    def test_js_exception_without_description_is_raised_with_its_text(self):
        tab, _ = self.tab({"result": {"result": {}, "exceptionDetails": {"text": "Uncaught (in promise)"}}})
        with self.assertRaisesRegex(RuntimeError, r"^Uncaught \(in promise\)$"):
            tab.js("Promise.reject()")

    def test_undefined_is_none(self):
        tab, _ = self.tab({"result": {"result": {"type": "undefined"}}})
        self.assertIsNone(tab.js("void 0"))

    # open and close
    def test_close_frees_the_socket_and_the_site_lock_once(self):
        lock = MagicMock()
        tab, ws = self.tab(lock=lock)
        tab.close()
        tab.close()
        self.assertEqual(ws.closed, 1)
        lock.close.assert_called_once_with()

    def test_failed_connect_frees_the_site_lock(self):
        lock = MagicMock()
        with patch.object(cdp, "connect", side_effect=OSError("connection refused")):
            with self.assertRaisesRegex(OSError, "connection refused"):
                cdp.Tab("ws://127.0.0.1:9222/devtools/page/T", lock)
        lock.close.assert_called_once_with()

    # click
    def test_click_in_a_hidden_tab_does_nothing(self):
        tab, ws = self.tab(value("hidden"))
        self.assertFalse(tab.click("#buy"))
        self.assertEqual(ws.expressions(), ["document.visibilityState"])

    def test_click_on_a_missing_element_does_nothing(self):
        tab, ws = self.tab(value("visible"), value(None))
        self.assertFalse(tab.click("button[data-x='1']"))
        self.assertEqual(ws.methods(), ["Runtime.evaluate", "Runtime.evaluate"])
        self.assertIn('document.querySelector("button[data-x=\'1\']")', ws.expressions()[1])

    def test_click_is_a_real_mouse_click_on_the_element_centre(self):
        tab, ws = self.tab(value("visible"), value([120.5, 300]), OK, OK, OK)
        self.assertTrue(tab.click("#buy"))
        self.assertEqual([m["params"] for m in ws.sent[2:]],
                         [{"type": t, "x": 120.5, "y": 300, "button": "left", "clickCount": 1}
                          for t in ("mouseMoved", "mousePressed", "mouseReleased")])
        self.assertEqual(ws.methods()[2:], ["Input.dispatchMouseEvent"] * 3)
        self.assertEqual(self.clock.slept, [0.4])   # after scrollIntoView

    # goto
    def test_goto_navigates_and_returns_once_the_page_is_interactive(self):
        tab, ws = self.tab(OK, value("loading"), value("interactive"))
        self.assertIsNone(tab.goto("https://shop.test/p/1", "shop"))
        self.assertEqual(ws.sent[0]["method"], "Page.navigate")
        self.assertEqual(ws.sent[0]["params"], {"url": "https://shop.test/p/1"})
        self.assertEqual(ws.expressions(), ["document.readyState"] * 2)
        self.assertEqual(self.clock.slept, [1.5, 0.7])
        self.assertEqual(cdp._last_nav["shop"], 1000.0)

    def test_goto_waits_for_the_condition_as_a_boolean(self):
        tab, ws = self.tab(OK, value("complete"), value(False), value("complete"), value(True))
        tab.goto("https://shop.test/", "shop", wait_js="document.querySelector('.card')")
        self.assertEqual(ws.expressions(), ["document.readyState", "!!(document.querySelector('.card'))"] * 2)

    def test_goto_keeps_loads_on_one_site_min_gap_apart(self):
        for ago in (1.0, 3.5):
            with self.subTest(ago):
                self.clock.slept.clear()
                cdp._last_nav["shop"] = self.clock.now - ago
                tab, _ = self.tab(OK, value("complete"))
                start = self.clock.now
                tab.goto("https://shop.test/", "shop")
                self.assertEqual(self.clock.slept[0], cdp.MIN_GAP - ago)
                self.assertEqual(cdp._last_nav["shop"], start + cdp.MIN_GAP - ago)

    def test_goto_does_not_wait_after_another_site(self):
        cdp._last_nav["other"] = 999.0
        tab, _ = self.tab(OK, value("complete"))
        tab.goto("https://shop.test/", "shop")
        self.assertEqual(self.clock.slept, [1.5])

    def test_goto_polls_through_a_document_swap(self):
        tab, ws = self.tab(OK, FAILED, value("complete"))
        tab.goto("https://shop.test/", "shop")
        self.assertEqual(len(ws.expressions()), 2)

    def test_goto_gives_up_quietly_at_its_timeout(self):
        tab, ws = self.tab(OK)                          # Chrome never answers readyState
        self.assertIsNone(tab.goto("https://shop.test/", "shop", timeout=3))
        self.assertEqual(len(ws.expressions()), 3)       # at 1.5, 2.2 and 2.9 s
        self.assertGreaterEqual(self.clock.now, 1003)

    # heal
    def test_clean_page_is_left_alone(self):
        tab, ws = self.tab(value(False))
        tab.heal()
        self.assertEqual(ws.methods(), ["Runtime.evaluate"])
        self.assertIn("'__req' in window", ws.expressions()[0])
        cdp.log.warning.assert_not_called()

    def test_page_that_cannot_be_checked_is_left_alone(self):
        tab, ws = self.tab(FAILED)
        tab.heal()
        self.assertEqual(ws.methods(), ["Runtime.evaluate"])

    def test_page_with_a_probe_is_reloaded_and_awaited(self):
        tab, ws = self.tab(value(True), value("https://www.ozon.ru/my"), OK, FAILED, value("loading"), value("complete"))
        tab.heal()
        self.assertEqual(ws.methods(), ["Runtime.evaluate"] * 2 + ["Page.reload"] + ["Runtime.evaluate"] * 3)
        self.assertEqual(ws.expressions()[1:], ["location.href"] + ["document.readyState"] * 3)
        cdp.log.warning.assert_called_once_with("debugging probe left in %s, reloading the tab", "https://www.ozon.ru/my")

    def test_reload_wait_is_bounded(self):
        tab, ws = self.tab(value(True), value("https://www.ozon.ru/my"), OK)
        tab.heal(timeout=3)
        self.assertEqual(ws.expressions().count("document.readyState"), 3)
        self.assertGreaterEqual(self.clock.now, 1003)


class SiteLockTests(unittest.TestCase):
    """_lock_site with real flock() on files in a temp dir: one caller per site's tab, across processes."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "cache"         # made on first use
        self.clock = Clock()
        for p in (patch.object(cdp, "LOCKS", self.dir), patch.object(cdp, "time", self.clock)):
            self.addCleanup(p.stop)
            p.start()

    def held(self, domain):
        """The site lock as another process holds it."""
        f = open(self.dir / f"tab-{domain}.lock", "w")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(f.close)
        return f

    def test_free_site_is_taken_at_once(self):
        lock = cdp._lock_site("ozon.ru")
        self.addCleanup(lock.close)
        self.assertEqual(Path(lock.name), self.dir / "tab-ozon.ru.lock")
        with open(lock.name, "w") as other, self.assertRaises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.clock.slept, [])

    def test_busy_site_is_taken_when_the_other_call_ends(self):
        cdp._lock_site("wb.ru").close()
        other = self.held("wb.ru")
        self.clock.on_sleep = lambda: len(self.clock.slept) == 3 and other.close()
        lock = cdp._lock_site("wb.ru")
        self.addCleanup(lock.close)
        self.assertEqual(self.clock.slept, [0.2] * 3)

    def test_other_sites_do_not_wait(self):
        cdp._lock_site("wb.ru").close()
        self.held("wb.ru")
        cdp._lock_site("ozon.ru").close()
        self.assertEqual(self.clock.slept, [])

    def test_wait_for_a_busy_site_is_bounded(self):
        cdp._lock_site("wb.ru").close()
        self.held("wb.ru")
        with self.assertRaisesRegex(RuntimeError, f"^вкладка wb.ru занята другим вызовом дольше {cdp.LOCK_WAIT} с$"):
            cdp._lock_site("wb.ru")
        self.assertGreater(self.clock.now, 1000 + cdp.LOCK_WAIT)


def target(url, ws, type="page"):
    return {"type": type, "url": url, "webSocketDebuggerUrl": ws}


class FindTabTests(unittest.TestCase):
    def find(self, *answers):
        lock = MagicMock()
        with patch.object(cdp, "_http", side_effect=answers) as http, patch.object(cdp, "Tab") as tab:
            got = cdp._find_tab("ozon.ru", lock)
        self.assertIs(got, tab.return_value)
        return tab.call_args, http.call_args_list, lock

    def test_site_tab_is_reused(self):
        args, http, lock = self.find([target("chrome://newtab/", "ws://blank"), target("https://www.ozon.ru/cart", "ws://ozon")])
        self.assertEqual(args, call("ws://ozon", lock))
        self.assertEqual(http, [call("/json/list")])

    def test_only_pages_count(self):
        args, _, lock = self.find([target("https://www.ozon.ru/sw.js", "ws://sw", type="service_worker"),
                                   target("about:blank", "ws://blank")])
        self.assertEqual(args, call("ws://blank", lock))

    def test_new_tab_page_is_taken_before_opening_one(self):
        args, http, lock = self.find([target("https://mail.test/", "ws://mail"), target("chrome://newtab/", "ws://newtab")])
        self.assertEqual(args, call("ws://newtab", lock))
        self.assertEqual(http, [call("/json/list")])

    def test_tab_is_opened_when_none_is_free(self):
        args, http, lock = self.find([target("https://mail.test/", "ws://mail")], {"webSocketDebuggerUrl": "ws://new"})
        self.assertEqual(args, call("ws://new", lock))
        self.assertEqual(http, [call("/json/list"), call("/json/new?about:blank", method="PUT")])


class TabForTests(unittest.TestCase):
    def test_tab_is_healed_before_it_is_handed_out(self):
        tab = MagicMock()
        with patch.object(cdp, "_lock_site") as lock_site, patch.object(cdp, "_find_tab", return_value=tab) as find:
            self.assertIs(cdp.tab_for("ozon.ru"), tab)
        find.assert_called_once_with("ozon.ru", lock_site.return_value)
        tab.heal.assert_called_once_with()

    def test_site_is_freed_when_no_tab_is_found(self):
        with patch.object(cdp, "_lock_site") as lock_site, \
                patch.object(cdp, "_find_tab", side_effect=RuntimeError("Chrome магазинов не поднялся")):
            with self.assertRaisesRegex(RuntimeError, "не поднялся"):
                cdp.tab_for("ozon.ru")
        lock_site.return_value.close.assert_called_once_with()


class HttpTests(unittest.TestCase):
    def http(self, *args, **kw):
        answer = MagicMock()
        answer.__enter__.return_value.read.return_value = b'{"Browser": "Chrome/155"}'
        with patch.object(cdp.urllib.request, "urlopen", return_value=answer) as urlopen:
            got = cdp._http(*args, **kw)
        req, = urlopen.call_args.args
        return got, req, urlopen.call_args.kwargs

    def test_get_from_the_shop_chrome_port(self):
        got, req, kw = self.http("/json/version")
        self.assertEqual(got, {"Browser": "Chrome/155"})
        self.assertEqual((req.full_url, req.get_method(), kw), ("http://127.0.0.1:9222/json/version", "GET", {"timeout": 10}))

    def test_method_and_timeout_are_passed(self):
        _, req, kw = self.http("/json/new?about:blank", method="PUT", timeout=2)
        self.assertEqual((req.full_url, req.get_method(), kw), ("http://127.0.0.1:9222/json/new?about:blank", "PUT", {"timeout": 2}))


if __name__ == "__main__":
    unittest.main()
