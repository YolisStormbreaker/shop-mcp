"""Minimal Chrome DevTools client for the shop-chrome instance on 127.0.0.1:9222.

One reusable tab per site (matched by domain), so the browser does not pile up tabs.
"""
import fcntl
import itertools
import json
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

from shoplog import log

CDP = "http://127.0.0.1:9222"
_ids = itertools.count(1)
_last_nav: dict[str, float] = {}
MIN_GAP = 4.0  # seconds between page loads on one site, keeps us under anti-bot radar
LOCKS = Path(__file__).parent / "cache"
LOCK_WAIT = 300  # s; a first full ozon_orders pass holds the tab ~3 min


def _http(path: str, method: str = "GET"):
    req = urllib.request.Request(CDP + path, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _lock_site(domain: str):
    """Hold the site's tab for one call.  Two calls in one tab break each other: one navigates
    away while the other reads the page (2026-09-30).  The stdio servers of several sessions,
    the HTTP server and watch.py are separate processes, hence a file lock."""
    LOCKS.mkdir(exist_ok=True)
    f = open(LOCKS / f"tab-{domain}.lock", "w")
    deadline = time.time() + LOCK_WAIT
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except BlockingIOError:
            if time.time() > deadline:
                f.close()
                raise RuntimeError(f"вкладка {domain} занята другим вызовом дольше {LOCK_WAIT} с")
            time.sleep(0.2)


class Tab:
    def __init__(self, ws_url: str, lock=None):
        self.lock = lock
        try:
            self.ws = connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=10)
        except Exception:
            self.close()
            raise

    def close(self):
        if getattr(self, "ws", None):
            self.ws.close()
            self.ws = None
        if self.lock:
            self.lock.close()           # releases the flock
            self.lock = None

    __del__ = close                     # a tab dropped by an exception still frees the site

    def call(self, method: str, timeout: float = 60, **params):
        mid = next(_ids)
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        deadline = time.time() + timeout
        while True:
            msg = json.loads(self.ws.recv(timeout=max(0.1, deadline - time.time())))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr: str, timeout: float = 60):
        """Evaluate JS (may return a Promise) and return the JSON value."""
        r = self.call("Runtime.evaluate", timeout=timeout, expression=expr,
                      awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError(d.get("exception", {}).get("description") or d.get("text"))
        return r["result"].get("value")

    def heal(self, timeout: float = 30):
        """Reload the page if a debugging probe is left in it.  Such a probe records requests
        into window.__req and rejects POSTs, so a review is not sent while its form is studied.
        On 2026-10-02 one stayed in the Ozon tab and every POST failed with «blocked by probe».
        Not a check for native fetch(): AliExpress and Avito wrap fetch() themselves."""
        try:
            if not self.js("'__req' in window || String(window.fetch).includes('blocked by probe')", timeout=5):
                return
        except Exception:
            return                      # blank or mid-navigation page: nothing to heal
        log.warning("debugging probe left in %s, reloading the tab", self.js("location.href", timeout=5))
        self.call("Page.reload")
        deadline = time.time() + timeout
        time.sleep(1.5)
        while time.time() < deadline:
            try:
                if self.js("document.readyState", timeout=5) == "complete":
                    return
            except Exception:
                pass
            time.sleep(0.7)

    def click(self, selector: str) -> bool:
        """Real mouse click (isTrusted) on the element; some sites ignore el.click()."""
        pos = self.js(f"""(() => {{
          const e = document.querySelector({json.dumps(selector)});
          if (!e) return null;
          e.scrollIntoView({{block: 'center'}});
          const b = e.getBoundingClientRect();
          return [b.x + b.width / 2, b.y + b.height / 2];
        }})()""")
        if not pos:
            return False
        time.sleep(0.4)
        for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", type=typ, x=pos[0], y=pos[1], button="left", clickCount=1)
        return True

    def goto(self, url: str, site: str, wait_js: str | None = None, timeout: float = 30):
        gap = MIN_GAP - (time.time() - _last_nav.get(site, 0))
        if gap > 0:
            time.sleep(gap)
        _last_nav[site] = time.time()
        self.call("Page.navigate", url=url)
        deadline = time.time() + timeout
        time.sleep(1.5)
        while time.time() < deadline:
            try:
                ready = self.js("document.readyState", timeout=5)
                if ready in ("interactive", "complete") and (not wait_js or self.js(wait_js, timeout=5)):
                    return
            except Exception:
                pass  # page is swapping documents mid-navigation
            time.sleep(0.7)
        # fall through: caller extracts whatever is there and reports emptiness


def tab_for(domain: str) -> Tab:
    """The site's tab, held for this caller until tab.close()."""
    lock = _lock_site(domain)
    try:
        tab = _find_tab(domain, lock)
    except BaseException:
        lock.close()
        raise
    tab.heal()
    return tab


def _find_tab(domain: str, lock) -> Tab:
    try:
        tabs = _http("/json/list")
    except OSError as e:
        raise RuntimeError("Chrome на макмини не отвечает на 127.0.0.1:9222 "
                           "(launchctl kickstart -k gui/501/local.shop-chrome)") from e
    pages = [t for t in tabs if t.get("type") == "page"]
    for t in pages:
        if domain in t.get("url", ""):
            return Tab(t["webSocketDebuggerUrl"], lock)
    blank = [t for t in pages if t.get("url", "").startswith(("about:blank", "chrome://newtab"))]
    t = blank[0] if blank else _http("/json/new?about:blank", method="PUT")
    return Tab(t["webSocketDebuggerUrl"], lock)
