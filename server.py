# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2,<2", "websockets>=13", "pillow"]
# ///
"""shop MCP: search Avito / Ozon / AliExpress in the logged-in Chrome on the Mac mini.

Run over ssh as a stdio MCP server, or with --http as a streamable HTTP server on
127.0.0.1:8765 (published through a tunnel, see launchd/local.shop-http.plist).
Output is compact TSV to keep token use low.
No tool places orders or pays: Ozon and AliExpress stop at the cart.
Reviews: the *_leave_review tools post a review under the user's name.
Avito messenger: avito_send sends a message under the user's name.
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
import images
import lamoda
import messenger
import orders
import ozon
import reviews
import wb
import ym
from shoplog import log

INSTRUCTIONS = """\
Поиск в интернет-магазинах через отдельный Chrome пользователя (профиль shop-chrome, порт 9222),
где он вошёл на все сайты. Цены, доставка и наличие — для адреса или города из его профиля на сайте.

Что есть: поиск и карточки товара на Авито, Ozon, AliExpress, Wildberries, Яндекс Маркете, Lamoda,
в Золотом яблоке; корзины Ozon, AliExpress, Wildberries, Яндекс Маркета, Lamoda и Золотого яблока; история
заказов Ozon и AliExpress; мессенджер Авито; отзывы на купленное на Ozon и AliExpress. Действуют от имени пользователя *_add_to_cart, *_remove_from_cart, avito_send и *_leave_review —
только по его явной просьбе, текст сообщения или отзыва показать ему до отправки. Заказы нигде не оформляются и не оплачиваются.

Правила:
- Прежде чем советовать товар, открой его *_item: в поиске данные неполные.
- Пометки: «реклама» и «продвижение» — платные места; «из-за рубежа»; «⛔ ЗАРЕЗЕРВИРОВАН» на Авито — не советовать.
- Если совпадений нет, Wildberries и Яндекс Маркет молча показывают посторонние товары — сверяй названия с запросом.
- Страницы: WB по 100 товаров, Lamoda по 60, Золотое яблоко по 24; Маркет на странице показывает
  только часть выдачи (8–40 карточек), за остальным иди на page=2, 3…
- Ответ с «⚠️» или таймаут — проверка на бота или капча. Не повторяй сразу: выполни `shop-chrome show`
  (или попроси пользователя), пусть он пройдёт проверку во вкладке сайта, потом `shop-chrome hide`.
  Chrome не отвечает — `shop-chrome restart`.
- Браузер обычно скрыт, а клики работают только в видимой активной вкладке. Поэтому адрес в avito_item,
  добавление в корзину AliExpress и изменение корзины Яндекс Маркета требуют shop-chrome show и
  открытой вкладки сайта; без этого инструмент сам скажет, что не получилось. Корзины Ozon, Wildberries,
  Lamoda и Золотого яблока меняются через API сайта и работают со скрытым браузером.
- Авито включает проверку при частых запросах, а на общих IP провайдеров (CGNAT) — почти сразу: в avito_search
  ставь shipping=0…3, а доставку уточняй через avito_item у выбранных объявлений. region по умолчанию —
  sankt-peterburg: для другого города передавай его (moskva, all — вся Россия и т.п.).
- История заказов при первом проходе медленная (до 10–15 с на каждый новый заказ), дальше из кэша.
"""

mcp = FastMCP("shop", instructions=INSTRUCTIONS)

# A stdio server lives as long as the Claude session that started it, often for days, and kept
# running old code after a fix was committed (2026-09-27: ozon_orders saw 157 of 944 orders).
# So before every call, reload the modules whose files changed, dependencies first.
# Modules after a changed one are reloaded too: `from cdp import tab_for` in ozon.py keeps the
# old function until ozon itself is reloaded.
# shoplog is left alone: reloading it would add a second log handler.
# A new tool still needs a restart: tools are registered from server.py once, at start.
_RELOADABLE = ("cdp", "capture", "images", "ali", "ozon", "avito", "messenger", "orders", "reviews", "wb", "ym", "lamoda", "goldapple")
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
        text = out if isinstance(out, str) else "\n".join(x for x in out if isinstance(x, str))  # shop_images: text + pictures
        warn = any(w in text for w in ("⚠️", "блокировку", "проверка Авито"))
        log.log(30 if warn else 20, "%s ok in %.1f s, %d lines: %s",
                call, time.time() - t, text.count("\n") + 1, text.split("\n", 1)[0][:150])
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
    """Детали объявления Авито: резерв (строка «⛔ ЗАРЕЗЕРВИРОВАН» — не советовать), цена, доставка в город из профиля и итог, адрес, продавец, параметры, описание (до 2500 символов).

    Адрес раскрывается кликом, поэтому только когда вкладка Авито на экране (shop-chrome show);
    иначе строка «адрес: не раскрыт…», остальное есть."""
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
    """Содержимое корзины Ozon: sku, количество, цена, название, итог. Итог Ozon считает только
    по товарам, отмеченным к оформлению; если отмеченных нет, так и написано."""
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
    """Товар AliExpress: цена, точные даты и цена доставки по способам, варианты — все комбинации
    свойств с sku, ценой и остатком (из API сайта). sku — открыть конкретный вариант.
    list_variants=False — без списка вариантов.
    """
    return ali.item(id_or_url, sku, list_variants)


@mcp.tool()
@logged
def ali_add_to_cart(id_or_url: str, sku: str | None = None, options: dict[str, str] | None = None) -> str:
    """Положить товар AliExpress в корзину, 1 шт. Заказ не оформляет.

    Вариант задаётся sku (из ali_item) или options — свойство и значение как в списке вариантов
    ali_item, например {"Цвет": "Silver"}; если подходит не один вариант, вернёт ошибку со списком.
    Кнопка «В корзину» нажимается кликом, поэтому нужна видимая вкладка AliExpress
    (shop-chrome show); иначе вернёт «не добавлено: вкладка AliExpress не на экране…».
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
    Списки и заказы кэшируются: обычный вызов — секунды, повторный в течение 10 минут — мгновенно;
    первый проход — до 10–15 с на каждый новый заказ.
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
    10 минут мгновенный; первый проход — до 10–15 с на каждый новый заказ. max_new — предел новых загрузок за вызов, повторный вызов продолжит.
    Возвращает TSV: заказ, «дата · статус», сумма заказа, товар, вариант, цена, ссылка.
    """
    return orders.ali_orders(query, limit, max_new)


@mcp.tool()
@logged
def wb_search(query: str, price_min: int | None = None, price_max: int | None = None,
              sort: str = "popular", page: int = 1, limit: int = 30) -> str:
    """Поиск на Wildberries под аккаунтом пользователя (регион и доставка — из его профиля).

    sort — popular | rate | priceup | pricedown | newly | benefit. page — страница по 100 товаров
    (в шапке «страница N из M»). При сортировке по цене строки страницы упорядочены по цене заново:
    WB поднимает продвигаемые товары наверх в любой сортировке.
    Цена — без скидки WB Кошелька (на сайте она на несколько процентов ниже).
    Если совпадений нет, WB молча показывает посторонние товары — сверяй названия с запросом.
    Возвращает TSV: id, цена, без скидки, название, бренд, рейтинг, отзывы, продавец, «привезут ≈» (оценка).
    """
    return wb.search(query, price_min, price_max, sort, page, limit)


@mcp.tool()
@logged
def wb_item(id_or_url: str, full: bool = False) -> str:
    """Карточка товара Wildberries по артикулу или ссылке: цена, цена до скидок и скидка в %, наличие,
    оценка срока доставки на адрес пользователя, продавец (рейтинг, число продаж, год регистрации),
    история цены по неделям (мин, макс, последние), ссылки на фото (смотреть — shop_images),
    характеристики, описание (до 2500 символов; full=True — целиком). Отзывы — wb_reviews."""
    return wb.item(id_or_url, full)


@mcp.tool()
@logged
def wb_reviews(id_or_url: str, sort: str = "useful", with_media: bool = False,
               page: int = 1, limit: int = 20) -> str:
    """Отзывы Wildberries о товаре (артикул или ссылка): рейтинг, число отзывов (с текстом, фото, видео),
    распределение звёзд; по каждому дата, звёзды, голоса «полезно» +/−, цвет и размер, имя, текст
    (+ достоинства | − недостатки | текст | ответ продавца), ссылки на фото (смотреть — shop_images)
    и видео (HLS index.m3u8 и картинка-превью для shop_images).
    WB отдаёт до ~1000 отзывов с текстом на карточку (все цвета и размеры), сортировка и страницы — по ним.
    sort: useful (по голосам, по умолчанию), new, high, low. with_media=True — только с фото или видео.
    page=2, 3… — следующие limit отзывов."""
    return wb.reviews(id_or_url, sort, with_media, page, limit)


@mcp.tool()
@logged
def ym_search(query: str, price_min: int | None = None, price_max: int | None = None,
              sort: str = "default", page: int = 1, limit: int = 30) -> str:
    """Поиск на Яндекс Маркете под аккаунтом пользователя (регион и доставка — из его профиля).

    sort — default | price | price_desc | rating («Высокий рейтинг») | with_reviews («С отзывами» —
    только товары с отзывами, не по их числу) | new. На странице видна лишь часть выдачи (обычно 8–40
    карточек, остальное сайт догружает прокруткой) — за следующими товарами иди на page=2, 3…
    «продвижение» — платное размещение по данным Маркета, на сайте не подписано; при сортировке
    по умолчанию таких бывает большинство.
    Возвращает TSV: sku, цена с картой Я Банка, без карты, до скидок, название, магазин, рейтинг · купили,
    доставка, пометки («продвижение», «из-за рубежа»), ссылка. Если совпадений нет, Маркет молча
    показывает посторонние популярные товары — сверяй названия с запросом.
    """
    return ym.search(query, price_min, price_max, sort, page, limit)


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

    sort — default | new | price_asc | price_desc | new_sale | discount. page — страница по 60 товаров
    (в шапке «страница N из M»). Цена — итоговая, со всеми скидками, включая персональную скидку лояльности; фильтр price_min/max
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
def goldapple_search(query: str, price_min: int | None = None, price_max: int | None = None,
                     sort: str = "relevance", page: int = 1, limit: int = 24) -> str:
    """Поиск в Золотом яблоке (goldapple.ru) под аккаунтом пользователя, цены и наличие — для его города.

    sort — relevance | priceAsc | priceDesc | discountAmount | byRating | byNewest.
    page — страница по 24 товара; число найденных сайт ограничивает 2000 («2000+»).
    Возвращает TSV: артикул, цена, без скидки, бренд, название, тип, объём (и число вариантов),
    рейтинг, отзывы, наличие, ссылка.
    """
    return goldapple.search(query, price_min, price_max, sort, page, limit)


@mcp.tool()
@logged
def goldapple_item(url: str, full: bool = False) -> str:
    """Карточка товара Золотого яблока по ссылке из goldapple_search: цена, старая цена и скидка в %,
    наличие каждого варианта (объём, цвет), варианты доставки на адрес пользователя (срок, цена),
    ссылки на фото (смотреть — shop_images), описание, применение, состав (до 2500 символов; full=True — целиком).
    Отзывы — goldapple_reviews."""
    return goldapple.item(url, full)


@mcp.tool()
@logged
def goldapple_reviews(id_or_url: str, sort: str = "useful", with_media: bool = False,
                      page: int = 1, limit: int = 20) -> str:
    """Отзывы Золотого яблока о товаре (артикул или ссылка): общий рейтинг, доля рекомендующих,
    распределение звёзд; по каждому отзыву дата, звёзды, «полезно», вариант, автор, текст
    (+ достоинства | − недостатки | комментарий) и ссылки на фото (смотреть — shop_images).
    sort: useful (по умолчанию), new, high, low. with_media=True — только отзывы с фото.
    Страницы по 20 отзывов (page=2, 3…)."""
    return goldapple.reviews(id_or_url, sort, with_media, page, limit)


@mcp.tool()
@logged
def wb_cart() -> str:
    """Корзина Wildberries: артикул, chrt (размер), шт, цена за штуку без WB Кошелька, выбрано ли к оформлению,
    бренд, название, размер. Состояние берётся с сервера WB, как его видит и приложение."""
    return wb.cart()


@mcp.tool()
@logged
def wb_add_to_cart(id_or_url: str, size: str | None = None, quantity: int = 1) -> str:
    """Положить товар Wildberries в корзину по артикулу или ссылке. Заказ не оформляет.

    size — обязателен, если у товара несколько размеров (без него вернёт список). Если товар уже в
    корзине, ничего не меняет. Работает со скрытым браузером, ~15 с. Возвращает итоговую корзину.
    """
    return wb.add_to_cart(id_or_url, size, quantity)


@mcp.tool()
@logged
def wb_remove_from_cart(id_or_url_or_chrt: str) -> str:
    """Убрать строку из корзины Wildberries по артикулу, ссылке или chrt из wb_cart (если в корзине
    несколько размеров одного товара — нужен chrt). Убирает все штуки строки. ~10 с."""
    return wb.remove_from_cart(id_or_url_or_chrt)


@mcp.tool()
@logged
def ym_cart() -> str:
    """Корзина Яндекс Маркета: sku, шт, цена с картой Яндекс Пэй, выбрано ли к оформлению, текст строки.
    Работает со скрытым браузером."""
    return ym.cart()


@mcp.tool()
@logged
def ym_add_to_cart(url: str) -> str:
    """Положить в корзину Яндекс Маркета основное предложение со страницы товара (ссылка из ym_search). 1 шт.
    Заказ не оформляет. Нужна видимая вкладка Маркета (shop-chrome show): иначе вернёт «не добавлено…»."""
    return ym.add_to_cart(url)


@mcp.tool()
@logged
def ym_remove_from_cart(sku: str) -> str:
    """Убрать товар из корзины Яндекс Маркета по sku из ym_cart (все штуки строки). Нужна видимая вкладка
    Маркета (shop-chrome show): иначе вернёт «не удалено…»."""
    return ym.remove_from_cart(sku)


@mcp.tool()
@logged
def lamoda_cart() -> str:
    """Корзина Lamoda: sku размера, шт, сумма строки со всеми скидками, без скидок, бренд, название, размер;
    итог по корзине. Работает со скрытым браузером."""
    return lamoda.cart()


@mcp.tool()
@logged
def lamoda_add_to_cart(sku_or_url: str, size: str | None = None) -> str:
    """Положить товар Lamoda в корзину, 1 шт: sku товара (из lamoda_search) или ссылка и size — размер как
    в lamoda_item (российский или брендовый; у одноразмерных не нужен, без него у многоразмерных вернёт
    список). Заказ не оформляет. Работает со скрытым браузером. Возвращает корзину."""
    return lamoda.add_to_cart(sku_or_url, size)


@mcp.tool()
@logged
def lamoda_remove_from_cart(size_sku: str) -> str:
    """Убрать строку из корзины Lamoda по sku размера из lamoda_cart. Работает со скрытым браузером."""
    return lamoda.remove_from_cart(size_sku)


@mcp.tool()
@logged
def goldapple_cart() -> str:
    """Корзина Золотого яблока: артикул, шт, цена за всю строку, без скидки, выбрано ли к оформлению,
    бренд, название, вариант. Работает со скрытым браузером."""
    return goldapple.cart()


@mcp.tool()
@logged
def goldapple_add_to_cart(id_or_url: str, quantity: int = 1) -> str:
    """Положить товар Золотого яблока в корзину: артикул варианта (из goldapple_item — у каждого объёма
    и цвета свой) или ссылка. Заказ не оформляет. Работает со скрытым браузером. Возвращает корзину."""
    return goldapple.add_to_cart(id_or_url, quantity)


@mcp.tool()
@logged
def goldapple_remove_from_cart(sku: str) -> str:
    """Убрать строку из корзины Золотого яблока по артикулу из goldapple_cart. Работает со скрытым браузером."""
    return goldapple.remove_from_cart(sku)


@mcp.tool()
@logged
def avito_chats(limit: int = 20, unread_only: bool = False, before: int | None = None) -> str:
    """Чаты в мессенджере Авито, новые сверху. Чаты не отмечаются прочитанными.

    unread_only=True — только непрочитанные. before — значение из строки «следующая страница».
    Возвращает TSV: id чата (для avito_chat и avito_send), ● если не прочитан, когда, собеседник,
    объявление, цена, последнее сообщение («я:» — моё), путь объявления.
    """
    return messenger.chats(limit, unread_only, before)


@mcp.tool()
@logged
def avito_chat(chat_id: str, limit: int = 30, offset: int = 0) -> str:
    """Переписка в чате Авито по id из avito_chats или ссылке на чат: собеседник, объявление,
    сообщения от старых к новым («я» — мои, «Авито» — системные). Чат не отмечается прочитанным.
    offset — сколько последних сообщений пропустить, чтобы листать назад.
    """
    return messenger.chat(chat_id, limit, offset)


@mcp.tool()
@logged
def avito_send(text: str, chat_id: str | None = None, item_url: str | None = None) -> str:
    """Отправить сообщение на Авито от имени пользователя: в существующий чат (chat_id из avito_chats)
    или продавцу объявления (item_url — ссылка на объявление; чат откроется кнопкой «Написать сообщение»).
    Только текст, без фото и файлов.

    Перед вызовом покажи пользователю получателя и итоговый текст и дождись согласия.
    Не пиши от его имени того, чего он не просил: цены, обещания, договорённости — только с его слов.
    Ответ «отправлено» значит, что сообщение видно в истории чата. При «⚠️» сначала проверь
    чат через avito_chat и не отправляй повторно вслепую.
    """
    return messenger.send(text, chat_id, item_url)


@mcp.tool()
@logged
def ozon_reviews_waiting(limit: int = 30) -> str:
    """Купленные на Ozon товары, которые ждут отзыва: sku, название, вариант."""
    return reviews.ozon_waiting(limit)


@mcp.tool()
@logged
def ozon_leave_review(sku_or_url: str, rating: int, text: str, anonymous: bool = False,
                      accept_conditions: bool = False) -> str:
    """Оставить отзыв на купленный товар Ozon: rating 1–5, text до 3000 символов.
    Отзыв публикуется от имени пользователя. Оценку и смысл текста бери только у него:
    не придумывай впечатления и не ставь оценку сам. Перед вызовом покажи ему итоговый текст
    и оценку и дождись согласия. Фото не прикладываются.

    Если за отзыв на товар дают баллы, Ozon сначала показывает условия; тогда отзыв не уходит,
    а вернутся условия. Отправить всё равно — повторить с accept_conditions=True.
    Уже оставленный отзыв не редактирует.
    """
    return reviews.ozon_review(sku_or_url, rating, text, anonymous, accept_conditions)


@mcp.tool()
@logged
def ali_reviews_waiting(limit: int = 30) -> str:
    """Купленные на AliExpress товары, которые ждут отзыва: строка заказа (для ali_leave_review),
    id товара, название, вариант."""
    return reviews.ali_waiting(limit)


@mcp.tool()
@logged
def ali_leave_review(order_line_id: str, rating: int, text: str, anonymous: bool = False) -> str:
    """Оставить отзыв на купленный товар AliExpress по строке заказа из ali_reviews_waiting:
    rating 1–5, text до 10000 символов. Отзыв уходит на модерацию, её проходят за 48 часов.
    Отзыв публикуется от имени пользователя. Оценку и смысл текста бери только у него:
    не придумывай впечатления и не ставь оценку сам. Перед вызовом покажи ему итоговый текст
    и оценку и дождись согласия. Фото не прикладываются.
    """
    return reviews.ali_review(order_line_id, rating, text, anonymous)


@mcp.tool()
@logged
def shop_images(urls: list[str], max_side: int = 1024) -> list:
    """Скачать картинки по ссылкам и показать их: фото товара из строки «фото:» любой *_item,
    фото из отзывов *_reviews или любые другие http(s)-картинки. До 6 за вызов, каждая — JPEG
    не больше max_side пикселей по длинной стороне. Ещё сохраняет файлы в cache/images сервера:
    пути — в первой, текстовой части ответа. Видео не скачивает: для отзывов с видео смотри
    его превью-картинку."""
    return images.images(urls, max_side)


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = 8765
        mcp.settings.stateless_http = True
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
