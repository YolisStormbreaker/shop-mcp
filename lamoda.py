"""Lamoda: search and product card, read-only.

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
