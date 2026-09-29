"""Take the JSON a site's own page fetched, instead of calling its API ourselves.

For sites that sign API calls with tokens and device headers (Wildberries) or send the user's
city and delivery zones in the request body (Gold Apple): the page builds the request, we read
the response through CDP Network.getResponseBody.
"""
import json
import time

import cdp


def capture(tab, site, url, patterns, timeout=20):
    """Navigate to url; return {name: JSON} of the first response whose URL contains every part of patterns[name].

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

    send("Network.enable")
    send("Page.navigate", url=url)
    pending, out, deadline = {}, {}, time.time() + timeout
    try:
        while time.time() < deadline and len(out) < len(patterns):
            try:
                m = json.loads(ws.recv(timeout=0.5))
            except TimeoutError:
                continue
            p = m.get("params", {})
            if m.get("method") == "Network.responseReceived":
                for name, parts in patterns.items():
                    if name not in out and name not in pending.values() and all(s in p["response"]["url"] for s in parts):
                        pending[p["requestId"]] = name
            elif m.get("method") == "Network.loadingFinished" and p.get("requestId") in pending:
                i = send("Network.getResponseBody", requestId=p["requestId"])
                while True:
                    r = json.loads(ws.recv(timeout=10))
                    if r.get("id") == i:
                        try:
                            out[pending[p["requestId"]]] = json.loads(r["result"]["body"])
                        except (KeyError, ValueError):
                            pass
                        break
        return out
    finally:
        send("Network.disable")
