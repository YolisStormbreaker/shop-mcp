"""Avito watch: new Orange Pi Zero3 boards under a total price, reserved ones skipped.

For the CNC pendant (machines repo, cnc/two-trees/pendant): its Zero3 burnt out on 2026-10-11, the
Armbian card from it boots on any Zero3, so any RAM size will do; cheapest first.
Run by launchd on the Mac mini (local.shop-watch, 10:07 and 20:07): `uv run --script watch.py`.
Sends new listings (price + cheapest delivery <= MAX_TOTAL) to Telegram (see tg.py) and remembers
them in logs/watch_seen.json, so each listing is reported once. --print prints instead of sending.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets>=13"]
# ///
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import avito  # noqa: E402
from cdp import tab_for  # noqa: E402
from shoplog import log  # noqa: E402
import html  # noqa: E402
import tg  # noqa: E402

MAX_TOTAL = 5000
QUERIES = ["orange pi zero 3", "orange pi zero3"]
SEEN = Path(__file__).parent / "logs" / "watch_seen.json"

# "Zero 3", "Zero3", and sellers who write "Orange Pi 3 Zero".
BOARD = re.compile(r"zero\s*-?\s*3(?!\d)|\b3\s*zero", re.I)
BRAND = re.compile(r"orange|оранж|\bopi", re.I)
# Other Orange Pi boards that match the words above.
OTHER = re.compile(r"zero\s*-?\s*2|2\s*w\b|\blts\b|zero\s*-?\s*3\s*w|\b3\s*b\b|h2\+|\bh3\b|512\s*mb|banana|raspberry", re.I)
# Accessories. A board "в корпусе" is fine, a case on its own starts with the word.
SKIP = re.compile(r"^\W*(корпус|кейс|case|акрилов|металлическ|прозрачн)|\bдля\b|блок питания|бп\b|кулер|радиатор|вентилятор|плата расширения|expansion|"
                  r"камер|дисплей|экран|монитор|кабель|адаптер|переходник|без платы", re.I)
RAM = re.compile(r"(1(?:[.,]5)?|2|4)\s*(?:gb|гб|g\b)", re.I)


def ram(title):
    m = RAM.search(title)
    return f"{m.group(1).replace(',', '.')} ГБ" if m else "память не указана"


def wanted(title):
    return bool(BOARD.search(title)) and bool(BRAND.search(title)) and not OTHER.search(title) \
        and not SKIP.search(title)


def scan(tab, query):
    url = avito.search_url(query, "all", 2000, MAX_TOTAL, "date", 1, True)
    tab.goto(url, "avito", wait_js="document.querySelector('[data-marker=\"item\"], [data-marker=\"page-title/count\"]')")
    r = tab.js(avito.LIST_JS)
    if r["blocked"]:
        raise RuntimeError(f"Авито показал блокировку или капчу: {r['url']}")
    return [x for x in r["items"] if x["url"] and wanted(x["title"])]


def main():
    seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()
    tab = tab_for("avito.ru")
    found, new = {}, []
    try:
        for q in QUERIES:
            for x in scan(tab, q):
                found.setdefault(x["id"], x)
        fresh = [x for i, x in found.items() if i not in seen]
        ship = avito._shipping(tab, [urllib.parse.urlparse(x["url"]).path for x in fresh])
    finally:
        tab.close()
    for x, s in zip(fresh, ship):
        if (s or {}).get("blocked"):
            break
        if (s or {}).get("reserved"):
            continue  # not marked seen: may come back if the deal falls through
        if not s or s.get("error"):
            continue  # the lookup failed: not marked seen, asked again next run
        seen.add(x["id"])
        _, cheapest = avito._ship_cell(s)
        price = int(x["price"]) if str(x["price"]).isdigit() else None
        if price is None or cheapest is None or price + cheapest > MAX_TOTAL:
            continue
        warn = "\n⚠️ по описанию не работает или продаётся как есть" if s.get("broken") else ""
        new.append((1 if warn else 0, price + cheapest,
                    f"<b>{price + cheapest} ₽</b> ({price} + доставка {cheapest}) · "
                    f"<a href=\"{x['url']}\">{html.escape(x['title'])}</a> · {x['city']} · {ram(x['title'])}{warn}"))
    SEEN.parent.mkdir(exist_ok=True)
    SEEN.write_text(json.dumps(sorted(seen)))
    log.info("watch: %d matching, %d not seen before, %d new under %d ₽", len(found), len(fresh), len(new), MAX_TOTAL)
    # Working boards first, then cheapest.
    return [t for _, _, t in sorted(new, key=lambda n: (n[0], n[1]))]


def notify(text):
    if "--print" in sys.argv:
        print(text)
    else:
        tg.send(text)


if __name__ == "__main__":
    if "--print" not in sys.argv and not tg.CONF.exists():
        log.warning("watch: no telegram.json, skipped")  # else listings would be marked seen unseen
        sys.exit("telegram.json missing, see tg.py")
    try:
        new = main()
    except Exception as e:
        log.exception("watch failed")
        notify(f"⚠️ Мониторинг Авито упал: {html.escape(str(e))[:500]}")
        raise
    if new:
        notify(f"Новые Orange Pi Zero3 на Авито до {MAX_TOTAL} ₽ с доставкой, без резерва, для пульта фрезера. "
               "Сверху дешёвые:\n\n" + "\n\n".join(new))
