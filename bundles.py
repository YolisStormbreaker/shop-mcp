"""Search a shop site's own JavaScript — how its page calls its API (an endpoint, a request's body) — paced and cached.

Reading a site's bundles is how this project learns a site's own requests. Fetching a hundred scripts in a burst, and
again for every question, is part of what got the user's IP banned (Перекрёсток, 2026-11-08). Here one page load takes
the site's slot of the shared budget (pace) and the scripts the page parsed are read from its debugger, with no request
of their own (a fetch also failed on CDNs that refuse it by CORS: М.Видео, DNS). Copies go to cache/bundles/<site>/.
Run: .venv/bin/python bundles.py <site> <page url> <regex> [context]"""
import hashlib
import re
import sys
import urllib.parse
from pathlib import Path

import cdp
import pace
from capture import _recv, _send

CACHE = Path(__file__).parent / "cache" / "bundles"


def scripts(site, url):
    """{script url: its text} for every script the page at url parsed, read from the page's debugger: one page load
    by the site's slot and no request of its own (a CDN refuses a page's fetch by CORS; a fetch would cost a slot)."""
    tab = cdp.tab_for(re.sub(r"^www\.", "", urllib.parse.urlsplit(url).hostname or ""))
    try:
        tab.goto(url, site, wait_js="document.readyState === 'complete'")
        texts = {name: tab.call("Debugger.getScriptSource", scriptId=sid)["scriptSource"] for name, sid in _parsed(tab).items()}
    finally:
        tab.close()
    for name, text in texts.items():
        _keep(site, name, text)
    return texts


def _parsed(tab):
    """{url: scriptId} of the page's scripts with an address: Debugger.enable reports every script parsed so far."""
    ids, quiet = {}, 0
    _send(tab.ws, "Debugger.enable")
    while quiet < 2:                                   # two silent half-seconds: the report is over
        m = _recv(tab.ws)
        quiet = 0 if m else quiet + 1
        p = m.get("params", {})
        if m.get("method") == "Debugger.scriptParsed" and p.get("url", "").startswith("http"):
            ids[p["url"]] = p["scriptId"]
    return ids


def _keep(site, name, text):
    """A copy on disk, cache/bundles/<site>/, for reading again with other tools."""
    f = CACHE / site / (hashlib.sha1(name.encode()).hexdigest()[:16] + ".js")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)


def search(texts, regex, context=160):
    """[(script url, the hit with context chars on each side)] for every match of regex."""
    return [(name, text[max(0, m.start() - context):m.end() + context])
            for name, text in texts.items() for m in re.finditer(regex, text)]


def main(argv):
    if len(argv) not in (3, 4) or argv[0] not in pace.POLICY:     # a typo in the site would walk past the real site's stop
        print(__doc__.strip().splitlines()[-1])
        return 2
    site, url, regex, *ctx = argv
    try:
        texts = scripts(site, url)
    except pace.Refused as e:
        print(e)
        return 1
    hits = search(texts, regex, int(ctx[0]) if ctx else 160)
    print(f"скриптов: {len(texts)}, совпадений: {len(hits)}")
    for name, snippet in hits[:40]:
        print(f"- {name.split('/')[-1][:50]}: {' '.join(snippet.split())}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
