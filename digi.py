"""Site search by Diginetica (sort.diginetica.net), shared by Biggeek and PiterGSM: both run its «instant search» widget,
which reads the query, sort and price filter from the page's address and asks sort.diginetica.net for 20 products.

We load that address and take the widget's own answer (capture). The widget starts only after a requestAnimationFrame,
which Chrome never runs in a hidden tab: so the search needs the site's tab on screen, and says so instead of loading
a page that can't work. Further pages come only on scroll (there is no page in the address): page 1 only.
Prices and stock are the search index's, the same for every city (regionId=global).
"""
import urllib.parse

from capture import capture
from cdp import tab_for
from shoplog import log

PAGE = 20
SORTS = {"relevance": "DEFAULT", "price_asc": "PRICE_ASC", "price_desc": "PRICE_DESC"}
HIDDEN = ("⚠️ Поиск {name} работает только в видимой вкладке: сайт запускает его, когда вкладка на экране. "
          "Попроси пользователя выполнить shop-chrome show (вкладку инструмент выведет вперёд сам) и повтори; "
          "карточки ({site}_item) открываются и в скрытом браузере.")
BLOCKED = "⚠️ {name} не отдал результаты поиска (проверка на бота или сайт не успел): shop-chrome show, открыть сайт, повторить."
MORE = "⚠️ {name} подгружает следующие страницы поиска только прокруткой, их здесь нет: уточни запрос или задай price_min / price_max / sort."


def search(shop, query, price_min=None, price_max=None, sort="relevance", page=1, limit=PAGE):
    """shop: {site, domain, home, name} of the store."""
    if sort not in SORTS:
        return f"sort: одно из {', '.join(SORTS)}"
    if page > 1:
        return MORE.format(**shop)
    url = search_url(shop["home"], query, price_min, price_max, sort)
    tab = tab_for(shop["domain"])
    try:
        tab.call("Page.bringToFront")      # the site's search starts in the visible tab only: in a shown window this makes it so
        if not tab.visible():
            return HIDDEN.format(**shop)
        got = capture(tab, shop["site"], url, {"s": ["sort.diginetica.net/search"]}).get("s")
    finally:
        tab.close()
    if "products" not in (got or {}):
        log.warning("%s search %s: no diginetica answer", shop["site"], url)
        return BLOCKED.format(**shop)
    return _table(shop, got, query, url, limit)


def search_url(home, query, price_min, price_max, sort):
    """The widget's own address form: params=|sort=<SORT>|filter=price:<min>;<max>"""
    params = f"|sort={SORTS[sort]}"
    if price_min or price_max:
        params += f"|filter=price:{int(price_min or 0)};{int(price_max or 10_000_000)}"
    return f"{home}/?" + urllib.parse.urlencode({"digiSearch": "true", "term": query, "params": params})


def _rub(s):
    return str(int(float(s))) if s and float(s) else ""        # "14090.0" -> "14090"; no price is "0.0"


def _table(shop, d, query, url, limit):
    rows = [_row(i + 1, p) for i, p in enumerate((d.get("products") or [])[:limit])]
    head = (f"{shop['name']} · {d.get('totalHits') or 0} найдено · страница 1 (по {PAGE}) · {url}\n" + _note(d, query) +
            f"ссылки относительно {shop['home']}; цены и наличие — как в поиске сайта, без привязки к городу\n"
            "#\tid\tцена ₽\tбез скидки\tназвание\tналичие\tссылка")
    return head + "\n" + ("\n".join(rows) if rows else "(пусто)")


def _note(d, query):
    """What the site did with the query: searched a corrected one, or found nothing exact and shows the nearest."""
    if d.get("zeroQueries"):
        return "точных совпадений нет — сайт показал похожие товары\n"
    fixed = d.get("correction") or ""
    return f"сайт искал «{fixed}»\n" if fixed and fixed.lower() != query.lower() else ""


def _row(n, p):
    now, old = _rub(p.get("price")), _rub(p.get("oldPrice"))
    return (f"{n}\t{p.get('id')}\t{now}\t{old if old != now else ''}\t{p.get('name', '')}\t"
            f"{'' if p.get('available') else 'нет в наличии'}\t{p.get('link_url', '')}")
