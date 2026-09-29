"""Take the JSON a site's own page fetched, instead of calling its API ourselves.

For sites that sign API calls with tokens and device headers (Wildberries) or send the user's
city and delivery zones in the request body (Gold Apple): the page builds the request, we read
the response through CDP Network.getResponseBody.
"""
import json
import time

import cdp


def capture(tab, site, url, patterns, timeout=20, rewrite=None):
    """Navigate to url; return {name: JSON} of the first response whose URL contains every part of patterns[name].

    rewrite=(glob, fn): the page's own requests matching glob are sent to fn(url) instead, with the
    browser's own headers (CDP Fetch). Wildberries loads page N only on scroll, which a background
    tab never does, so its page-1 request is sent as page N. Only requestId and url are read from
    the paused request: its headers carry the user's token.
    Names whose response did not arrive within timeout are missing from the result.
    """
    gap = cdp.MIN_GAP - (time.time() - cdp._last_nav.get(site, 0))
    if gap > 0:
        time.sleep(gap)
    cdp._last_nav[site] = time.time()
    ws = tab.ws

    def send(method, **params):
        i = next(cdp._ids)
        ws.send(json.dumps({"id": i, "method": method, "params": params}))
        return i

    def resume(p):
        """Every paused request must be continued, or the page hangs."""
        old = p["request"]["url"]
        new = rewrite[1](old)
        send("Fetch.continueRequest", requestId=p["requestId"], **({"url": new} if new != old else {}))

    send("Network.enable")
    if rewrite:
        tab.call("Fetch.enable", patterns=[{"urlPattern": rewrite[0], "requestStage": "Request"}])  # before navigate
    send("Page.navigate", url=url)
    pending, out, deadline = {}, {}, time.time() + timeout
    try:
        while time.time() < deadline and len(out) < len(patterns):
            try:
                m = json.loads(ws.recv(timeout=0.5))
            except TimeoutError:
                continue
            p = m.get("params", {})
            if m.get("method") == "Fetch.requestPaused":
                resume(p)
            elif m.get("method") == "Network.responseReceived":
                for name, parts in patterns.items():
                    if name not in out and name not in pending.values() and all(s in p["response"]["url"] for s in parts):
                        pending[p["requestId"]] = name
            elif m.get("method") == "Network.loadingFinished" and p.get("requestId") in pending:
                i = send("Network.getResponseBody", requestId=p["requestId"])
                while True:
                    r = json.loads(ws.recv(timeout=10))
                    if r.get("method") == "Fetch.requestPaused":
                        resume(r["params"])
                    elif r.get("id") == i:
                        try:
                            out[pending[p["requestId"]]] = json.loads(r["result"]["body"])
                        except (KeyError, ValueError):
                            pass
                        break
        return out
    finally:
        if rewrite:
            send("Fetch.disable")
        send("Network.disable")
