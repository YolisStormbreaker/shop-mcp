"""Yandex Market: search, product card, reviews and cart (view; add and remove need the tab on screen). Never checks out.

Search results are server-rendered; every snippet carries its data as JSON in data-zone-data,
so the page is parsed rather than an API called. Prices and delivery are for the user's region.
"""
import json
import time
import urllib.parse

from cdp import tab_for
from shoplog import dump, log

# names as the site labels them: rating = «Высокий рейтинг», with_reviews = «С отзывами» (a filter, not an order)
SORTS = {"default": None, "price": "aprice", "price_desc": "dprice", "rating": "rating", "with_reviews": "opinions", "new": "ddate"}
CAPTCHA_JS = "/showcaptcha/.test(location.href) || /^Ой/.test(document.title)"
BLOCKED = "⚠️ Яндекс Маркет показал капчу: shop-chrome show, пройти её в браузере, повторить."

SEARCH_JS = r"""
(() => {
  const t = s => (s || '').replace(/\s+/g, ' ').trim();
  return [...document.querySelectorAll('[data-zone-name="productSnippet"]')].map(el => {
    let z = {};
    try { z = JSON.parse(el.getAttribute('data-zone-data') || '{}'); } catch (e) {}
    const add = Object.fromEntries((z.additionalPrices || []).map(a => [a.priceType, a.priceValue]));
    const q = a => t(el.querySelector(`[data-auto="${a}"]`)?.innerText);
    return {
      sku: z.marketSku || '', title: z.title || q('snippet-title'), price: z.price ?? '',
      card: add.yaBank || '', nocard: add.withDiscount || '',
      shop: (z.signals || []).find(s => s.type === 'shop')?.title || '',
      ad: !!z.sponsored, cross: z.isCrossBorder === 'true',
      delivery: q('delivery-wrapper'), reviews: q('reviews'),
      url: (el.querySelector('[data-auto="snippet-link"]')?.getAttribute('href') || '').split('?')[0],
    };
  });
})()
"""

ITEM_JS = r"""
(() => {
  const t = s => (s || '').replace(/\s+/g, ' ').trim();
  const q = (sel, root = document) => t(root?.querySelector(sel)?.innerText);
  const main = document.querySelector('[data-auto="main"]');
  const lines = (document.querySelector('[data-zone-name="ProductSpecsList"]')?.innerText || '')
    .split('\n').map(t).filter(s => s && s !== 'Все характеристики');
  const specs = [];
  for (let i = 0; i + 1 < lines.length; i += 2) specs.push(lines[i] + ': ' + lines[i + 1]);
  let z = {};
  try { z = JSON.parse(document.querySelector('[data-zone-name="cartButton"][data-zone-data]')?.getAttribute('data-zone-data') || '{}'); } catch (e) {}
  return {
    title: q('h1'), vendor: q('[data-auto="product-card-vendor"]'), rating: q('[data-auto="product-rating"]').replace(/\s*·$/, ''),
    price: q('[data-auto="snippet-price-current"]', main), old: q('[data-auto="snippet-price-old"]', main),
    pay: /Пэй/.test(main?.innerText || ''),
    shop: q('[data-auto="shop-info-title"]'), trust: q('[data-auto="trust-info-block"]'),
    // date/type up to the price only: after the price a variant shows the user's pickup address
    delivery: [...document.querySelectorAll('[data-zone-name="deliveryVariant"]')].map(e => {
      const v = e.innerText.split('\n').map(t).filter(Boolean);
      const k = v.findIndex(s => /₽$/.test(s));
      return (k >= 0 ? v.slice(0, k + 1) : v.slice(0, 1)).join(' ');
    }),
    specs, sku: z.marketSku || '', cross: z.isCrossBorder === 'true',
    description: t(document.querySelector('[data-zone-name="description"]')?.innerText).replace(/Всё описание$/, ''),
    // gallery thumbnails come in several sizes of one picture; /orig is the full one
    photos: [...new Set([...document.querySelectorAll('[data-zone-name="pictureGallery"] img')].map(i => i.src)
      .filter(s => /get-mpic/.test(s)).map(s => s.replace(/\/[^/]+$/, '/orig')))],
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


def search(query, price_min=None, price_max=None, sort="default", page=1, limit=30):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    qs = {"text": query}
    if price_min:
        qs["pricefrom"] = int(price_min)
    if price_max:
        qs["priceto"] = int(price_max)
    if SORTS[sort]:
        qs["how"] = SORTS[sort]
    if page > 1:
        qs["page"] = page
    url = "https://market.yandex.ru/search?" + urllib.parse.urlencode(qs)
    tab = tab_for("market.yandex.ru")
    try:
        tab.goto(url, "ym", wait_js=f"{_new_page(tab)} && (!!document.querySelector('[data-zone-name=\"productSnippet\"]') || {CAPTCHA_JS})")
        if _captcha(tab, f"search {url}"):
            return BLOCKED
        # only the server-rendered part of the grid: the rest loads on scroll, which a background tab never does
        items = tab.js(SEARCH_JS)
    finally:
        tab.close()
    seen, rows = set(), []
    for x in items:
        key = x["sku"] or x["url"]
        if key in seen:
            continue
        seen.add(key)
        nocard = x["nocard"] or x["price"]
        before = x["price"] if x["nocard"] else ""
        marks = ", ".join(m for m, on in (("продвижение", x["ad"]), ("из-за рубежа", x["cross"])) if on)
        rows.append(f"{len(rows)+1}\t{x['sku']}\t{x['card']}\t{nocard}\t{before}\t{x['title']}\t{x['shop']}\t"
                    f"{x['reviews']}\t{x['delivery']}\t{marks}\t{x['url']}")
    promoted = sum(1 for r in rows if "продвижение" in r)
    head = (f"Яндекс Маркет · страница {page} · карточек: {len(rows)}, продвигаемых: {promoted}; дальше — page={page + 1} · {url}\n"
            "ссылки относительно https://market.yandex.ru; цены и доставка — для региона из профиля\n"
            "#\tsku\tс картой Я Банка ₽\tбез карты ₽\tдо скидок ₽\tназвание\tмагазин\tрейтинг · купили\tдоставка\tпометки\tссылка")
    return head + "\n" + ("\n".join(rows[:limit]) if rows else "(пусто)")


def item(url, full=False):
    if url.startswith("/"):
        url = "https://market.yandex.ru" + url
    if "market.yandex.ru" not in url:
        return "нужна ссылка на товар Яндекс Маркета (https://market.yandex.ru/card/...)"
    tab = tab_for("market.yandex.ru")
    try:
        tab.goto(url, "ym", wait_js=f"{_new_page(tab)} && (!!document.querySelector('h1') || {CAPTCHA_JS})")
        if _captcha(tab, f"item {url}"):
            return BLOCKED
        r = tab.js(ITEM_JS)
    finally:
        tab.close()
    lines = [f"{r['title']} — {r['price'] or 'нет цены'}" + (" с Яндекс Пэй" if r["pay"] else "")
             + (f" (до скидок {r['old']})" if r["old"] else ""),
             url.split("?")[0]]
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
    lines.append("\n" + (r["description"] if full else r["description"][:2500]))
    return "\n".join(lines)


# The reviews page ignores sort and page parameters in the URL. Sorting is a chip with options
# (element.click() works in a hidden tab); more reviews load on scroll, which a hidden tab never
# does, so each sort gives its first 10.
REVIEW_SORTS = {"useful": "relevance-1", "new": "date-1", "high": "grade-1", "low": "grade-0"}
REVIEWS_JS = r"""
(() => {
  const t = s => (s || '').replace(/\s+/g, ' ').trim();
  return {
    summary: t(document.querySelector('[data-auto="rating-distribution-block"]')?.innerText),
    dist: t(document.querySelector('[data-auto="rating-distribution"]')?.innerText),
    reviews: [...document.querySelectorAll('[data-auto="review-item"]')].map(e => {
      let z = {};
      try { z = JSON.parse(e.closest('[data-zone-data]')?.getAttribute('data-zone-data') || '{}'); } catch (x) {}
      return {
        grade: z.grade, date: z.date || t(e.querySelector('[data-auto="created-date"]')?.innerText),
        up: z.votesAgree || 0, down: z.votesDisagree || 0,
        author: t(e.querySelector('[data-auto="nickname"]')?.innerText),
        text: (e.querySelector('[data-auto="review-description"]')?.innerText || '').split('\n').map(t).filter(Boolean).join(' | '),
        variant: (e.querySelector('[data-auto="ugc-element-offer-info"]')?.innerText || '').split('\n').map(t).filter(Boolean).join(', '),
        photos: [...new Set([...e.querySelectorAll('img')].map(i => i.src).filter(s => /get-market-ugc/.test(s))
          .map(s => s.replace(/(get-market-ugc\/\d+\/[^/]+).*$/, '$1/orig')))],
      };
    }),
  };
})()
"""


def reviews(url, sort="useful", with_media=False, this_variant=False):
    if sort not in REVIEW_SORTS:
        return f"sort: одно из {', '.join(REVIEW_SORTS)}"
    if url.startswith("/"):
        url = "https://market.yandex.ru" + url
    if "market.yandex.ru/card/" not in url:
        return "нужна ссылка на товар Яндекс Маркета (https://market.yandex.ru/card/...)"
    url = url.split("?")[0].rstrip("/").removesuffix("/reviews") + "/reviews"
    items = "document.querySelectorAll('[data-auto=\"review-item\"]')"
    tab = tab_for("market.yandex.ru")
    try:
        tab.goto(url, "ym", wait_js=f"{_new_page(tab)} && ({items}.length > 0 || /нет отзывов|Отзывов пока нет/i.test(document.body.innerText) || {CAPTCHA_JS})")
        if _captcha(tab, f"reviews {url}"):
            return BLOCKED
        def redraw(js):
            first = tab.js(f"{items}[0]?.innerText || ''")
            tab.js(js)
            for _ in range(20):
                time.sleep(0.4)
                if tab.js(f"({items}[0]?.innerText || '') !== {json.dumps(first)}"):
                    break
        if this_variant:
            redraw("document.querySelector('[data-zone-name=thisOptionTab]')?.querySelector('button,a,input,label')?.click()"
                   " || document.querySelector('[data-zone-name=thisOptionTab]')?.click()")
        if sort != "useful":
            tab.js("document.querySelector('[data-auto=\"product-reviews-sort\"]')?.click()")
            time.sleep(0.8)
            redraw(f"document.querySelector('[data-auto=\"more-actions-{REVIEW_SORTS[sort]}\"]')?.click()")
        r = tab.js(REVIEWS_JS)
    finally:
        tab.close()
    rows = [x for x in r["reviews"] if x["photos"] or not with_media]
    head = (f"Яндекс Маркет · {url}\n{r['summary']}" + (f" · {r['dist']}" if r["dist"] else "") + "\n"
            f"{'только этот вариант' if this_variant else 'все варианты'}, сортировка {sort}"
            f"{', только с фото' if with_media else ''}. Видны первые 10 отзывов на сортировку: "
            "следующие сайт подгружает прокруткой видимой страницы, а браузер скрыт. Год у дат текущего года сайт не пишет.\n"
            "дата\t★\tполезно +/−\tвариант\tавтор\tтекст\tфото (shop_images)")
    return head + "\n" + ("\n".join(f"{x['date']}\t{x['grade']}\t+{x['up']}/−{x['down']}\t{x['variant']}\t{x['author']}\t{x['text']}\t{' '.join(x['photos'])}"
                                    for x in rows) if rows else "(отзывов нет)")


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
    tab.goto(CART_URL, "ym", wait_js=f"{_new_page(tab)} && (!!document.querySelector('input[type=checkbox]') || /пуст/i.test(document.body.innerText) || {CAPTCHA_JS})")
    return None if _captcha(tab, "cart") else tab.js(ROWS_JS)


def _cart_text(rows):
    if not rows:
        return "корзина Яндекс Маркета пуста"
    return ("корзина Яндекс Маркета (✓ — выбрано к оформлению; цена с картой Яндекс Пэй, как её показывает строка)\n"
            "sku\tшт\tцена\t✓\tтовар\n" + "\n".join(f"{r['sku']}\t{r['qty']}\t{r['price']}\t{'✓' if r['checked'] else ''}\t{r['text']}" for r in rows))


def cart():
    tab = tab_for("market.yandex.ru")
    try:
        rows = _open_cart(tab)
    finally:
        tab.close()
    return BLOCKED if rows is None else _cart_text(rows)


def add_to_cart(url):
    if url.startswith("/"):
        url = "https://market.yandex.ru" + url
    tab = tab_for("market.yandex.ru")
    try:
        before = _open_cart(tab)
        if before is None:
            return BLOCKED
        tab.goto(url, "ym", wait_js=f"{_new_page(tab)} && (!!document.querySelector('h1') || {CAPTCHA_JS})")
        if _captcha(tab, f"add {url}"):
            return BLOCKED
        # the offer's own button: the page also has «В корзину» on every similar product
        if not tab.click('[data-auto="main"] [data-auto="cartButton"]'):
            return "не добавлено: " + (NOT_ON_SCREEN if not tab.visible() else "не нашёл кнопку «В корзину» у основного предложения")
        time.sleep(2)
        rows = _open_cart(tab)
    finally:
        tab.close()
    if rows is None:
        return BLOCKED
    old = {r["sku"]: r["qty"] for r in before}
    new = [r for r in rows if old.get(r["sku"]) != r["qty"]]  # the page does not name its sku reliably: diff the cart
    if not new:
        return "⚠️ Маркет не подтвердил добавление (или товар уже был в корзине)\n" + _cart_text(rows)
    return f"добавлено: sku {', '.join(r['sku'] for r in new)}\n" + _cart_text(rows)


def remove_from_cart(sku):
    sku = str(sku).strip()
    tab = tab_for("market.yandex.ru")
    try:
        rows = _open_cart(tab)
        if rows is None:
            return BLOCKED
        row = next((r for r in rows if r["sku"] == sku), None)
        if not row:
            return "такого sku в корзине нет\n" + _cart_text(rows)
        if not tab.visible():
            return "не удалено: " + NOT_ON_SCREEN
        # «−» at the row's own quantity field: each click takes one off, the last one removes the line
        minus = f"""(() => {{ const r = (window.__ymRows || []).find(r => r.sku === {json.dumps(sku)}); if (!r) return null;
            const q = r.el.querySelector('input[type=number]'); if (!q) return null;
            const b = [...r.el.querySelectorAll('button')].filter(b => b.compareDocumentPosition(q) & Node.DOCUMENT_POSITION_FOLLOWING).pop();  // «−» sits right before the field
            if (!b) return null; b.scrollIntoView({{block: 'center'}}); window.__ymMinus = b; return true; }})()"""
        for _ in range(int(row["qty"] or 1)):
            if not tab.js(minus):
                break
            time.sleep(0.6)
            x, y = tab.js("(() => { const r = window.__ymMinus.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
            for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
                tab.call("Input.dispatchMouseEvent", type=typ, x=x, y=y, button="left", clickCount=1)
            time.sleep(1.5)
            tab.js(ROWS_JS)  # the line re-renders after each change
        rows = _open_cart(tab)
    finally:
        tab.close()
    if rows is None:
        return BLOCKED
    gone = not any(r["sku"] == sku for r in rows)
    return f"{'удалено' if gone else '⚠️ Маркет не подтвердил удаление'}: sku {sku}\n" + _cart_text(rows)
