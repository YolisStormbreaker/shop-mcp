"""Take the JSON a site's own page fetched, instead of calling its API ourselves.

For sites that sign API calls with tokens and device headers (Wildberries) or send the user's
city and delivery zones in the request body (Gold Apple): the page builds the request, we read
the response through CDP Network.getResponseBody.
"""
import base64
import json
import re
import time

import cdp


def capture(tab, site, url, patterns, timeout=20, rewrite=None, js=None, optional=()):
    """Navigate to url; return {name: JSON} of the first response whose URL contains every part of patterns[name]
    (a part "re:<regex>" is searched as a regular expression instead).

    rewrite=(glob, fn): the page's own requests matching glob are sent to fn(url) instead, with the
    browser's own headers (CDP Fetch); fn may return (url, body) to replace the body too. Wildberries
    loads page N only on scroll, which a background tab never does, so its page-1 request is sent as
    page N; its cart sync, sent on every page load, carries our cart change. Only requestId and url
    are read from the paused request: its headers carry the user's token.
    Names whose response did not arrive within timeout are missing from the result.
    js: run this in the page instead of navigating to url — e.g. the site's own router, so a single-page
    app fetches the next screen's data without a full page load (Samokat's bot check counts page loads).
    optional: names the page may never ask for (Wildberries' seller card for its own goods); once every other
    name is in, they get OPTIONAL_WAIT seconds more, not the rest of timeout.
    """
    _wait_turn(site)
    ws = tab.ws
    _send(ws, "Network.enable")
    if rewrite:
        tab.call("Fetch.enable", patterns=[{"urlPattern": rewrite[0], "requestStage": "Request"}])  # before navigate
    if js:
        _send(ws, "Runtime.evaluate", expression=js)
    else:
        _send(ws, "Page.navigate", url=url)
    pending, out, deadline = {}, {}, time.time() + timeout
    try:
        while time.time() < deadline and len(out) < len(patterns):
            _on(ws, _recv(ws), patterns, rewrite, pending, out)
            if optional and set(patterns) - set(optional) <= set(out):
                deadline = min(deadline, time.time() + OPTIONAL_WAIT)
        return out
    finally:
        if rewrite:
            _send(ws, "Fetch.disable")
        _send(ws, "Network.disable")


OPTIONAL_WAIT = 3


def _wait_turn(site):
    gap = cdp.MIN_GAP - (time.time() - cdp._last_nav.get(site, 0))
    if gap > 0:
        time.sleep(gap)
    cdp._last_nav[site] = time.time()


def _send(ws, method, **params):
    i = next(cdp._ids)
    ws.send(json.dumps({"id": i, "method": method, "params": params}))
    return i


def _recv(ws):
    try:
        return json.loads(ws.recv(timeout=0.5))
    except TimeoutError:
        return {}


def _on(ws, m, patterns, rewrite, pending, out):
    """One message from the browser: a paused request goes on, a matching response is claimed, the body of a
    claimed one that finished loading is asked for and read into out. pending maps the requestId of a claimed
    response, then the id of our Network.getResponseBody command, to its name."""
    p = m.get("params", {})
    if m.get("method") == "Fetch.requestPaused":
        _send(ws, "Fetch.continueRequest", **_continue(p, rewrite))
    elif m.get("method") == "Network.responseReceived":
        if name := _claim(p["response"]["url"], patterns, set(out) | set(pending.values())):
            pending[p["requestId"]] = name
    elif m.get("method") == "Network.loadingFinished" and p.get("requestId") in pending:
        pending[_send(ws, "Network.getResponseBody", requestId=p["requestId"])] = pending[p["requestId"]]
    elif m.get("id") in pending:
        _read(m, pending, out)


def _read(m, pending, out):
    """Our getResponseBody's answer into out.  A body that cannot be read (the page had moved on to another one,
    or it is not JSON) frees its name, so the next response that matches can still bring it."""
    name = pending.pop(m["id"])
    try:
        out[name] = json.loads(m["result"]["body"])
    except (KeyError, ValueError):
        for k in [k for k, v in pending.items() if v == name]:
            del pending[k]


def _matches(url, parts):
    return all(re.search(s[3:], url) if s.startswith("re:") else s in url for s in parts)


def _claim(url, patterns, taken):
    """The name a response at url is read for: of the names not taken whose parts it all contains, the last."""
    return next((name for name in reversed(patterns) if name not in taken and _matches(url, patterns[name])), None)


def _continue(p, rewrite):
    """Fetch.continueRequest parameters for a paused request. Every paused request must be continued,
    or the page hangs."""
    if not rewrite:  # paused by an earlier call just before its Fetch.disable took effect
        return {"requestId": p["requestId"]}
    old = p["request"]["url"]
    new, body = rewrite[1](old), None
    if isinstance(new, tuple):
        new, body = new
    change = {"url": new} if new != old else {}
    if body is not None:
        change["postData"] = base64.b64encode(body.encode()).decode()
    return {"requestId": p["requestId"], **change}
