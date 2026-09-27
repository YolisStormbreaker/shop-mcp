"""Order history on Ozon and AliExpress, searchable by product name.

Neither site puts product names in its order list: Ozon gives pictures and prices, AliExpress
gives item ids.  So every order costs one more request for its details, and finished orders
are cached in cache/orders.json - they do not change, and the second search is instant.
Orders still on their way are fetched fresh every time.
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
_lock = threading.Lock()


def _load():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _put(key, order):
    """Add one order to the cache file.  Re-read under a file lock first: the stdio server
    and the HTTP server are separate processes and may both be writing."""
    CACHE.parent.mkdir(exist_ok=True)
    with _lock, open(CACHE.with_suffix(".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        c = _load()
        c[key] = order
        tmp = CACHE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(c, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(CACHE)


def _match(order, words):
    text = " ".join(p["title"] + " " + p.get("variant", "") for p in order["products"]).lower()
    return all(w in text for w in words)


def _words(query):
    return [w for w in (query or "").lower().split() if w]


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
def _ozon_list_pages(tab, url):
    """Yield order tiles from one tab of the order list, following its paginator."""
    for _ in range(40):
        page = ozon._page(tab, url)
        for w in ozon._widgets(page, "orderList"):
            yield from w.get("ordersV2", [])
        nxt = [w.get("nextPage") for w in ozon._widgets(page, "paginator")
               if w.get("layoutContainer", "").startswith("order-list") and w.get("nextPage")]
        if not nxt:
            return
        url = nxt[0]


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
                                          if x.get("textStyle", "PRICE") == "PRICE").replace(" ", " "),
                        "url": ("https://www.ozon.ru" + link) if link else "",
                        "seller": s.get("name", {}).get("text", ""),
                    })
    total = ""
    for w in ozon._widgets(d, "orderDoneTotal") + ozon._widgets(d, "orderTotal"):
        total = w.get("total", {}).get("right", {}).get("price", {}).get("text", "") or total
    return products, total.replace(" ", " ")


def ozon_orders(query=None, year=None, limit=30, max_new=60):
    words, cache = _words(query), _load()
    tab = ozon._tab()
    rows, scanned, fetched, capped = [], 0, 0, False
    try:
        sources = [("active", "/my/orderlist")]
        years = [year] if year else _ozon_years(tab)
        sources += [(f"archive {y}", f"/my/orderlist?selectedTab=archive&selectedYear={y}") for y in years]
        seen = set()
        for tag, url in sources:
            for t in _ozon_list_pages(tab, url):
                oid, status = _ozon_tile(t)
                if not oid or oid in seen:
                    continue
                seen.add(oid)
                key = f"ozon:{oid}"
                o = cache.get(key)
                if o is None:
                    if fetched >= max_new:
                        capped = True
                        break
                    products, total = _ozon_details(tab, oid)
                    fetched += 1
                    o = {"id": oid, "when": status + (f" ({tag.split()[-1]})" if tag != "active" else ""),
                         "total": total, "products": products}
                    if tag != "active":
                        _put(key, o)
                scanned += 1
                if _match(o, words):
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


def ali_orders(query=None, limit=30, max_new=60):
    words, cache = _words(query), _load()
    tab = ali._tab()
    rows, scanned, fetched, capped = [], 0, 0, False
    try:
        seen = set()
        for tab_type in ("active", "archive"):
            page = 1
            while True:
                r = ali._fetch(tab, ALI_LIST, {"tabType": tab_type, "page": page, "pageSize": 20}) or {}
                data = r.get("data") or {}
                for group in data.get("items") or []:
                    for od in group.get("orders") or []:
                        oid = od.get("orderId")
                        if not oid or oid in seen:
                            continue
                        seen.add(oid)
                        key = f"ali:{oid}"
                        o = cache.get(key)
                        if o is None:
                            if fetched >= max_new:
                                capped = True
                                break
                            det = _ali_detail(tab, oid) or {}
                            fetched += 1
                            status = (od.get("statusInfo") or {}).get("title") or (od.get("tag") or {}).get("title", "")
                            o = {"id": oid, "when": " · ".join(x for x in (det.get("date", ""), status) if x),
                                 "total": od.get("totalPrice", "").replace(" ", " "),
                                 "products": det.get("products") or
                                             [{"title": f"(не прочитал название) товар {p.get('itemId')}",
                                               "url": f"https://aliexpress.ru/item/{p.get('itemId')}.html"}
                                              for p in od.get("products") or []]}
                            if tab_type == "archive" and det.get("products"):
                                _put(key, o)
                        scanned += 1
                        if _match(o, words):
                            rows.append(o)
                            if len(rows) >= limit:
                                break
                    if capped or len(rows) >= limit:
                        break
                if capped or len(rows) >= limit or not data.get("hasMore"):
                    break
                page += 1
            if capped or len(rows) >= limit:
                break
    finally:
        tab.close()
    log.info("ali_orders %r: %d found, %d scanned, %d fetched", query, len(rows), scanned, fetched)
    return _format("AliExpress", rows, scanned, capped, query)
