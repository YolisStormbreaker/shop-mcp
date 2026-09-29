"""Order history on Ozon and AliExpress, searchable by product name.

Neither site puts product names in its order list: Ozon gives pictures and prices, AliExpress
gives item ids.  So every order costs one more request for its details.  Everything read is
kept in cache/orders.json:
- details of finished orders - they do not change;
- details of orders on their way, for a day - their status comes from the list, which is fresh;
- the order lists themselves.  Orders only join the top of a list, so a saved list is refreshed
  from the top until a page with nothing new.  An Ozon archive year that ended over a month
  before it was saved is not read again at all.  For LIVE_TTL after a refresh the saved lists
  are used as they are: a few searches in a row cost no requests.
Every request waits 1.5 s after the previous one (anti-bot), so the number of requests is the time.
"""
import fcntl
import json
import os
import re
import threading
import time
from pathlib import Path

import ali
import ozon
from shoplog import log

CACHE = Path(__file__).parent / "cache" / "orders.json"
LIVE_TTL = 600          # s: saved order lists are used without re-reading
ACTIVE_TTL = 86400      # s: details of an order on its way are re-read after this
_lock = threading.Lock()


def _load():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _put(updates):
    """Write entries to the cache file.  Re-read under a file lock first: the stdio server
    and the HTTP server are separate processes and may both be writing."""
    CACHE.parent.mkdir(exist_ok=True)
    with _lock, open(CACHE.with_suffix(".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        c = _load()
        c.update(updates)
        tmp = CACHE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(c, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(CACHE)


def _alts(query):
    """«usb хаб | hub» -> [["usb", "хаб"], ["hub"]]: an order matches if it has every word
    of any one alternative.  No query matches everything."""
    alts = [[w for w in q.lower().split() if w] for q in (query or "").split("|")]
    return [a for a in alts if a] or [[]]


def _match(order, alts):
    text = " ".join(p["title"] + " " + p.get("variant", "") for p in order["products"]).lower()
    return any(all(w in text for w in words) for words in alts)


def _stale(o, active):
    """Details must be (re)read: never read, or read while the order was on its way and
    either it has finished since or the copy is older than ACTIVE_TTL."""
    return o is None or "at" in o and (not active or time.time() - o["at"] > ACTIVE_TTL)


def _walk(pages, known=None):
    """A whole order list, newest first, from an iterator of pages of (id, ...) entries.
    With `known` - the same list read earlier - stop at the first page with no new ids and
    take the rest from `known`."""
    ids = {x[0] for x in known or []}
    out = []
    for page in pages:
        out += page
        if known and all(x[0] in ids for x in page):
            have = {x[0] for x in out}
            return out + [x for x in known if x[0] not in have]
    return out


def _format(site, rows, scanned, capped, query):
    head = f"{site}: заказы" + (f" с «{query}» в названии" if query else "") + \
           f" — найдено {len(rows)}, просмотрено заказов {scanned}"
    if capped:
        head += (" (достиг предела новых загрузок за вызов; просмотренные закэшированы — "
                 "повтори тот же вызов, чтобы искать дальше)")
    lines = [head, "заказ\tдата / статус\tсумма\tтовар\tвариант\tцена\tссылка"]
    for o in rows:
        for p in o["products"]:
            lines.append(f"{o['id']}\t{o['when']}\t{o['total']}\t{p['title'][:110]}\t{p.get('variant', '')[:50]}"
                         f"\t{p.get('price', '')}\t{p.get('url', '')}")
    return "\n".join(lines) if rows else head + "\n(ничего)"


# ------------------------------------------------------------------------------ Ozon
def _ozon_pages(tab, url):
    """Yield pages of (order id, status) from one tab of the order list, following its paginator."""
    for _ in range(200):
        page = ozon._page(tab, url)
        yield [x for w in ozon._widgets(page, "orderList")
               for x in map(_ozon_tile, w.get("ordersV2", [])) if x[0]]
        # page 1 names its next page in a paginator widget (next to one for recommendations);
        # every later page names it at the top level of the response
        nxt = [w.get("nextPage") for w in ozon._widgets(page, "paginator")
               if (w.get("layoutContainer") or "").startswith("order-list") and w.get("nextPage")]
        nxt = nxt[0] if nxt else page.get("nextPage")
        if not nxt or "order" not in nxt:
            return
        url = nxt


def _ozon_years(tab):
    page = ozon._page(tab, "/my/orderlist?selectedTab=archive")
    years = []
    for f in ozon._widgets(page, "orderFilters"):
        for b in f.get("tagButtons", []):
            if re.fullmatch(r"\d{4}", b.get("text", "")):
                years.append(int(b["text"]))
    return sorted(set(years), reverse=True)


def _ozon_tile(t):
    link = (t.get("leftBlock", {}).get("textIcon", {}).get("common", {}).get("action", {}).get("link", "")
            or json.dumps(t))
    m = re.search(r"order=([\d-]+)", link)
    status = t.get("leftBlock", {}).get("textIcon", {}).get("text", {}).get("text", "")
    return (m.group(1) if m else None), status


def _ozon_lists(tab, cache, year=None):
    """[(tag, [(order id, status)])]: current orders, then the archive by year, newest first."""
    now = time.time()
    live = cache.get("ozon:live") or {}
    fresh = now - live.get("at", 0) < LIVE_TTL
    updates = {}
    if not fresh:
        live = {"at": now, "years": _ozon_years(tab), "active": _walk(_ozon_pages(tab, "/my/orderlist"))}
        updates["ozon:live"] = live
    lists = [("active", live["active"])]
    for y in [year] if year else live["years"]:
        key = f"ozon:list:{y}"
        saved = cache.get(key)
        # orders of late December may reach the archive in January
        final = saved and saved["at"] > time.mktime((y + 1, 2, 1, 0, 0, 0, 0, 0, -1))
        if saved and (final or fresh):
            ids = saved["ids"]
        else:
            ids = _walk(_ozon_pages(tab, f"/my/orderlist?selectedTab=archive&selectedYear={y}"),
                        saved and saved["ids"])
            updates[key] = {"at": now, "ids": ids}
        lists.append((f"archive {y}", ids))
    if updates:
        _put(updates)
    return lists


def _ozon_details(tab, oid):
    d = ozon._page(tab, "/my/orderdetails/?order=" + oid)
    products = []
    for sw in ozon._widgets(d, "shipmentWidget"):
        for it in sw.get("items", []):
            for s in it.get("sellers", []):
                for p in s.get("products", []):
                    t = p.get("title", {})
                    link = t.get("common", {}).get("action", {}).get("link", "").split("?")[0]
                    products.append({
                        "title": t.get("name", {}).get("text", ""),
                        "variant": "; ".join(a.get("text", "") for a in p.get("attributes", [])),
                        "price": " ".join(x.get("text", "") for x in p.get("price", {}).get("price", [])
                                          if x.get("textStyle", "PRICE") == "PRICE").replace(" ", " "),
                        "url": ("https://www.ozon.ru" + link) if link else "",
                        "seller": s.get("name", {}).get("text", ""),
                    })
    total = ""
    for w in ozon._widgets(d, "orderDoneTotal") + ozon._widgets(d, "orderTotal"):
        total = w.get("total", {}).get("right", {}).get("price", {}).get("text", "") or total
    return products, total.replace(" ", " ")


def ozon_orders(query=None, year=None, limit=30, max_new=60):
    alts, cache = _alts(query), _load()
    tab = ozon._tab()
    rows, scanned, fetched, capped = [], 0, 0, False
    try:
        seen = set()
        for tag, ids in _ozon_lists(tab, cache, year):
            active = tag == "active"
            for oid, status in ids:
                if oid in seen:
                    continue
                seen.add(oid)
                key = f"ozon:{oid}"
                o = cache.get(key)
                if _stale(o, active):
                    if fetched >= max_new:
                        capped = True
                        break
                    products, total = _ozon_details(tab, oid)
                    fetched += 1
                    o = {"id": oid, "total": total, "products": products}
                    if active:
                        o["at"] = time.time()
                    _put({key: o})
                o = dict(o, when=status + ("" if active else f" ({tag.split()[-1]})"))
                scanned += 1
                if _match(o, alts):
                    rows.append(o)
                    if len(rows) >= limit:
                        break
            if capped or len(rows) >= limit:
                break
    finally:
        tab.close()
    log.info("ozon_orders %r: %d found, %d scanned, %d fetched", query, len(rows), scanned, fetched)
    return _format("Ozon", rows, scanned, capped, query)


# ------------------------------------------------------------------------------ AliExpress
ALI_LIST = "/aer-api/bx/orders/v3/web/orders-list"

# The order page is server-rendered: fetch its HTML and read it with DOMParser in the tab,
# so only the few fields come back over the wire, not 400 KB of page.
ALI_DETAIL_JS = """fetch(%s, {credentials: "include"}).then(r => r.text()).then(h => {
  const d = new DOMParser().parseFromString(h, "text/html");
  const body = d.body ? d.body.innerText || d.body.textContent : "";
  const date = ((h.match(/Заказ от (?:<!-- -->)?([^<"]{3,30})/) || [])[1] || "").trim();
  const products = [...d.querySelectorAll('[data-testid="productText"]')].map(a => {
    const box = a.parentElement;
    const texts = [...box.querySelectorAll("div")].map(x => x.textContent.trim()).filter(Boolean);
    const title = a.textContent.trim();
    const rest = texts.filter(t => t !== title && !title.includes(t));
    return {title, variant: rest.find(t => !/₽|шт\\./.test(t)) || "",
            price: rest.find(t => /₽/.test(t)) || "", url: (a.href || "").split("?")[0]};
  });
  return {date, products, n: h.length};
})"""


def _ali_detail(tab, oid):
    gap = 1.5 - (time.time() - ali._last_call)
    if gap > 0:
        time.sleep(gap)
    ali._last_call = time.time()                # the same pacing as ali._fetch
    return tab.js(ALI_DETAIL_JS % json.dumps(f"/order-list/{oid}"), timeout=60)


def _ali_pages(tab, tab_type):
    """Yield pages of (order id, status, total, item ids) from the active or archive list."""
    page = 1
    while True:
        r = ali._fetch(tab, ALI_LIST, {"tabType": tab_type, "page": page, "pageSize": 20}) or {}
        data = r.get("data") or {}
        yield [(od["orderId"],
                (od.get("statusInfo") or {}).get("title") or (od.get("tag") or {}).get("title", ""),
                od.get("totalPrice", "").replace(" ", " "),
                [p.get("itemId") for p in od.get("products") or []])
               for group in data.get("items") or [] for od in group.get("orders") or [] if od.get("orderId")]
        if not data.get("hasMore"):
            return
        page += 1


def _ali_lists(tab, cache):
    now = time.time()
    live = cache.get("ali:live") or {}
    saved = (cache.get("ali:list:archive") or {}).get("ids")
    if now - live.get("at", 0) < LIVE_TTL and saved is not None:
        return [("active", live["active"]), ("archive", saved)]
    active = _walk(_ali_pages(tab, "active"))
    archive = _walk(_ali_pages(tab, "archive"), saved)
    _put({"ali:live": {"at": now, "active": active}, "ali:list:archive": {"at": now, "ids": archive}})
    return [("active", active), ("archive", archive)]


def ali_orders(query=None, limit=30, max_new=60):
    alts, cache = _alts(query), _load()
    tab = ali._tab()
    rows, scanned, fetched, capped = [], 0, 0, False
    try:
        seen = set()
        for tab_type, ids in _ali_lists(tab, cache):
            active = tab_type == "active"
            for oid, status, total, items in ids:
                if oid in seen:
                    continue
                seen.add(oid)
                key = f"ali:{oid}"
                o = cache.get(key)
                if _stale(o, active):
                    if fetched >= max_new:
                        capped = True
                        break
                    det = _ali_detail(tab, oid) or {}
                    fetched += 1
                    o = {"id": oid, "date": det.get("date", ""),
                         "products": det.get("products") or
                                     [{"title": f"(не прочитал название) товар {i}",
                                       "url": f"https://aliexpress.ru/item/{i}.html"} for i in items]}
                    if det.get("products"):
                        if active:
                            o["at"] = time.time()
                        _put({key: o})
                # orders cached before 2026-09-29 have "when" and "total" instead of "date"
                when = " · ".join(x for x in (o["date"], status) if x) if "date" in o else o["when"]
                o = dict(o, when=when, total=total or o.get("total", ""))
                scanned += 1
                if _match(o, alts):
                    rows.append(o)
                    if len(rows) >= limit:
                        break
            if capped or len(rows) >= limit:
                break
    finally:
        tab.close()
    log.info("ali_orders %r: %d found, %d scanned, %d fetched", query, len(rows), scanned, fetched)
    return _format("AliExpress", rows, scanned, capped, query)
