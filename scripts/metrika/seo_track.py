#!/usr/bin/env python3
"""
seo_track.py — риг атрибуции SEO-экспериментов Puntús.
Считает ОРГАНИЧЕСКИЕ визиты/заказы/выручку по каждой экспериментальной странице
с даты её запуска. Т.к. небрендовый органик сегодня ≈ 0, любой органический заказ
на новой странице = результат SEO-работы (чистая изоляция).

Пишет табло в stdout + дозапись снапшота в data/mirrors/seo-experiments.csv.
Запуск: python3 scripts/metrika/seo_track.py

Определения экспериментов — здесь (в git). Замеры — в mirrors (append-only).
Ранжирование по запросам мерить отдельно через GSC API (см. strategy/seo-module.md).
"""
import os, json, csv, urllib.parse, urllib.request, pathlib, datetime

TOKEN = os.environ.get("YM_TOKEN") or open(os.path.expanduser("~/ProjectData/Puntus/ym_token.txt")).read().strip()
REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "mirrors" / "seo-experiments.csv"
TODAY = os.environ.get("SEO_TODAY", "yesterday")

# --- ОПРЕДЕЛЕНИЯ ЭКСПЕРИМЕНТОВ (изолированные гипотезы) ---
# url — точный путь посадочной; launch — дата запуска (день 0); target — целевой запрос
EXPERIMENTS = [
    {"id": "E1", "url": "/rings",     "launch": "2026-07-08", "target": "кольцо с жемчугом / необычное кольцо с жемчугом", "note": "оптимизация: title/H1/meta/текст + JSON-LD (без «серебра», RULE L1)"},
    {"id": "E2", "url": "/necklace",  "launch": "2026-07-08", "target": "колье с жемчугом / барочным жемчугом", "note": "оптимизация категории"},
    {"id": "E3", "url": "/pearl-rings",    "launch": "2026-07-08", "target": "кольцо с речным/барочным жемчугом", "note": "НОВАЯ посадочная (лонг-тейл)"},
    {"id": "E4", "url": "/gift-guide",     "launch": "2026-07-08", "target": "украшение в подарок девушке", "note": "НОВАЯ инфо-страница → каталог"},
    {"id": "E5", "url": "/earrings",  "launch": "2026-07-08", "target": "серьги с жемчугом", "note": "оптимизация категории"},
]
ORG = "ym:s:lastTrafficSource=='organic'"


def api(metrics, filt, d1, d2="yesterday"):
    p = {"ids": "108324634", "metrics": metrics, "filters": filt,
         "date1": d1, "date2": d2, "limit": 1, "accuracy": "full"}
    u = "https://api-metrika.yandex.net/stat/v1/data?" + urllib.parse.urlencode(p)
    r = urllib.request.Request(u, headers={"Authorization": "OAuth " + TOKEN})
    return json.load(urllib.request.urlopen(r, timeout=60)).get("totals", [0, 0, 0])


def f(n):
    n = int(n) if isinstance(n, float) and n.is_integer() else n
    return f"{n:,.0f}".replace(",", " ") if isinstance(n, (int, float)) and abs(n) >= 1000 else str(n)


def main():
    measured = datetime.date.today().isoformat()
    # общий органик-базлайн (весь период)
    base = api("ym:s:visits,ym:s:ecommercePurchases,ym:s:ecommerceRevenue", ORG, "2026-03-20")
    print("=" * 74)
    print(f"SEO-ТАБЛО (замер {measured}) — органика по экспериментам")
    print("=" * 74)
    print(f"Органика всего за всё время: {f(base[0])} виз | {int(base[1])} зак | {f(base[2])}₽\n")
    print(f"{'ID':4}{'страница':16}{'запуск':12}{'дней':>5}{'орг.виз':>9}{'заказы':>8}{'выручка':>11}")
    rows = []
    for e in EXPERIMENTS:
        days = (datetime.date.fromisoformat(measured) - datetime.date.fromisoformat(e["launch"])).days
        if days < 1:                       # день 0/будущее — мерить нечего, базовая линия = 0
            v, o, rev = 0, 0, 0
        else:
            filt = f"{ORG} AND ym:s:startURLPathFull=='{e['url']}'"
            v, o, rev = api("ym:s:visits,ym:s:ecommercePurchases,ym:s:ecommerceRevenue", filt, e["launch"])
        print(f"{e['id']:4}{e['url']:16}{e['launch']:12}{days:>5}{f(v):>9}{int(o):>8}{f(rev):>11}")
        rows.append([measured, e["id"], e["url"], e["launch"], days, int(v), int(o), int(rev), e["target"]])
    print(f"\n→ целевые запросы (мерить ранжирование в GSC/Вебмастере):")
    for e in EXPERIMENTS:
        print(f"   {e['id']}: «{e['target']}»  — {e['note']}")

    # дозапись снапшота
    new = not OUT.exists()
    with open(OUT, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["measured_on", "exp_id", "url", "launch", "days_since", "organic_visits", "organic_orders", "organic_revenue", "target_query"])
        w.writerows(rows)
    print(f"\n✅ снапшот дозаписан в {OUT.relative_to(REPO)} ({len(rows)} строк). День 0 = базовая линия (нули).")


if __name__ == "__main__":
    main()
