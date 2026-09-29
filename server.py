# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2,<2", "websockets>=13"]
# ///
"""shop MCP: search Avito / Ozon / AliExpress in the logged-in Chrome on the Mac mini.

Run over ssh as a stdio MCP server, or with --http as a streamable HTTP server on
127.0.0.1:8765 (published through a tunnel, see launchd/local.shop-http.plist).
Output is compact TSV to keep token use low.
No tool places orders or pays: Ozon and AliExpress stop at the cart.
"""
import functools
import importlib
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP

import ali
import avito
import goldapple
import lamoda
import orders
import ozon
import wb
import ym
from shoplog import log

mcp = FastMCP("shop")

# A stdio server lives as long as the Claude session that started it, often for days, and kept
# running old code after a fix was committed (2026-09-27: ozon_orders saw 157 of 944 orders).
# So before every call, reload the modules whose files changed, dependencies first.
# Modules after a changed one are reloaded too: `from cdp import tab_for` in ozon.py keeps the
# old function until ozon itself is reloaded.
# shoplog is left alone: reloading it would add a second log handler.
# A new tool still needs a restart: tools are registered from server.py once, at start.
_RELOADABLE = ("cdp", "capture", "ali", "ozon", "avito", "orders", "wb", "ym", "lamoda", "goldapple")
_mtimes = {m: Path(sys.modules[m].__file__).stat().st_mtime for m in _RELOADABLE}
_reload_lock = threading.Lock()


def _reload_changed():
    with _reload_lock:
        changed = False
        for m in _RELOADABLE:
            mt = Path(sys.modules[m].__file__).stat().st_mtime
            if changed or mt != _mtimes[m]:
                importlib.reload(sys.modules[m])
                _mtimes[m] = mt
                changed = True
                log.info("reloaded %s.py", m)


def logged(fn):
    """Log every tool call to logs/shop.log: arguments, time, first line of the answer or the error."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t = time.time()
        call = f"{fn.__name__} {args or ''}{kwargs}"
        try:
            _reload_changed()
            out = fn(*args, **kwargs)
        except Exception:
            log.exception("%s failed in %.1f s", call, time.time() - t)
            raise
        warn = any(w in out for w in ("⚠️", "блокировку", "проверка Авито"))
        log.log(30 if warn else 20, "%s ok in %.1f s, %d lines: %s",
                call, time.time() - t, out.count("\n") + 1, out.split("\n", 1)[0][:150])
        return out
    return wrapper


@mcp.tool()
@logged
def avito_search(query: str, region: str = "sankt-peterburg", price_min: int | None = None,
                 price_max: int | None = None, sort: str = "default", page: int = 1,
                 limit: int = 30, delivery: bool = False, shipping: int = 15) -> str:
    """Поиск на Авито под аккаунтом пользователя.

    region — часть адреса Авито: sankt-peterburg, moskva, all (вся Россия) и т.п.
    sort — default | date | price | price_desc. delivery=True — только с Авито Доставкой.
    shipping=N — для первых N объявлений с Авито Доставкой узнать цену доставки в город
    из профиля и посчитать «итого» (цена + самая дешёвая доставка); 0 — не узнавать.
    Это ~2.5 с на объявление, чаще Авито включает проверку безопасности. Сортировка Авито по цене доставку
    не учитывает — самое дешёвое с доставкой ищи по колонке «итого».
    Зарезервированные объявления из этих N скрываются (в выдаче поиска Авито резерв не виден;
    при shipping=0 не проверяется). Не советуй объявление, не проверив его через avito_item.
    Возвращает TSV: цена, доставка ₽, итого, название, город, срок доставки, рейтинг, дата, ссылка.
    """
    return avito.search(query, region, price_min, price_max, sort, page, limit, delivery, shipping)


@mcp.tool()
@logged
def avito_item(url: str) -> str:
    """Детали объявления Авито: резерв (строка «⛔ ЗАРЕЗЕРВИРОВАН» — не советовать), цена, доставка в город из профиля и итог, адрес, продавец, параметры, описание (до 2500 символов)."""
    return avito.item(url)


@mcp.tool()
@logged
def ozon_search(query: str, price_min: int | None = None, price_max: int | None = None,
                sort: str = "score", limit: int = 30) -> str:
    """Поиск на Ozon под аккаунтом пользователя (доставка — на его адрес).

    sort — score (популярные) | new | price | price_desc | rating | discount.
    Возвращает TSV: sku, цена, цена без скидки, название, рейтинг, отзывы, когда привезут.
    """
    return ozon.search(query, price_min, price_max, sort, limit)


@mcp.tool()
@logged
def ozon_item(sku_or_url: str) -> str:
    """Карточка товара Ozon по sku или ссылке: цена, наличие, когда привезут, рейтинг, продавец
    с юрлицом и адресом (строка «⚠️ из-за рубежа», если продавец иностранный), все характеристики,
    описание (до 2500 символов). Проверяй товар через неё, прежде чем советовать или класть в корзину."""
    return ozon.item(sku_or_url)


@mcp.tool()
@logged
def ozon_add_to_cart(sku_or_url: str, quantity: int = 1) -> str:
    """Положить товар Ozon в корзину по sku или ссылке. Заказ не оформляет."""
    return ozon.add_to_cart(sku_or_url, quantity)


@mcp.tool()
@logged
def ozon_cart() -> str:
    """Содержимое корзины Ozon: sku, количество, цена, название, итог."""
    return ozon.cart()


@mcp.tool()
@logged
def ozon_remove_from_cart(sku_or_url: str) -> str:
    """Убрать товар из корзины Ozon по sku или ссылке."""
    return ozon.remove_from_cart(sku_or_url)


@mcp.tool()
@logged
def ali_search(query: str, price_min: int | None = None, price_max: int | None = None,
               sort: str = "default", limit: int = 30) -> str:
    """Поиск на AliExpress (aliexpress.ru) под аккаунтом пользователя.

    sort — default | orders (по числу покупок) | price | price_desc.
    Возвращает TSV: id, sku, цена, название, рейтинг, купили, «привезут до» (оценка),
    срок и цена доставки из карточки, магазин. Точные даты — в ali_item.
    """
    return ali.search(query, price_min, price_max, sort, limit)


@mcp.tool()
@logged
def ali_item(id_or_url: str, sku: str | None = None, list_variants: bool = True) -> str:
    """Товар AliExpress: цена, точные даты и цена доставки по способам, варианты (название, sku, цена).

    list_variants=False быстрее: не перебирает варианты.
    """
    return ali.item(id_or_url, sku, list_variants)


@mcp.tool()
@logged
def ali_add_to_cart(id_or_url: str, sku: str | None = None, options: dict[str, str] | None = None) -> str:
    """Положить товар AliExpress в корзину, 1 шт. Заказ не оформляет.

    Вариант задаётся sku (из ali_item) или options, например {"Цвет": "Silver"}.
    Возвращает выбранный вариант, цену, даты и цену доставки.
    """
    return ali.add_to_cart(id_or_url, sku, options)


@mcp.tool()
@logged
def ali_cart() -> str:
    """Корзина AliExpress: cart_id, выбран ли к оформлению, id товара, шт, цена, доставка, итог."""
    return ali.cart()


@mcp.tool()
@logged
def ali_remove_from_cart(cart_id_or_item_id: str) -> str:
    """Убрать строку из корзины AliExpress по cart_id или id товара. Выбор остальных строк сохраняется."""
    return ali.remove_from_cart(cart_id_or_item_id)


@mcp.tool()
@logged
def ozon_orders(query: str | None = None, year: int | None = None, limit: int = 30, max_new: int = 60) -> str:
    """История заказов Ozon с названиями товаров; query — слова, которые все должны быть в названии
    или варианте товара (без учёта регистра), например «вентилятор 5015». Несколько вариантов
    через «|» ищутся за один вызов: «usb хаб | разветвитель usb | hub» — не вызывай три раза.

    Идёт от новых к старым: текущие заказы, потом архив по годам (year — только этот год).
    Списки и заказы кэшируются: обычный вызов — секунды, повторный в течение 10 минут — мгновенно.
    max_new — предел новых загрузок за вызов: если он достигнут, в шапке будет сказано,
    и тот же вызов ещё раз продолжит поиск.
    Возвращает TSV: заказ, дата/статус, сумма заказа, товар, вариант, цена, ссылка.
    """
    return orders.ozon_orders(query, year, limit, max_new)


@mcp.tool()
@logged
def ali_orders(query: str | None = None, limit: int = 30, max_new: int = 60) -> str:
    """История заказов AliExpress (aliexpress.ru) с названиями товаров; query — слова, которые все
    должны быть в названии или варианте (без учёта регистра), например «улитка» или «blower 5015».
    Несколько вариантов через «|» ищутся за один вызов: «дисплей | экран | touch».

    Текущие заказы, потом архив. Списки и заказы кэшируются, повторный вызов в течение
    10 минут мгновенный. max_new — предел новых загрузок за вызов, повторный вызов продолжит.
    Возвращает TSV: заказ, «дата · статус», сумма заказа, товар, вариант, цена, ссылка.
    """
    return orders.ali_orders(query, limit, max_new)


@mcp.tool()
@logged
def wb_search(query: str, price_min: int | None = None, price_max: int | None = None,
              sort: str = "popular", page: int = 1, limit: int = 30) -> str:
    """Поиск на Wildberries под аккаунтом пользователя (регион и доставка — из его профиля).

    sort — popular | rate | priceup | pricedown | newly | benefit. При сортировке по цене строки
    упорядочены по цене заново: WB поднимает продвигаемые товары наверх в любой сортировке.
    Цена — без скидки WB Кошелька (на сайте она на несколько процентов ниже).
    Если совпадений нет, WB молча показывает посторонние товары — сверяй названия с запросом.
    Возвращает TSV: id, цена, без скидки, название, бренд, рейтинг, отзывы, продавец, «привезут ≈» (оценка).
    """
    return wb.search(query, price_min, price_max, sort, page, limit)


@mcp.tool()
@logged
def wb_item(id_or_url: str) -> str:
    """Карточка товара Wildberries по артикулу или ссылке: цена, наличие, оценка срока доставки,
    продавец (рейтинг, число продаж, год регистрации), характеристики, описание (до 2500 символов)."""
    return wb.item(id_or_url)


@mcp.tool()
@logged
def ym_search(query: str, price_min: int | None = None, price_max: int | None = None,
              sort: str = "default", limit: int = 30) -> str:
    """Поиск на Яндекс Маркете под аккаунтом пользователя (регион и доставка — из его профиля).

    sort — default | price | price_desc | rating | reviews.
    Возвращает TSV: sku, цена с картой Я Банка, без карты, до скидок, название, магазин, рейтинг · купили,
    доставка, пометки («реклама», «из-за рубежа»), ссылка. Если совпадений нет, Маркет молча
    показывает посторонние популярные товары — сверяй названия с запросом.
    """
    return ym.search(query, price_min, price_max, sort, limit)


@mcp.tool()
@logged
def ym_item(url: str) -> str:
    """Карточка товара Яндекс Маркета по ссылке: цена, бренд, рейтинг, магазин и его статистика,
    варианты доставки, основные характеристики, описание (до 2500 символов), пометка «из-за рубежа»."""
    return ym.item(url)


@mcp.tool()
@logged
def lamoda_search(query: str, price_min: int | None = None, price_max: int | None = None,
                  sort: str = "default", page: int = 1, limit: int = 30) -> str:
    """Поиск на Lamoda под аккаунтом пользователя.

    sort — default | new | price_asc | price_desc | new_sale | discount.
    Цена — итоговая, со всеми скидками, включая персональную скидку лояльности; фильтр price_min/max
    Lamoda применяет к своей цене, итоговая может оказаться ниже price_min.
    Возвращает TSV: sku, цена, без скидок, акция до, бренд, название, рейтинг, отзывы,
    размеры в наличии (в системе бренда), пометка «реклама», ссылка.
    """
    return lamoda.search(query, price_min, price_max, sort, page, limit)


@mcp.tool()
@logged
def lamoda_item(sku_or_url: str) -> str:
    """Карточка товара Lamoda по sku или ссылке: цена, продавец, можно ли вернуть,
    размеры с остатками, характеристики, описание (до 2500 символов)."""
    return lamoda.item(sku_or_url)


@mcp.tool()
@logged
def goldapple_search(query: str, limit: int = 24) -> str:
    """Поиск в Золотом яблоке (goldapple.ru) под аккаунтом пользователя, цены и наличие — для его города.

    Только первая страница выдачи по релевантности (до 24 товаров), без сортировки и фильтра цены.
    Возвращает TSV: артикул, цена, без скидки, бренд, название, тип, объём (и число вариантов),
    рейтинг, отзывы, наличие, ссылка.
    """
    return goldapple.search(query, limit)


@mcp.tool()
@logged
def goldapple_item(url: str) -> str:
    """Карточка товара Золотого яблока по ссылке из goldapple_search: цена и наличие каждого
    варианта (объём, цвет), описание, применение, состав (всего до 2500 символов)."""
    return goldapple.item(url)


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = 8765
        mcp.settings.stateless_http = True
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
