#!/usr/bin/env python3
"""
ym_full.py — ПОЛНАЯ выгрузка Stat API (все строки, вся история счётчика).
Дополняет ym_pull.py: тут limit=100000 и расширенный список измерений + кросс-таблицы.
Пишет полные CSV в data/mirrors/metrica/full/. Печатает размеры и хвосты.

Запуск: python3 scripts/metrika/ym_full.py [date1] [date2]
"""
import os, sys, json, csv, time, urllib.parse, urllib.request, urllib.error, pathlib

COUNTER = "108324634"
REPO = pathlib.Path(__file__).resolve().parents[2]
OUTDIR = REPO / "data" / "mirrors" / "metrica" / "full"
OUTDIR.mkdir(parents=True, exist_ok=True)
TOKEN = os.environ.get("YM_TOKEN") or \
    open(os.path.expanduser("~/ProjectData/Puntus/ym_token.txt")).read().strip()

D1 = sys.argv[1] if len(sys.argv) > 1 else "2026-03-20"   # до старта счётчика — API отдаст с первого дня
D2 = sys.argv[2] if len(sys.argv) > 2 else "yesterday"
LIM = 100000
BASE = "ym:s:visits,ym:s:ecommercePurchases,ym:s:ecommerceRevenue"

# key, human, dimensions, metrics, sort
REPORTS = [
    # полная глубина существующих
    ("city_all",        "Все города",            "ym:s:regionCity",        BASE, "-ym:s:ecommerceRevenue"),
    ("products_all",    "Все товары",            "ym:s:productName",       "ym:s:productPurchasedQuantity,ym:s:productPurchasedPrice", "-ym:s:productPurchasedPrice"),
    ("landing_all",     "Все входные страницы",   "ym:s:startURLPathFull",  BASE, "-ym:s:visits"),
    ("search_all",      "Все поисковые фразы",    "ym:s:searchPhrase",      "ym:s:visits", "-ym:s:visits"),
    ("country_all",     "Все страны",            "ym:s:regionCountry",     BASE, "-ym:s:visits"),
    # новые измерения
    ("browser",         "Браузеры",              "ym:s:browser",           BASE, "-ym:s:visits"),
    ("os",              "Операционные системы",   "ym:s:operatingSystem",   BASE, "-ym:s:visits"),
    ("phone_brand",     "Бренд смартфона",        "ym:s:mobilePhone",       BASE, "-ym:s:visits"),
    ("social_net",      "Соцсети (детально)",     "ym:s:lastSocialNetwork", BASE, "-ym:s:visits"),
    ("utm_source",      "UTM source",            "ym:s:UTMSource",         BASE, "-ym:s:visits"),
    ("utm_campaign",    "UTM campaign",          "ym:s:UTMCampaign",       BASE, "-ym:s:visits"),
    ("utm_medium",      "UTM medium",            "ym:s:UTMMedium",         BASE, "-ym:s:visits"),
    ("exit_page",       "Страницы выхода",        "ym:s:endURLPathFull",    "ym:s:visits", "-ym:s:visits"),
    ("depth",           "Глубина просмотра",      "ym:s:pageViews",         BASE, "ym:s:pageViews"),
    ("duration_bucket", "Длительность визита",    "ym:s:visitDuration",     BASE, "ym:s:visitDuration"),
    ("region",          "Регионы/области",        "ym:s:regionArea",        BASE, "-ym:s:ecommerceRevenue"),
    # кросс-таблицы (где прячется Simpson's paradox и настоящие драйверы)
    ("x_source_device", "Источник × устройство",  "ym:s:lastTrafficSource,ym:s:deviceCategory", BASE, "-ym:s:visits"),
    ("x_landing_source","Страница × источник",    "ym:s:startURLPathFull,ym:s:lastTrafficSource", BASE, "-ym:s:visits"),
    ("x_product_gender","Товар × пол (B1)",       "ym:s:productName,ym:s:gender", "ym:s:ecommercePurchases,ym:s:ecommerceRevenue", "-ym:s:ecommerceRevenue"),
    ("x_city_device",   "Город × устройство",     "ym:s:regionCity,ym:s:deviceCategory", BASE, "-ym:s:visits"),
    ("x_date_source",   "День × источник",        "ym:s:date,ym:s:lastTrafficSource", BASE, "ym:s:date"),
]


def stat(dims, metrics, sort):
    p = {"ids": COUNTER, "dimensions": dims, "metrics": metrics, "sort": sort,
         "date1": D1, "date2": D2, "limit": LIM, "accuracy": "full"}
    url = "https://api-metrika.yandex.net/stat/v1/data?" + urllib.parse.urlencode(p)
    r = urllib.request.Request(url, headers={"Authorization": "OAuth " + TOKEN})
    for a in range(4):
        try:
            return json.load(urllib.request.urlopen(r, timeout=180))
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code in (429, 503) and a < 3:
                time.sleep(3 * (a + 1)); continue
            return {"errors": body[:200], "code": e.code}
        except Exception as e:
            if a < 3: time.sleep(3); continue
            return {"errors": str(e)[:200]}


def main():
    print(f"# ПОЛНАЯ ВЫГРУЗКА #{COUNTER}  {D1}..{D2}  (limit {LIM})\n")
    total_bytes = 0
    for key, human, dims, metrics, sort in REPORTS:
        resp = stat(dims, metrics, sort)
        if resp.get("errors"):
            print(f"⚠️ {human} [{key}] — ОШИБКА: {resp['errors']}")
            continue
        rows = resp.get("data", [])
        tr = resp.get("total_rows")
        header = [d.split(":")[-1] for d in dims.split(",")] + \
                 [m.split(":")[-1] for m in metrics.split(",")]
        path = OUTDIR / f"{key}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(header)
            for r in rows:
                dv = [d.get("name") if d.get("name") is not None else d.get("id") for d in r["dimensions"]]
                w.writerow(dv + r["metrics"])
        sz = path.stat().st_size; total_bytes += sz
        samp = "  ⚠️SAMPLED" if resp.get("sampled") else ""
        print(f"✅ {human:26} [{key:16}] {len(rows):>6} строк (всего {tr}) → {sz//1024} КБ{samp}")
    print(f"\nИТОГО файлов в {OUTDIR.relative_to(REPO)}: ~{total_bytes//1024} КБ")


if __name__ == "__main__":
    main()
