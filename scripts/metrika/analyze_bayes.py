#!/usr/bin/env python3
"""
analyze_bayes.py — статистически честный анализ сегментов Метрики.
Реализует топ-методы из дип-резерча (08.07.2026), робастные на МАЛЫХ данных
(~436 конверсий), без тяжёлых зависимостей — только numpy/scipy.

1. Байесовский рейтинг сегментов (beta-binomial, Jeffreys prior):
   для каждого сегмента — доверительный интервал CR + P(сегмент лучше/хуже сайта)
   + сколько ₽ можно вернуть, подтянув отстающих к среднему.
   → заменяет пометки «на глаз» на вероятность. (метод: bayesian-testing)
2. Simpson's paradox: переворачивается ли вывод устройство/источник внутри срезов.
3. Пуассоновская детекция аномалий дня (C-chart, точные лимиты) — для ~5 заказов/день.

Данные: data/mirrors/metrica/*.csv (90д) + full/*.csv. Запуск: python3 scripts/metrika/analyze_bayes.py
"""
import os, csv, pathlib, sys
import numpy as np
from scipy import stats

REPO = pathlib.Path(__file__).resolve().parents[2]
DIR = REPO / "data" / "mirrors" / "metrica"
FULL = DIR / "full"
rng = np.random.default_rng(42)
NMC = 200_000
MIN_V = 200           # минимум визитов, чтобы сегмент был осмысленным
AOV = 20808           # ₽, для оценки возвратной выручки


def load(path):
    rows = list(csv.reader(open(path, encoding="utf-8")))
    return rows[0], rows[1:]


def num(x):
    try: return float(x)
    except: return 0.0


def beta_draws(orders, visits, n=NMC):
    """Постериор CR ~ Beta(o+.5, v-o+.5) (Jeffreys), сэмплы."""
    a = orders + 0.5
    b = max(visits - orders, 0) + 0.5
    return rng.beta(a, b, n)


# ---------- 1. БАЙЕСОВСКИЙ РЕЙТИНГ ----------
def bayes_rank(file, label_cols=1, title=""):
    header, data = load(DIR / file)
    # ожидаем ...dims..., visits, ecommercePurchases, ecommerceRevenue
    vi = header.index("visits"); oi = header.index("ecommercePurchases")
    ri = header.index("ecommerceRevenue") if "ecommerceRevenue" in header else None
    site_v = sum(num(r[vi]) for r in data)
    site_o = sum(num(r[oi]) for r in data)
    site_cr = site_o / site_v if site_v else 0
    site_draws = beta_draws(site_o, site_v)

    print(f"\n### {title or file}  (сайт: CR {100*site_cr:.2f}%, {int(site_o)} зак / {int(site_v)} виз)")
    print(f"{'сегмент':32} {'виз':>6} {'зак':>4} {'CR%':>6} {'94% интервал':>16} {'P(лучше)':>9}  вердикт")
    out = []
    for r in data:
        v = num(r[vi]); o = num(r[oi])
        if v < MIN_V: continue
        label = " / ".join(r[:label_cols])[:31]
        d = beta_draws(o, v)
        cr = o / v
        lo, hi = np.percentile(d, [3, 97])
        p_better = float(np.mean(d > site_draws))
        if p_better >= 0.9:   verdict = "🟢 выше (уверенно)"
        elif p_better <= 0.1: verdict = "🔴 ниже (уверенно)"
        else:                 verdict = "⚪ не отличить от среднего"
        # возвратная выручка если подтянуть отстающего к среднему
        recover = max(0, (site_cr - cr)) * v * AOV
        out.append((label, v, o, cr, lo, hi, p_better, verdict, recover))

    for label, v, o, cr, lo, hi, p, verdict, rec in out:
        rectxt = f"  💰 вернуть ~{rec/1000:.0f}К₽" if (p <= 0.1 and rec > 50000) else ""
        print(f"{label:32} {int(v):>6} {int(o):>4} {100*cr:>5.2f} "
              f"[{100*lo:>4.2f};{100*hi:>5.2f}]  {p:>8.2f}  {verdict}{rectxt}")
    return out


# ---------- 2. SIMPSON'S PARADOX ----------
def simpson(file, outer_idx, inner_idx, title=""):
    header, data = load(FULL / file)
    vi = header.index("visits"); oi = header.index("ecommercePurchases")
    # агрегат по inner (напр. устройство): CR
    agg = {}
    for r in data:
        inner = r[inner_idx]
        v, o = num(r[vi]), num(r[oi])
        a = agg.setdefault(inner, [0, 0]); a[0] += v; a[1] += o
    agg_cr = {k: (o / v if v else 0) for k, (v, o) in agg.items() if v >= MIN_V}
    if len(agg_cr) < 2:
        print(f"\n### Simpson [{title}] — мало данных"); return
    global_best = max(agg_cr, key=agg_cr.get)
    print(f"\n### Simpson's paradox: {title}")
    print(f"  Агрегат: лучший = '{global_best}' " +
          ", ".join(f"{k} {100*c:.2f}%" for k, c in sorted(agg_cr.items(), key=lambda x:-x[1])))
    # внутри каждого outer (источник): кто лучший inner
    flips = []
    outers = {}
    for r in data:
        outer, inner = r[outer_idx], r[inner_idx]
        v, o = num(r[vi]), num(r[oi])
        outers.setdefault(outer, {}).setdefault(inner, [0, 0])
        outers[outer][inner][0] += v; outers[outer][inner][1] += o
    for outer, inners in outers.items():
        crs = {k: (o / v) for k, (v, o) in inners.items() if v >= MIN_V}
        if len(crs) < 2: continue
        local_best = max(crs, key=crs.get)
        if local_best != global_best:
            flips.append((outer, local_best, crs))
    if flips:
        print("  ⚠️ ПАРАДОКС — внутри этих срезов лидер переворачивается:")
        for outer, lb, crs in flips[:8]:
            print(f"    {outer:24} лучший='{lb}' " + ", ".join(f"{k} {100*c:.2f}%" for k,c in crs.items()))
    else:
        print("  ✅ парадокса нет — вывод устойчив во всех срезах")


# ---------- 3. ПУАССОНОВСКАЯ ДЕТЕКЦИЯ АНОМАЛИЙ ДНЯ ----------
def poisson_anomalies(file="00_timeseries.csv"):
    header, data = load(DIR / file)
    oi = header.index("ecommercePurchases"); di = header.index("date")
    ri = header.index("ecommerceRevenue")
    orders = np.array([num(r[oi]) for r in data])
    dates = [r[di] for r in data]
    mu = orders.mean()
    # точные пуассоновские лимиты 99.7% (аналог 3σ, но для счётных данных)
    ucl = stats.poisson.ppf(0.9985, mu)
    lcl = stats.poisson.ppf(0.0015, mu)
    print(f"\n### Пуассоновская детекция аномалий дня (заказы/день, μ={mu:.1f})")
    print(f"  Контрольные лимиты (99.7%, точный Пуассон): LCL={lcl:.0f}  UCL={ucl:.0f}")
    hi = [(dates[i], int(orders[i])) for i in range(len(orders)) if orders[i] > ucl]
    lo = [(dates[i], int(orders[i])) for i in range(len(orders)) if orders[i] < lcl]
    if hi:
        print("  🟢 аномально ВЫСОКИЕ дни (искать причину — что сработало):")
        for dt, o in hi: print(f"     {dt}: {o} заказов")
    if lo:
        print(f"  🔴 аномально НИЗКИЕ дни ({len(lo)} шт, искать поломку/причину):")
        for dt, o in lo[:10]: print(f"     {dt}: {o} заказов")
    if not hi and not lo:
        print("  ✅ выбросов за контрольные лимиты нет — процесс стабилен")


def main():
    print("=" * 78)
    print("СТАТИСТИЧЕСКИ ЧЕСТНЫЙ АНАЛИЗ (методы из дип-резерча 08.07.2026)")
    print("=" * 78)
    # Байесовский рейтинг ключевых срезов
    bayes_rank("01_traffic.csv",   1, "Источники трафика")
    bayes_rank("03_device.csv",    1, "Устройства")
    bayes_rank("04_gender.csv",    1, "Пол")
    bayes_rank("08_landing.csv",   1, "Входные страницы (топ)")
    bayes_rank("13_newvsret.csv",  1, "Новый / вернувшийся")
    bayes_rank("07_city.csv",      1, "Города")
    # Simpson
    simpson("x_source_device.csv", 0, 1, "устройство внутри источников")
    # Пуассон
    poisson_anomalies()
    print("\n" + "=" * 78)
    print("ЧИТАТЬ ТАК: P(лучше)≥0.90 = уверенно выше среднего; ≤0.10 = уверенно ниже;")
    print("между = НЕ отличить от среднего (наш прежний 🟢/🔴 мог быть шумом).")


if __name__ == "__main__":
    main()
