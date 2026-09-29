"""Lamoda: search, product card and cart (view, add, remove). Never checks out.

Pages are server-rendered with the data in window.__NUXT__ (products, prices with every discount
applied, sizes in stock), so we read that state instead of the markup.
"""
import json
import re
import urllib.parse

from cdp import tab_for
from shoplog import dump, log

SORTS = ("default", "new", "price_asc", "price_desc", "new_sale", "discount")
STATE = "window.__NUXT__?.payload?.state?.payload"
BLOCKED = "⚠️ Lamoda не отдала данные страницы (проверка на бота?): shop-chrome show, открыть сайт, повторить."

SEARCH_JS = f"""
(() => {{
  const P = {STATE};
  if (!P?.products) return null;
  return {{found: P.pagination?.found ?? P.products.length, pages: P.pagination?.pages || 1, page: P.pagination?.page || 1, items: P.products.map(p => {{
    const pr = p.prices || [];
    const last = pr[pr.length - 1] || {{}};
    return {{
      sku: p.sku, name: p.name, brand: p.brand?.name || '',
      price: +(last.price ?? p.price_amount), base: +(pr[0]?.price ?? p.old_price_amount ?? 0),
      until: (last.discount?.active_to || '').slice(0, 10),
      rating: p.rating?.average_rating ? (p.rating.average_rating / 20).toFixed(1) : '', reviews: p.rating?.reviews_count || '',
      sizes: (p.sizes || []).filter(s => s.is_available).map(s => s.brand_size).join(' '),
      ad: !!p.ad_params, url: `/p/${{p.sku.toLowerCase()}}/${{p.seo_tail}}/`,
    }};
  }})}};
}})()
"""

ITEM_JS = f"""
(() => {{
  const p = {STATE}?.product;
  if (!p) return null;
  const prices = Object.values(p.prices || {{}}).map(x => +String(x.price).replace(/\\D/g, '')).filter(Boolean);
  return {{
    title: [p.brand?.title || p.brand?.name, p.model_title || p.title].filter(Boolean).join(' '), kind: p.title, sku: p.sku,
    price: prices.length ? Math.min(...prices) : null, base: prices.length ? Math.max(...prices) : null,
    seller: p.seller?.title || '', returnable: !!p.is_returnable, in_stock: !!p.is_in_stock,
    sizes: (p.sizes || []).map(s => `${{s.title}}${{s.brand_title && s.brand_title !== s.title ? ` (${{s.brand_size_system}} ${{s.brand_title}})` : ''}}: ${{s.stock_quantity ? s.stock_quantity + ' шт' : 'нет'}}`),
    attrs: (p.attributes || []).map(a => `${{a.title}}: ${{a.value}}`),
    description: (p.description || '').slice(0, 2500),
  }};
}})()
"""


def search(query, price_min=None, price_max=None, sort="default", page=1, limit=30):
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    qs = {"q": query}
    if sort != "default":
        qs["sort"] = sort
    if price_min or price_max:
        qs["price"] = f"{int(price_min or 0)},{int(price_max or 10_000_000)}"
    if page > 1:
        qs["page"] = page
    url = "https://www.lamoda.ru/catalogsearch/result/?" + urllib.parse.urlencode(qs)
    tab = tab_for("lamoda.ru")
    try:
        # the tab still holds the previous page's state until the new one loads
        old = tab.js(f"{STATE}?.catalog_request_id || ''")
        tab.goto(url, "lamoda", wait_js=f"!!{STATE}?.products && {STATE}.catalog_request_id !== {json.dumps(old)}")
        r = tab.js(SEARCH_JS)
        if r is None:
            saved = dump("lamoda", "search", tab.js("document.documentElement.outerHTML"))
            log.warning("lamoda search %s: no __NUXT__ products, page %s", url, saved)
    finally:
        tab.close()
    if r is None:
        return BLOCKED
    rows = []
    for i, x in enumerate(r["items"][:limit]):
        marks = "реклама" if x["ad"] else ""
        rows.append(f"{i+1}\t{x['sku']}\t{x['price']}\t{x['base'] if x['base'] > x['price'] else ''}\t{x['until']}\t"
                    f"{x['brand']}\t{x['name']}\t{x['rating']}\t{x['reviews']}\t{x['sizes']}\t{marks}\t{x['url']}")
    head = (f"Lamoda · {r['found']} найдено · страница {r['page']} из {r['pages']} · {url}\n"
            "ссылки относительно https://www.lamoda.ru; цена — со всеми скидками, включая вашу скидку лояльности; "
            "«до» — когда кончается акционная цена; размеры в наличии — в системе бренда\n"
            "#\tsku\tцена ₽\tбез скидок\tакция до\tбренд\tназвание\tрейтинг\tотзывов\tразмеры в наличии\tпометки\tссылка")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def item(sku_or_url):
    s = sku_or_url.strip()
    if s.startswith("/"):
        s = "https://www.lamoda.ru" + s
    url = s if "lamoda.ru" in s else f"https://www.lamoda.ru/p/{s.lower()}/"
    m = re.search(r"/p/([a-z0-9]+)", url, re.I)
    ready = f"{STATE}?.product?.sku?.toLowerCase() === {json.dumps(m.group(1).lower())}" if m else f"!!{STATE}?.product"
    tab = tab_for("lamoda.ru")
    try:
        tab.goto(url, "lamoda", wait_js=ready)
        r = tab.js(ITEM_JS)
        if r is None:
            saved = dump("lamoda", "item", tab.js("document.documentElement.outerHTML"))
            log.warning("lamoda item %s: no __NUXT__ product, page %s", url, saved)
    finally:
        tab.close()
    if r is None:
        return BLOCKED
    lines = [f"{r['title']} ({r['kind']}) — {r['price']} ₽" + (f", без скидок {r['base']} ₽" if r["base"] and r["base"] > r["price"] else ""),
             url.split("?")[0], f"sku: {r['sku']} · продавец: {r['seller']} · " + ("можно вернуть" if r["returnable"] else "⚠️ без возврата")]
    lines.append("размеры: " + "; ".join(r["sizes"]) if r["sizes"] else ("в наличии" if r["in_stock"] else "нет в наличии"))
    if r["attrs"]:
        lines.append("характеристики: " + "; ".join(r["attrs"]))
    lines.append("\n" + r["description"])
    return "\n".join(lines)


# Cart: the site's own API client (cartGet / cartAdd / cartRemove in its code) — same-origin JSON with
# the session cookie, so it works from a background tab. geo is the delivery region the site keeps in
# the gd_aoid cookie; the tab must be on lamoda.ru for relative URLs and that cookie.
def _lm_tab():
    tab = tab_for("lamoda.ru")
    if "lamoda.ru" not in (tab.js("location.hostname") or ""):
        tab.goto("https://www.lamoda.ru/", "lamoda", wait_js="document.readyState === 'complete'")
    return tab


def _api(tab, method, path, body=None, retried=False):
    opts = {"method": method, "credentials": "include"}
    if body is not None:
        opts["headers"] = {"Content-Type": "application/json"}
        opts["body"] = json.dumps(body)
    r = tab.js(f"fetch({json.dumps(path)}, {json.dumps(opts)}).then(async r => ({{s: r.status, b: await r.text()}}))")
    try:
        return json.loads(r["b"])
    except ValueError:
        pass
    log.warning("lamoda %s %s: %s non-JSON%s", method, path, r["s"], " again after reload" if retried else "")
    if retried:
        return None
    tab.goto("https://www.lamoda.ru/", "lamoda", wait_js="document.readyState === 'complete'")  # renews anti-bot cookies
    return _api(tab, method, path, body, retried=True)


def _geo(tab):
    aoid = tab.js("decodeURIComponent((document.cookie.match(/(?:^|; )gd_aoid=([^;]+)/) || [])[1] || '')")
    return {"aoid": aoid} if aoid else None


def _lines(d):
    return [i for p in (d or {}).get("packages") or [] for i in p.get("items") or []]


def _cart_text(d):
    items = _lines(d)
    if not items:
        return "корзина Lamoda пуста"
    rows = [f"{i['size'].get('sku')}\t{i.get('quantity')}\t{i.get('total_price')}\t{i.get('original_price') if i.get('original_price') != i.get('total_price') else ''}\t"
            f"{(i.get('product') or {}).get('brand', {}).get('title', '')}\t{(i.get('product') or {}).get('title', '')}\t{i['size'].get('title', '')}"
            for i in items]
    return (f"корзина Lamoda: {d.get('total_quantity')} шт, итого {d.get('total_price')} ₽ (со всеми скидками)\n"
            "sku размера\tшт\tсумма ₽\tбез скидок\tбренд\tназвание\tразмер\n" + "\n".join(rows))


def cart():
    tab = _lm_tab()
    try:
        d = _api(tab, "GET", "/api/v1/cart/get")
    finally:
        tab.close()
    return BLOCKED if d is None else _cart_text(d)


def add_to_cart(sku_or_url, size=None):
    s = sku_or_url.strip()
    m = re.search(r"/p/([a-z0-9]+)", s, re.I) or re.fullmatch(r"([a-z0-9]{12})", s, re.I)
    if not m:
        return "нужен sku товара (из lamoda_search) или ссылка на товар"
    sku = m.group(1).upper()
    tab = _lm_tab()
    try:
        tab.goto(f"https://www.lamoda.ru/p/{sku.lower()}/", "lamoda", wait_js=f"{STATE}?.product?.sku === {json.dumps(sku)}")
        sizes = tab.js(f"({STATE}?.product?.sizes || []).map(s => ({{sku: s.sku, title: s.title, brand: s.brand_title || '', stock: s.stock_quantity || 0}}))")
        if not sizes:
            return BLOCKED
        names = ", ".join(f"{x['title']}{' (' + x['brand'] + ')' if x['brand'] and x['brand'] != x['title'] else ''}: {x['stock']} шт" for x in sizes)
        if size is None and len(sizes) > 1:
            return "у товара несколько размеров, укажи size: " + names
        pick = sizes[0] if size is None else next((x for x in sizes if str(size).strip().lower() in (x["title"].lower(), x["brand"].lower(), x["sku"].lower())), None)
        if not pick:
            return f"нет размера «{size}»; есть: " + names
        if not pick["stock"]:
            return f"размер {pick['title']} закончился; есть: " + names
        geo = _geo(tab)
        if not geo:
            return "⚠️ не нашёл регион доставки Lamoda (cookie gd_aoid): открой сайт и выбери город"
        _api(tab, "POST", "/api/v1/cart/add", {"sku": pick["sku"], "geo": geo})
        d = _api(tab, "GET", "/api/v1/cart/get")
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    ok = any(i["size"].get("sku") == pick["sku"] for i in _lines(d))
    return f"{'добавлено' if ok else '⚠️ Lamoda не подтвердила добавление'}: {pick['sku']}, размер {pick['title']}\n" + _cart_text(d)


def remove_from_cart(size_sku):
    size_sku = size_sku.strip().upper()
    tab = _lm_tab()
    try:
        d = _api(tab, "GET", "/api/v1/cart/get")
        if d is None:
            return BLOCKED
        if not any(i["size"].get("sku") == size_sku for i in _lines(d)):
            return "такого sku размера в корзине нет\n" + _cart_text(d)
        _api(tab, "POST", "/api/v1/cart/remove", {"skus": [size_sku], "geo": _geo(tab)})
        d = _api(tab, "GET", "/api/v1/cart/get")
    finally:
        tab.close()
    if d is None:
        return BLOCKED
    gone = not any(i["size"].get("sku") == size_sku for i in _lines(d))
    return f"{'удалено' if gone else '⚠️ Lamoda не подтвердила удаление'}: {size_sku}\n" + _cart_text(d)
