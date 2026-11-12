"""What a shop page asks its site for: one page load by a slot of the shared budget (pace), every XHR/fetch answer
kept with its address, and the page's state objects (__NEXT_DATA__ and the like). For learning a new site without
a burst of requests: read cache/netlog/<site>/last.json as many times as needed instead of loading the page again.
Run: .venv/bin/python netlog.py <site> <page url> [seconds]"""
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import cdp
import pace
from capture import _recv, _send

CACHE = Path(__file__).parent / "cache" / "netlog"
# window globals the page's framework fills with its data (Next.js, Nuxt, Redux-style initial states)
STATE_JS = r"""(() => { const out = {};
  for (const k of Object.keys(window)) if (/^__|INITIAL|STATE|DATA/.test(k) && !/^__(REACT|VUE)_DEVTOOLS/.test(k)) {
    try { const v = window[k]; if (v && typeof v === 'object') out[k] = JSON.parse(JSON.stringify(v)) } catch (e) {} }
  const n = document.getElementById('__NEXT_DATA__'); if (n) try { out.__NEXT_DATA__ = JSON.parse(n.textContent) } catch (e) {}
  return out })()"""


def record(site, url, wait=15):
    """{url, responses: [{url, status, json, text when not JSON}], state} of one load of url; also saved to
    cache/netlog/<site>/last.json. A block page stops the site through pace like any page load."""
    tab = cdp.tab_for(re.sub(r"^www\.", "", urllib.parse.urlsplit(url).hostname or ""))
    try:
        pace.acquire(site, "page")
        ws = tab.ws
        _send(ws, "Network.enable")
        _send(ws, "Page.navigate", url=url)
        seen, asked, bodies = {}, {}, {}
        deadline = time.time() + wait
        while time.time() < deadline:
            _on(ws, _recv(ws), seen, asked, bodies)
        _send(ws, "Network.disable")
        pace.check_page(site, tab._probe())
        got = {"url": url, "responses": [_answer(*seen[rid], bodies[rid]) for rid in seen if rid in bodies],
               "state": tab.js(STATE_JS, timeout=30) or {}}
    finally:
        tab.close()
    (CACHE / site).mkdir(parents=True, exist_ok=True)
    (CACHE / site / "last.json").write_text(json.dumps(got, ensure_ascii=False, indent=1))
    return got


def _on(ws, m, seen, asked, bodies):
    p = m.get("params", {})
    if m.get("method") == "Network.responseReceived" and p.get("type") in ("XHR", "Fetch"):
        seen[p["requestId"]] = (p["response"]["url"], p["response"]["status"])
    elif m.get("method") == "Network.loadingFinished" and p.get("requestId") in seen:
        asked[_send(ws, "Network.getResponseBody", requestId=p["requestId"])] = p["requestId"]
    elif m.get("id") in asked:
        bodies[asked.pop(m["id"])] = (m.get("result") or {}).get("body") or ""


def _answer(url, status, text):
    try:
        return {"url": url, "status": status, "json": json.loads(text)}
    except ValueError:
        return {"url": url, "status": status, "json": None, "text": text[:2000]}


def _shape(v):
    return "{" + ", ".join(sorted(v)) + "}" if isinstance(v, dict) else f"[{len(v)}]" if isinstance(v, list) else type(v).__name__


def summary(got):
    lines = [f"{got['url']}: {len(got['responses'])} ответа"]
    for r in got["responses"]:
        what = _shape(r["json"]) if r["json"] is not None else "не JSON: " + " ".join(r["text"].split())[:80]
        lines.append(f"{r['status']} {r['url'][:160]} — {what}")
    lines += [f"window.{k} — {_shape(v)}" for k, v in got["state"].items()]
    return "\n".join(lines)


def main(argv):
    if len(argv) not in (2, 3) or argv[0] not in pace.POLICY:      # a typo in the site would walk past the real site's stop
        print(__doc__.strip().splitlines()[-1])
        return 2
    try:
        got = record(argv[0], argv[1], float(argv[2]) if len(argv) > 2 else 15)
    except pace.Refused as e:
        print(e)
        return 1
    print(summary(got))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
