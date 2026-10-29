"""Yandex Market: search, product card, reviews and cart (view; add and remove need the tab on screen). Never checks out.

Search results are server-rendered; every snippet carries its data as JSON in data-zone-data,
so the page is parsed rather than an API called. Prices and delivery are for the user's region.
"""
import json
import re
import time
import urllib.parse

from cdp import tab_for
from shoplog import dump, log

# names as the site labels them: rating = «Высокий рейтинг», with_reviews = «С отзывами» (a filter, not an order)
SORTS = {"default": None, "price": "aprice", "price_desc": "dprice", "rating": "rating", "with_reviews": "opinions", "new": "ddate"}
CAPTCHA_JS = "/showcaptcha/.test(location.href) || /^Ой/.test(document.title)"
BLOCKED = "⚠️ Яндекс Маркет показал капчу: shop-chrome show, пройти её в браузере, повторить."
NOT_A_CARD = "нужна ссылка на товар Яндекс Маркета (https://market.yandex.ru/card/...)"

SEARCH_JS = r"""
(() => {
  const t = s => (s || '').replace(/\s+/g, ' ').trim();
  return [...document.querySelectorAll('[data-zone-name="productSnippet"]')].map(el => {
    let zone = {};
    try { zone = JSON.parse(el.getAttribute('data-zone-data') || '{}'); } catch (e) {}
    const q = a => t(el.querySelector(`[data-auto="${a}"]`)?.innerText);
    return {zone, title: q('snippet-title'), delivery: q('delivery-wrapper'), reviews: q('reviews'),
            href: el.querySelector('[data-auto="snippet-link"]')?.getAttribute('href') || ''};
  });
})()
"""

ITEM_JS = r"""
(() => {
  const t = s => (s || '').replace(/\s+/g, ' ').trim();
  const q = (sel, root = document) => t(root?.querySelector(sel)?.innerText);
  const main = document.querySelector('[data-auto="main"]');
  let zone = {};
  // the offer's sku and cross-border flag: the cart button's zone no longer has them (2026-10)
  try { zone = JSON.parse(main?.querySelector('[data-zone-name="productSnippet"][data-zone-data]')?.getAttribute('data-zone-data') || '{}'); } catch (e) {}
  return {
    title: q('h1'), vendor: q('[data-auto="product-card-vendor"]'), rating: q('[data-auto="product-rating"]'),
    price: q('[data-auto="snippet-price-current"]', main), old: q('[data-auto="snippet-price-old"]', main),
    pay: /Пэй/.test(main?.innerText || ''),
    shop: q('[data-auto="shop-info-title"]'), trust: q('[data-auto="trust-info-block"]'),
    delivery: [...document.querySelectorAll('[data-zone-name="deliveryVariant"]')].map(e => e.innerText),
    specs: document.querySelector('[data-zone-name="ProductSpecsList"]')?.innerText || '', zone,
    description: q('[data-zone-name="description"]'),
    photos: [...document.querySelectorAll('[data-zone-name="pictureGallery"] img')].map(i => i.src),
  };
})()
"""


def _new_page(tab):
    """JS condition true only once the tab shows a new document: right after navigate the old page,
    which also has snippets (similar items) and an h1, can still be there. YM rewrites the URL, so not location."""
    return f"performance.timeOrigin !== {tab.js('performance.timeOrigin')}"


def _captcha(tab, what):
    if tab.js(CAPTCHA_JS):
        saved = dump("ym", "captcha", tab.js("document.documentElement.outerHTML"))
        log.warning("ym %s: captcha, page %s", what, saved)
        return True
    return False


def _in_tab(work):
    """work(tab) in the Market tab, held for this call only."""
    tab = tab_for("market.yandex.ru")
    try:
        return work(tab)
    finally:
        tab.close()


def _load(tab, url, what, ready, read):
    """read(tab) once the tab shows url (ready: JS condition of a loaded page); None behind a captcha."""
    tab.goto(url, "ym", wait_js=f"{_new_page(tab)} && ({ready} || {CAPTCHA_JS})")
    return None if _captcha(tab, f"{what} {url}") else read(tab)


def _read(url, what, ready, read):
    """_load in the Market tab, held for this call only."""
    return _in_tab(lambda tab: _load(tab, url, what, ready, read))


def search(query, price_min=None, price_max=None, sort="default", page=1, limit=30):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    url = _search_url(query, price_min, price_max, sort, page)
    # only the server-rendered part of the grid: the rest loads on scroll, which a background tab never does
    items = _read(url, "search", "!!document.querySelector('[data-zone-name=\"productSnippet\"]')", lambda tab: tab.js(SEARCH_JS))
    if items is None:
        return BLOCKED
    cards = _unique(map(_snippet, items))
    rows = [_search_row(n, x) for n, x in enumerate(cards, 1)]
    promoted = sum(x["ad"] for x in cards)
    head = (f"Яндекс Маркет · страница {page} · карточек: {len(rows)}, продвигаемых: {promoted}; дальше — page={page + 1} · {url}\n"
            "ссылки относительно https://market.yandex.ru; цены и доставка — для региона из профиля\n"
            "#\tsku\tс картой Я Банка ₽\tбез карты ₽\tдо скидок ₽\tназвание\tмагазин\tрейтинг · купили\tдоставка\tпометки\tссылка")
    return head + "\n" + ("\n".join(rows[:limit]) if rows else "(пусто)")


def _search_url(query, price_min, price_max, sort, page):
    qs = {"text": query}
    if price_min:
        qs["pricefrom"] = int(price_min)
    if price_max:
        qs["priceto"] = int(price_max)
    if SORTS[sort]:
        qs["how"] = SORTS[sort]
    if page > 1:
        qs["page"] = page
    return "https://market.yandex.ru/search?" + urllib.parse.urlencode(qs)


def _snippet(s):
    """One card from the snippet's data-zone-data and the texts around it."""
    z = s["zone"]
    shop = next((x.get("title") for x in z.get("signals") or [] if x.get("type") == "shop"), None)
    return {"sku": z.get("marketSku") or "", "title": z.get("title") or s["title"], **_prices(z), "shop": shop or "",
            "ad": bool(z.get("sponsored")), "cross": z.get("isCrossBorder") == "true",  # a string, "true" or "false"
            "delivery": s["delivery"], "reviews": s["reviews"], "url": s["href"].split("?")[0]}


def _prices(z):
    """price is the one on the card; additionalPrices hold it with the Ya Bank card (yaBank) and without (withDiscount)."""
    other = {a.get("priceType"): a.get("priceValue") for a in z.get("additionalPrices") or []}
    return {"price": "" if z.get("price") is None else z["price"], "card": other.get("yaBank") or "", "nocard": other.get("withDiscount") or ""}


def _unique(items):
    """Snippets in page order, each sku (or link, when there is none) once."""
    first = {}
    for x in items:
        first.setdefault(x["sku"] or x["url"], x)
    return list(first.values())


def _search_row(n, x):
    marks = ", ".join(m for m, on in (("продвижение", x["ad"]), ("из-за рубежа", x["cross"])) if on)
    return (f"{n}\t{x['sku']}\t{x['card']}\t{x['nocard'] or x['price']}\t{x['price'] if x['nocard'] else ''}\t{x['title']}\t"
            f"{x['shop']}\t{x['reviews']}\t{x['delivery']}\t{marks}\t{x['url']}")


def _absolute(url):
    return "https://market.yandex.ru" + url if url.startswith("/") else url


def _market(url):
    """The link made absolute if it is on market.yandex.ru, else None: the logged-in Market tab never goes to
    another site, whatever the link's text contains."""
    url = _absolute(url)
    host = urllib.parse.urlsplit(url).hostname or ""
    return url if host == "market.yandex.ru" or host.endswith(".market.yandex.ru") else None


def item(url, full=False):
    url = _market(url)
    if not url:
        return NOT_A_CARD
    r = _read(url, "item", "!!document.querySelector('h1')", lambda tab: tab.js(ITEM_JS))
    return BLOCKED if r is None else _card(_item(r), url, full)


def _item(p):
    """The card page's texts -> the fields of the card."""
    z = p["zone"]
    return {**p, "rating": re.sub(r"\s*·$", "", p["rating"]), "description": p["description"].removesuffix("Всё описание").rstrip(),
            "delivery": [_delivery(v) for v in p["delivery"]], "specs": _specs(p["specs"]), "photos": _gallery(p["photos"]),
            "sku": z.get("marketSku") or "", "cross": z.get("isCrossBorder") == "true"}


def _lines(text):
    """innerText -> its non-empty lines, spaces collapsed."""
    return [s for s in (" ".join(x.split()) for x in text.split("\n")) if s]


def _delivery(text):
    """Date and type up to the price only: after the price a variant shows the user's pickup address."""
    v = _lines(text)
    return " ".join(v[:next((k for k, s in enumerate(v) if s.endswith("₽")), 0) + 1])


def _specs(text):
    """«name, value» line pairs of the spec list."""
    lines = [s for s in _lines(text) if s != "Все характеристики"]
    return [f"{a}: {b}" for a, b in zip(lines[::2], lines[1::2])]


def _gallery(srcs):
    """Gallery thumbnails come in several sizes of one picture; /orig is the full one."""
    return list(dict.fromkeys(re.sub(r"/[^/]+$", "/orig", s) for s in srcs if "get-mpic" in s))


def _card(r, url, full):
    lines = [_price_line(r), url.split("?")[0]]
    if r["cross"]:
        lines.append("⚠️ из-за рубежа")
    lines += [f"{k}: {v}" for k, v in (("sku", r["sku"]), ("бренд", r["vendor"]), ("рейтинг", r["rating"]),
              ("магазин", f"{r['shop']} · {r['trust']}".strip(" ·"))) if v]
    if r["delivery"]:
        lines.append("доставка: " + "; ".join(r["delivery"]))
    if r["photos"]:
        lines.append("фото (shop_images): " + " ".join(r["photos"][:10]))
    lines.append("отзывы: ym_reviews")
    if r["specs"]:
        lines.append("характеристики: " + "; ".join(r["specs"]))
    if r["description"]:
        lines.append("\n" + (r["description"] if full else r["description"][:2500]))
    return "\n".join(lines)


def _price_line(r):
    return (f"{r['title']} — {r['price'] or 'нет цены'}" + (" с Яндекс Пэй" if r["pay"] else "")
            + (f" (до скидок {r['old']})" if r["old"] else ""))


# The reviews page ignores sort and page parameters in the URL. Sorting is a chip with options
# (element.click() works in a hidden tab); more reviews load on scroll, which a hidden tab never
# does, so each sort gives its first 10.
REVIEW_SORTS = {"useful": "relevance-1", "new": "date-1", "high": "grade-1", "low": "grade-0"}
REVIEW_ITEMS = "document.querySelectorAll('[data-auto=\"review-item\"]')"
REVIEWS_JS = r"""
(() => {
  const t = s => (s || '').replace(/\s+/g, ' ').trim();
  const text = (e, a) => e.querySelector(`[data-auto="${a}"]`)?.innerText || '';
  return {
    summary: t(document.querySelector('[data-auto="rating-distribution-block"]')?.innerText),
    dist: t(document.querySelector('[data-auto="rating-distribution"]')?.innerText),
    reviews: [...document.querySelectorAll('[data-auto="review-item"]')].map(e => {
      let zone = {};
      try { zone = JSON.parse(e.closest('[data-zone-data]')?.getAttribute('data-zone-data') || '{}'); } catch (x) {}
      return {zone, date: t(text(e, 'created-date')), author: t(text(e, 'nickname')), text: text(e, 'review-description'),
              variant: text(e, 'ugc-element-offer-info'), photos: [...e.querySelectorAll('img')].map(i => i.src)};
    }),
  };
})()
"""


def reviews(url, sort="useful", with_media=False, this_variant=False):
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    url = _reviews_url(url)
    if not url:
        return NOT_A_CARD
    r = _read(url, "reviews", f"{REVIEW_ITEMS}.length > 0 || /нет отзывов|Отзывов пока нет/i.test(document.body.innerText)",
              lambda tab: _sorted_reviews(tab, sort, this_variant))
    return BLOCKED if r is None else _reviews_text(r, url, sort, with_media, this_variant)


def _reviews_url(url):
    """The card's reviews page, or None for a link that is not a card."""
    url = _market(url)
    return url.split("?")[0].rstrip("/").removesuffix("/reviews") + "/reviews" if url and "/card/" in url else None


def _sorted_reviews(tab, sort, this_variant):
    if this_variant:
        _redraw(tab, "document.querySelector('[data-zone-name=thisOptionTab]')?.querySelector('button,a,input,label')?.click()"
                     " || document.querySelector('[data-zone-name=thisOptionTab]')?.click()")
    if sort != "useful":
        tab.js("document.querySelector('[data-auto=\"product-reviews-sort\"]')?.click()")
        time.sleep(0.8)
        _redraw(tab, f"document.querySelector('[data-auto=\"more-actions-{REVIEW_SORTS[sort]}\"]')?.click()")
    return tab.js(REVIEWS_JS)


def _redraw(tab, js):
    """Run js (a click), then wait up to 8 s for the list to show another first review."""
    first = tab.js(f"{REVIEW_ITEMS}[0]?.innerText || ''")
    tab.js(js)
    for _ in range(20):
        time.sleep(0.4)
        if tab.js(f"({REVIEW_ITEMS}[0]?.innerText || '') !== {json.dumps(first)}"):
            break


def _reviews_text(r, url, sort, with_media, this_variant):
    rows = [_review_row(x) for x in map(_review, r["reviews"]) if x["photos"] or not with_media]
    head = (f"Яндекс Маркет · {url}\n{r['summary']}" + (f" · {r['dist']}" if r["dist"] else "") + "\n"
            f"{'только этот вариант' if this_variant else 'все варианты'}, сортировка {sort}"
            f"{', только с фото' if with_media else ''}. Видны первые 10 отзывов на сортировку: "
            "следующие сайт подгружает прокруткой видимой страницы, а браузер скрыт. Год у дат текущего года сайт не пишет.\n"
            "дата\t★\tполезно +/−\tвариант\tавтор\tтекст\tфото (shop_images)")
    return head + "\n" + ("\n".join(rows) if rows else "(отзывов нет)")


def _review(e):
    """One review's zone data and texts -> the fields of its row."""
    z = e["zone"]
    return {"grade": z.get("grade", ""), "date": z.get("date") or e["date"], "up": z.get("votesAgree") or 0,
            "down": z.get("votesDisagree") or 0, "author": e["author"], "text": " | ".join(_lines(e["text"])),
            "variant": ", ".join(_lines(e["variant"])), "photos": list(dict.fromkeys(
                re.sub(r"(get-market-ugc/\d+/[^/]+).*$", r"\1/orig", s) for s in e["photos"] if "get-market-ugc" in s))}


def _review_row(x):
    return f"{x['date']}\t{x['grade']}\t+{x['up']}/−{x['down']}\t{x['variant']}\t{x['author']}\t{x['text']}\t{' '.join(x['photos'])}"


# Cart. Reading works from a background tab; adding and removing are clicks (the site's cart calls
# are gRPC with a page secret), so they need the Market tab on screen. Rows are found by their
# checkbox and sku, never by button text: the cart header has a bulk «Удалить» for all selected items.
CART_URL = "https://market.yandex.ru/my/cart"
# Each cart line: the widest block around one sku's zones that holds no other sku and at most one
# quantity field; blocks without a quantity field (recommendations) are not cart lines.
# Rows are kept in window.__ymRows so a click can target one row's own «−».
ROWS_JS = r"""
(() => {
  const own = e => { try { const d = JSON.parse(e.getAttribute('data-zone-data')); return String(d.marketSku || d.skuId || '') } catch (x) { return '' } };
  const QTY = 'input[type=number]';
  const zones = [...document.querySelectorAll('[data-zone-data]')].filter(e => own(e));
  const rows = [];
  for (const sku of new Set(zones.map(own))) {
    let best = null;
    for (const z of zones.filter(e => own(e) === sku)) {
      let p = z;
      while (p.parentElement && !zones.some(e => own(e) !== sku && p.parentElement.contains(e)) && p.parentElement.querySelectorAll(QTY).length <= 1) p = p.parentElement;
      if (!best || p.contains(best)) best = p;
    }
    const qty = best && best.querySelector(QTY);
    if (!qty) continue;
    const cb = best.querySelector('input[type=checkbox]'), text = (best.innerText || '').replace(/\s+/g, ' ').trim();
    rows.push({el: best, sku, qty: qty.value, checked: cb ? cb.checked : null, text: text.slice(0, 150),
               price: ((text.match(/\d[\d\s\u2009\u00a0]*₽/) || [''])[0]).replace(/[\s\u2009\u00a0]/g, '')});
  }
  window.__ymRows = rows;
  return rows.map(({el, ...r}) => r);
})()
"""
NOT_ON_SCREEN = ("вкладка Яндекс Маркета не на экране, а корзина меняется только кликами в видимой вкладке. "
                 "Попроси пользователя выполнить shop-chrome show и открыть вкладку market.yandex.ru, потом повтори.")


def _open_cart(tab):
    """The cart's rows, None behind a captcha."""
    return _load(tab, CART_URL, "cart", "!!document.querySelector('input[type=checkbox]') || /пуст/i.test(document.body.innerText)",
                 lambda t: t.js(ROWS_JS))


def _cart_text(rows):
    if not rows:
        return "корзина Яндекс Маркета пуста"
    return ("корзина Яндекс Маркета (✓ — выбрано к оформлению; цена с картой Яндекс Пэй, как её показывает строка)\n"
            "sku\tшт\tцена\t✓\tтовар\n" + "\n".join(f"{r['sku']}\t{r['qty']}\t{r['price']}\t{'✓' if r['checked'] else ''}\t{r['text']}" for r in rows))


def cart():
    rows = _in_tab(_open_cart)
    return BLOCKED if rows is None else _cart_text(rows)


def add_to_cart(url):
    url = _market(url)
    if not url:
        return NOT_A_CARD
    return _in_tab(lambda tab: _add(tab, url))


def _add(tab, url):
    before = _open_cart(tab)
    if before is None:
        return BLOCKED
    # the offer's own button: the page also has «В корзину» on every similar product
    clicked = _load(tab, url, "add", "!!document.querySelector('h1')", lambda t: t.click('[data-auto="main"] [data-auto="cartButton"]'))
    if clicked is None:
        return BLOCKED
    if not clicked:
        return "не добавлено: " + (NOT_ON_SCREEN if not tab.visible() else "не нашёл кнопку «В корзину» у основного предложения")
    time.sleep(2)
    rows = _open_cart(tab)
    return BLOCKED if rows is None else _added(before, rows)


def _added(before, rows):
    """The reply from the cart's rows before and after the click."""
    old = {r["sku"]: r["qty"] for r in before}
    new = [r for r in rows if old.get(r["sku"]) != r["qty"]]  # the page does not name its sku reliably: diff the cart
    if not new:
        return "⚠️ Маркет не подтвердил добавление (или товар уже был в корзине)\n" + _cart_text(rows)
    return f"добавлено: sku {', '.join(r['sku'] for r in new)}\n" + _cart_text(rows)


def remove_from_cart(sku):
    sku = str(sku).strip()
    return _in_tab(lambda tab: _remove(tab, sku))


def _remove(tab, sku):
    rows = _open_cart(tab)
    if rows is None:
        return BLOCKED
    row = next((r for r in rows if r["sku"] == sku), None)
    if not row:
        return "такого sku в корзине нет\n" + _cart_text(rows)
    if not tab.visible():
        return "не удалено: " + NOT_ON_SCREEN
    _take_off(tab, sku, int(row["qty"] or 1))
    rows = _open_cart(tab)
    return BLOCKED if rows is None else _removed(sku, rows)


def _take_off(tab, sku, times):
    """Click «−» at the row's own quantity field times: each click takes one off, the last one removes the line."""
    minus = f"""(() => {{ const r = (window.__ymRows || []).find(r => r.sku === {json.dumps(sku)}); if (!r) return null;
        const q = r.el.querySelector('input[type=number]'); if (!q) return null;
        const b = [...r.el.querySelectorAll('button')].filter(b => b.compareDocumentPosition(q) & Node.DOCUMENT_POSITION_FOLLOWING).pop();  // «−» sits right before the field
        if (!b) return null; b.scrollIntoView({{block: 'center'}}); window.__ymMinus = b; return true; }})()"""
    for _ in range(times):
        if not tab.js(minus):
            break
        time.sleep(0.6)
        x, y = tab.js("(() => { const r = window.__ymMinus.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
            tab.call("Input.dispatchMouseEvent", type=typ, x=x, y=y, button="left", clickCount=1)
        time.sleep(1.5)
        tab.js(ROWS_JS)  # the line re-renders after each change


def _removed(sku, rows):
    gone = not any(r["sku"] == sku for r in rows)
    return f"{'удалено' if gone else '⚠️ Маркет не подтвердил удаление'}: sku {sku}\n" + _cart_text(rows)
