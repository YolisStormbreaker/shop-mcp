"""capture(): navigate (or run js), let paused requests go (rewritten or as they were), match responses
by URL parts and read their bodies, over a scripted CDP websocket and a fake clock.
No browser.  Run: .venv/bin/python -B -m unittest -v test_capture"""
import base64
import itertools
import json
import unittest
from unittest.mock import MagicMock, patch

import capture as C
import cdp

URL = "https://shop.test/p"


class FakeWs:
    """send() records; recv(timeout=) replays the script, then raises TimeoutError."""

    def __init__(self, script):
        self.script, self.sent = list(script), []

    def send(self, raw):
        self.sent.append(json.loads(raw))

    def recv(self, timeout=None):
        if not self.script:
            raise TimeoutError
        m = self.script.pop(0)
        return json.dumps(m(self.sent) if callable(m) else m)


def response(rid, url):
    return {"method": "Network.responseReceived", "params": {"requestId": rid, "response": {"url": url}}}


def finished(rid):
    return {"method": "Network.loadingFinished", "params": {"requestId": rid}}


def paused(rid, url):
    return {"method": "Fetch.requestPaused", "params": {"requestId": rid, "request": {"url": url, "headers": {"Authorization": "Bearer t"}}}}


def body(text=None, **reply):
    """The browser's answer to the last Network.getResponseBody sent."""
    def answer(sent):
        i = [s for s in sent if s["method"] == "Network.getResponseBody"][-1]["id"]
        return {"id": i, **(reply or {"result": {"body": text}})}
    return answer


def run(script, patterns, last_nav=None, **kw):
    """(result, [(method, params) sent, Fetch.enable included], clock)"""
    ws, clock = FakeWs(script), MagicMock()
    clock.time.side_effect = itertools.count(1000.0, 1.0)   # every reading one second later
    tab = MagicMock(ws=ws)
    tab.call.side_effect = lambda method, **params: ws.sent.append({"method": method, "params": params})
    with patch.object(C, "time", clock), patch.dict(cdp._last_nav, last_nav or {}, clear=True):
        got = C.capture(tab, "shop", URL, patterns, **kw)
        clock.last_nav = dict(cdp._last_nav)
    return got, [(s["method"], s["params"]) for s in ws.sent], clock


class CaptureTests(unittest.TestCase):
    def test_navigates_and_reads_the_matching_response(self):
        got, sent, clock = run([response("r0", "https://api.test/other"), finished("r0"), {"method": "Page.frameNavigated"},
                                response("r1", "https://api.test/x?a=1"), finished("r1"), body('{"ok": 1}'),
                                response("r2", "https://api.test/x?a=1")], {"x": ["/x", "a=1"]})
        self.assertEqual(got, {"x": {"ok": 1}})
        self.assertEqual(sent, [("Network.enable", {}), ("Page.navigate", {"url": URL}),
                                ("Network.getResponseBody", {"requestId": "r1"}), ("Network.disable", {})])
        clock.sleep.assert_not_called()
        self.assertEqual(clock.last_nav, {"shop": 1001.0})

    def test_js_runs_in_the_page_instead_of_navigating(self):
        _, sent, _ = run([], {"x": ["/x"]}, js="router.go('/x')")
        self.assertEqual(sent[1], ("Runtime.evaluate", {"expression": "router.go('/x')"}))

    def test_waits_out_the_gap_since_the_last_page_load_on_the_site(self):
        _, _, clock = run([], {"x": ["/x"]}, last_nav={"shop": 999.0, "other": 1.0})
        clock.sleep.assert_called_once_with(cdp.MIN_GAP - 1)
        self.assertEqual(clock.last_nav, {"shop": 1001.0, "other": 1.0})

    def test_re_part_is_a_regular_expression(self):
        got, _, _ = run([response("r1", "https://api.test/favorites?all"), finished("r1"),
                         response("r2", "https://api.test/catalog/favorites"), finished("r2"), body("[1]")],
                        {"f": ["re:/favorites$", "catalog"]})
        self.assertEqual(got, {"f": [1]})

    def test_each_name_takes_the_first_response_it_matches(self):
        got, sent, _ = run([response("r1", "https://api.test/a?n=1"), response("r2", "https://api.test/a?n=2"),
                            response("r3", "https://api.test/b"), finished("r2"), finished("r1"), body('"a1"'),
                            finished("r3"), body('"b"')], {"a": ["/a"], "b": ["/b"]})
        self.assertEqual(got, {"a": "a1", "b": "b"})
        self.assertNotIn(("Network.getResponseBody", {"requestId": "r2"}), sent)

    def test_a_response_matching_two_names_is_read_for_the_last_of_them(self):
        got, _, _ = run([response("r1", "https://api.test/ab"), finished("r1"), body('"ab"'),
                         response("r2", "https://api.test/a"), finished("r2"), body('"a"')], {"a": ["/a"], "b": ["b"]})
        self.assertEqual(got, {"b": "ab", "a": "a"})

    def test_rewrite_sends_the_paused_request_to_a_new_url(self):
        got, sent, _ = run([paused("f1", "https://api.test/s?q=1"), response("r1", "https://api.test/s?q=1&page=2"),
                            finished("r1"), body("{}")], {"s": ["/s"]}, rewrite=("*/s?*", lambda u: u + "&page=2"))
        self.assertEqual(got, {"s": {}})
        self.assertEqual(sent, [("Network.enable", {}),
                                ("Fetch.enable", {"patterns": [{"urlPattern": "*/s?*", "requestStage": "Request"}]}),
                                ("Page.navigate", {"url": URL}),
                                ("Fetch.continueRequest", {"requestId": "f1", "url": "https://api.test/s?q=1&page=2"}),
                                ("Network.getResponseBody", {"requestId": "r1"}), ("Fetch.disable", {}), ("Network.disable", {})])

    def test_rewrite_to_url_and_body_sends_the_body_base64(self):
        bodies = iter([("https://api.test/sync", '[{"op": "добавить"}]'), ("https://api.test/sync?v=2", '[]'), "https://api.test/sync"])
        _, sent, _ = run([paused("f1", "https://api.test/sync"), paused("f2", "https://api.test/sync"),
                          paused("f3", "https://api.test/sync")], {"x": ["/x"]}, timeout=5, rewrite=("*sync*", lambda u: next(bodies)))
        self.assertEqual([p for m, p in sent if m == "Fetch.continueRequest"], [
            {"requestId": "f1", "postData": base64.b64encode('[{"op": "добавить"}]'.encode()).decode()},
            {"requestId": "f2", "url": "https://api.test/sync?v=2", "postData": "W10="},
            {"requestId": "f3"}])

    def test_request_paused_without_rewrite_goes_on_as_it_was(self):
        got, sent, _ = run([paused("f1", "https://api.test/x"), response("r1", "https://api.test/x"), finished("r1"), body("2")],
                           {"x": ["/x"]})
        self.assertEqual(got, {"x": 2})
        self.assertEqual(sent[2], ("Fetch.continueRequest", {"requestId": "f1"}))
        self.assertEqual(sent[-1], ("Network.disable", {}))
        self.assertNotIn(("Fetch.disable", {}), sent)

    def test_request_paused_while_a_body_is_read_goes_on_too(self):
        got, sent, _ = run([response("r1", "https://api.test/x"), finished("r1"), paused("f1", "https://api.test/s"), body("3")],
                           {"x": ["/x"]}, rewrite=("*/s*", lambda u: u + "?p=2"))
        self.assertEqual(got, {"x": 3})
        self.assertEqual(sent[3:6], [("Network.getResponseBody", {"requestId": "r1"}),
                                     ("Fetch.continueRequest", {"requestId": "f1", "url": "https://api.test/s?p=2"}),
                                     ("Fetch.disable", {})])

    def test_body_that_is_not_json_leaves_the_name_missing(self):
        got, sent, _ = run([response("r1", "https://api.test/x"), finished("r1"), body("<html>"),
                            response("r2", "https://api.test/y"), finished("r2"), body(error={"message": "No resource"})],
                           {"x": ["/x"], "y": ["/y"]}, timeout=10)
        self.assertEqual(got, {})
        self.assertEqual(sent[-1], ("Network.disable", {}))

    def test_timeout_leaves_names_missing(self):
        got, sent, _ = run([response("r1", "https://api.test/x"), finished("r1"), body("1")], {"x": ["/x"], "y": ["/y"]}, timeout=8)
        self.assertEqual(got, {"x": 1})
        self.assertEqual(sent[-1], ("Network.disable", {}))

    def test_messages_that_arrive_while_a_body_is_read_are_handled_too(self):
        got, _, _ = run([response("r1", "https://api.test/x"), finished("r1"), response("r2", "https://api.test/y"), body("1"),
                         finished("r2"), body("2")], {"x": ["/x"], "y": ["/y"]}, timeout=10)
        self.assertEqual(got, {"x": 1, "y": 2})

    def test_a_body_that_cannot_be_read_frees_its_name_for_the_next_match(self):
        # Золотое яблоко: the page goes on to a category before its search answer is read; the category's answer has the data
        got, _, _ = run([response("r1", "https://api.test/search"), finished("r1"), body(error={"message": "No resource"}),
                         response("r2", "https://api.test/cards"), finished("r2"), body('{"cards": 1}')],
                        {"s": ["re:/(search|cards)"]}, timeout=10)
        self.assertEqual(got, {"s": {"cards": 1}})

    def test_body_that_never_comes_leaves_the_name_missing(self):
        got, sent, _ = run([response("r1", "https://api.test/x"), finished("r1")], {"x": ["/x"]}, rewrite=("*", str))
        self.assertEqual(got, {})
        self.assertEqual(sent[-2:], [("Fetch.disable", {}), ("Network.disable", {})])

    def test_an_optional_name_gets_a_short_wait_once_the_others_are_in(self):
        script, patterns = [response("r1", "https://api.test/x"), finished("r1"), body("1")], {"x": ["/x"], "seller": ["/s"]}
        got, _, clock = run(list(script), patterns, optional=("seller",))
        _, _, waited = run(list(script), patterns)
        self.assertEqual(got, {"x": 1})
        self.assertLess(clock.time.call_count, 12)          # the clock moves a second per reading: ~3 s, not 20
        self.assertGreaterEqual(waited.time.call_count, 20)

    @patch.object(C, "OPTIONAL_WAIT", 10)      # the fake clock moves a second per reading
    def test_an_optional_name_that_comes_in_time_is_read(self):
        got, _, _ = run([response("r1", "https://api.test/x"), finished("r1"), body("1"), response("r2", "https://api.test/s"),
                         finished("r2"), body("2")], {"x": ["/x"], "seller": ["/s"]}, optional=("seller",))
        self.assertEqual(got, {"x": 1, "seller": 2})

if __name__ == "__main__":
    unittest.main()
