"""Yandex Market: search and product card, read-only.

Search results are server-rendered; every snippet carries its data as JSON in data-zone-data,
so the page is parsed rather than an API called. Prices and delivery are for the user's region.
"""
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
    description: t(document.querySelector('[data-zone-name="description"]')?.innerText).replace(/Всё описание$/, '').slice(0, 2500),
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


def item(url):
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
    if r["specs"]:
        lines.append("характеристики: " + "; ".join(r["specs"]))
    lines.append("\n" + r["description"])
    return "\n".join(lines)
