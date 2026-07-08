#!/usr/bin/env python3
"""
ym_pull.py — полная выгрузка Яндекс.Метрики (Stat API) для Puntús #108324634.

Тянет ~15 срезов (источники, устройства, гео, демография, страницы, время,
товары, фразы), пишет CSV в data/mirrors/metrica/ и печатает читаемый дайджест
для анализа. Токен: $YM_TOKEN или ~/ProjectData/Puntus/ym_token.txt.

Запуск:
  python3 scripts/metrika/ym_pull.py                    # 90 дней
  python3 scripts/metrika/ym_pull.py 2026-01-01 2026-07-07
"""
import os, sys, json, csv, time, urllib.parse, urllib.request, urllib.error, pathlib

COUNTER = "108324634"
REPO = pathlib.Path(__file__).resolve().parents[2]
OUTDIR = REPO / "data" / "mirrors" / "metrica"
OUTDIR.mkdir(parents=True, exist_ok=True)

TOKEN = os.environ.get("YM_TOKEN") or \
    open(os.path.expanduser("~/ProjectData/Puntus/ym_token.txt")).read().strip()

D1 = sys.argv[1] if len(sys.argv) > 1 else "90daysAgo"
D2 = sys.argv[2] if len(sys.argv) > 2 else "yesterday"

BASE = "ym:s:visits,ym:s:ecommercePurchases,ym:s:ecommerceRevenue"  # визиты, заказы, выручка

# key, human, dimensions, metrics, sort, limit
REPORTS = [
    ("00_timeseries",   "Динамика по дням",        "ym:s:date",            BASE, "ym:s:date", 400),
    ("01_traffic",      "Источники трафика",        "ym:s:lastTrafficSource", BASE, "-ym:s:ecommerceRevenue", 20),
    ("02_engine",       "Поисковые системы",        "ym:s:lastSourceEngine",  BASE, "-ym:s:visits", 20),
    ("03_device",       "Устройства",               "ym:s:deviceCategory",    BASE, "-ym:s:visits", 10),
    ("04_gender",       "Пол (кто платит)",         "ym:s:gender",            BASE, "-ym:s:ecommercePurchases", 10),
    ("05_age",          "Возраст",                  "ym:s:ageInterval",       BASE, "-ym:s:ecommercePurchases", 15),
    ("06_gender_age",   "Пол × возраст",            "ym:s:gender,ym:s:ageInterval", BASE, "-ym:s:ecommercePurchases", 30),
    ("07_city",         "Города (выручка)",         "ym:s:regionCity",        BASE, "-ym:s:ecommerceRevenue", 30),
    ("08_landing",      "Входные страницы",         "ym:s:startURLPathFull",  BASE, "-ym:s:visits", 30),
    ("09_dayofweek",    "День недели",              "ym:s:dayOfWeekName",     BASE, "-ym:s:ecommercePurchases", 7),
    ("10_hour",         "Час суток",                "ym:s:hour",              BASE, "ym:s:hour", 24),
    ("11_products",     "Товары (выручка)",         "ym:s:productName",       "ym:s:productPurchasedQuantity,ym:s:productPurchasedPrice", "-ym:s:productPurchasedPrice", 40),
    ("12_search",       "Поисковые фразы",          "ym:s:searchPhrase",      "ym:s:visits", "-ym:s:visits", 40),
    ("13_newvsret",     "Новый / вернувшийся",      "ym:s:isNewUser",         BASE, "-ym:s:visits", 5),
]


def api(path, params):
    params = dict(params); params["ids"] = COUNTER
    url = "https://api-metrika.yandex.net" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "OAuth " + TOKEN})
    for attempt in range(4):
        try:
            return json.load(urllib.request.urlopen(req, timeout=90))
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code in (429, 503) and attempt < 3:
                time.sleep(2 * (attempt + 1)); continue
            return {"errors": [{"http": e.code, "body": body[:200]}]}
        except Exception as e:
            if attempt < 3:
                time.sleep(2); continue
            return {"errors": [{"exc": str(e)[:200]}]}


def stat(dims, metrics, sort, limit):
    return api("/stat/v1/data", {
        "dimensions": dims, "metrics": metrics, "sort": sort,
        "date1": D1, "date2": D2, "limit": limit, "accuracy": "full",
    })


def rows_of(resp):
    """→ [(dim_labels[list], metric_values[list]), ...]"""
    out = []
    for r in resp.get("data", []):
        dims = [d.get("name") if d.get("name") is not None else d.get("id") for d in r["dimensions"]]
        out.append((dims, r["metrics"]))
    return out


def fmt(n):
    if isinstance(n, float) and n.is_integer(): n = int(n)
    if isinstance(n, (int, float)) and abs(n) >= 1000:
        return f"{n:,.0f}".replace(",", " ")
    return str(round(n, 2) if isinstance(n, float) else n)


def main():
    print(f"# МЕТРИКА #{COUNTER} — выгрузка {D1}..{D2}\n")

    # цели (для контекста CR)
    goals = api(f"/management/v1/counter/{COUNTER}/goals", {})
    if goals.get("goals"):
        print("## Цели счётчика")
        for g in goals["goals"]:
            print(f"  - id {g['id']}: {g['name']} ({g.get('type')})")
        print()

    # общий тотал (для среднего CR)
    tot = stat("", BASE, "-ym:s:visits", 1).get("totals", [0, 0, 0])
    visits_all, orders_all, rev_all = tot
    cr_all = 100 * orders_all / visits_all if visits_all else 0
    aov_all = rev_all / orders_all if orders_all else 0
    print(f"## ИТОГО за период: визиты {fmt(visits_all)} | заказы {fmt(orders_all)} | "
          f"выручка {fmt(rev_all)} ₽ | CR {cr_all:.2f}% | AOV {fmt(aov_all)} ₽\n")

    manifest = []
    for key, human, dims, metrics, sort, limit in REPORTS:
        resp = stat(dims, metrics, sort, limit)
        if resp.get("errors"):
            print(f"### ⚠️ {human} [{key}] — ОШИБКА: {resp['errors']}\n")
            continue
        rows = rows_of(resp)
        # CSV
        header = [d.split(":")[-1] for d in dims.split(",")] + \
                 [m.split(":")[-1] for m in metrics.split(",")]
        path = OUTDIR / f"{key}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(header)
            for dv, mv in rows:
                w.writerow(dv + [fmt(x) if False else x for x in mv])
        manifest.append(str(path.relative_to(REPO)))

        # дайджест (топ-8) с расчётом CR где есть заказы
        print(f"### {human} [{key}] → {path.name}")
        has_ecom = metrics == BASE
        for dv, mv in rows[:8]:
            label = " / ".join(str(x) for x in dv)
            if has_ecom:
                v, o, r = mv
                cr = 100 * o / v if v else 0
                flag = ""
                if v >= 500 and cr_all:  # помечаем заметные отклонения CR
                    if cr >= cr_all * 1.4: flag = "  🟢 CR выше среднего"
                    elif cr <= cr_all * 0.6: flag = "  🔴 CR ниже среднего"
                print(f"    {label:38} | виз {fmt(v):>7} | зак {fmt(o):>4} | "
                      f"выр {fmt(r):>10} | CR {cr:4.2f}%{flag}")
            else:
                print(f"    {label:38} | " + " | ".join(fmt(x) for x in mv))
        print()

    print("## Файлы:")
    for m in manifest:
        print("  -", m)


if __name__ == "__main__":
    main()
