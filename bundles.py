"""Search a shop site's own JavaScript — how its page calls its API (an endpoint, a request's body) — paced and cached.

Reading a site's bundles is how this project learns a site's own requests. Fetching a hundred scripts in a burst, and
again for every question, is part of what got the user's IP banned (Перекрёсток, 2026-11-08). Here each script is
fetched once, each by a slot of the shared budget (pace), and kept in cache/bundles/<site>/; every later search reads
the copies. A refusal keeps what was fetched: run it again after the time it names.
Run: .venv/bin/python bundles.py <site> <page url> <regex> [context]"""
import hashlib
import json
import re
import sys
import urllib.parse
from pathlib import Path

import cdp
import pace

CACHE = Path(__file__).parent / "cache" / "bundles"
SCRIPTS_JS = "[...new Set(performance.getEntriesByType('resource').map(e => e.name).filter(n => /\\.js(\\?|$)/.test(n)))]"


def scripts(site, url):
    """{script url: its text} for every script the page at url loaded: from the cache, the missing ones fetched."""
    tab = cdp.tab_for(re.sub(r"^www\.", "", urllib.parse.urlsplit(url).hostname or ""))
    try:
        tab.goto(url, site, wait_js="document.readyState === 'complete'")
        return {name: _text(tab, site, name) for name in tab.js(SCRIPTS_JS) or []}
    finally:
        tab.close()


def _text(tab, site, name):
    f = CACHE / site / (hashlib.sha1(name.encode()).hexdigest()[:16] + ".js")
    if not f.exists():
        pace.acquire(site, "api")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(tab.js(f"fetch({json.dumps(name)}, {{credentials: 'include'}}).then(r => r.text())", timeout=60) or "")
    return f.read_text()


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
