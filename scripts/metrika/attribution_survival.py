#!/usr/bin/env python3
"""
attribution_survival.py — уровень B методологии на сырье сессий:

  A. МАРКОВСКАЯ АТТРИБУЦИЯ (removal effects, первого порядка) — реальный вклад канала
     в цепочке касаний vs last-click / first-click. Отвечает: ассистирует ли инста
     покупкам, даже если по последнему клику слабая (риск «убить» верх воронки).
  B. SURVIVAL / TIME-TO-PURCHASE (Kaplan-Meier, реализован на numpy) — сколько дней и
     касаний до покупки, по каналу первого касания. Отвечает: сколько «догревать» новый трафик.

Обе реализованы без тяжёлых зависимостей (numpy). Запуск: python3 scripts/metrika/attribution_survival.py
"""
import os, csv
from collections import defaultdict
import numpy as np

LOG = os.path.expanduser("~/ProjectData/Puntus/metrica-logs/visits_2026-03-30_2026-07-06.tsv")
PURCHASE = "543386484"
MERGE = {"messenger": "other", "recommend": "other", "ad": "other", "undefined": "other"}


def journeys():
    rows = list(csv.reader(open(LOG, encoding="utf-8"), delimiter="\t"))
    I = {c.split(":")[-1]: i for i, c in enumerate(rows[0])}
    by = defaultdict(list)
    for r in rows[1:]:
        src = r[I["lastTrafficSource"]]; src = MERGE.get(src, src)
        by[r[I["clientID"]]].append((r[I["date"]], src, 1 if PURCHASE in r[I["goalsID"]] else 0))
    js = []
    for cid, sess in by.items():
        sess.sort(key=lambda x: x[0])
        path = []; converted = False; conv_date = None; first_date = sess[0][0]
        for date, src, buy in sess:
            path.append(src)
            if buy:
                converted = True; conv_date = date; break
        js.append(dict(path=path, conv=converted, first=first_date,
                       last=sess[-1][0], conv_date=conv_date, n_touch=len(path)))
    return js


# ---------- A. МАРКОВ ----------
def markov(js):
    chans = sorted({c for j in js for c in j["path"]})
    states = ["start"] + chans + ["conv", "null"]
    idx = {s: i for i, s in enumerate(states)}
    n = len(states)
    T = np.zeros((n, n))
    for j in js:
        seq = ["start"] + j["path"] + (["conv"] if j["conv"] else ["null"])
        for a, b in zip(seq[:-1], seq[1:]):
            T[idx[a], idx[b]] += 1
    row = T.sum(1, keepdims=True); row[row == 0] = 1
    P = T / row
    P[idx["conv"]] = 0; P[idx["conv"], idx["conv"]] = 1
    P[idx["null"]] = 0; P[idx["null"], idx["null"]] = 1

    def conv_prob(Pm):
        trans = [i for i in range(n) if states[i] not in ("conv", "null")]
        ab = [idx["conv"], idx["null"]]
        Q = Pm[np.ix_(trans, trans)]; R = Pm[np.ix_(trans, ab)]
        Nf = np.linalg.inv(np.eye(len(trans)) - Q)
        B = Nf @ R
        return B[trans.index(idx["start"]), 0]  # P(старт → conv)

    base = conv_prob(P)
    removal = {}
    for c in chans:
        Pc = P.copy()
        # удалить канал: все переходы В канал c уводим в null
        col = idx[c]
        for i in range(n):
            if Pc[i, col] > 0:
                Pc[i, idx["null"]] += Pc[i, col]; Pc[i, col] = 0
        Pc[col] = 0; Pc[col, idx["null"]] = 1
        removal[c] = (base - conv_prob(Pc)) / base if base else 0

    total_conv = sum(j["conv"] for j in js)
    s = sum(v for v in removal.values() if v > 0) or 1
    markov_attr = {c: max(0, removal[c]) / s * total_conv for c in chans}
    # эвристики для сравнения
    first = defaultdict(float); last = defaultdict(float)
    for j in js:
        if j["conv"]:
            first[j["path"][0]] += 1; last[j["path"][-1]] += 1

    print("=" * 74)
    print(f"A. МАРКОВСКАЯ АТТРИБУЦИЯ ({total_conv} конверсий, база P(conv)={base:.4f})")
    print("=" * 74)
    print(f"{'канал':12} {'Марков':>8} {'last-click':>11} {'first-click':>12}  сигнал")
    for c in chans:
        m, l, f = markov_attr[c], last[c], first[c]
        flag = ""
        if l >= 3 and m > l * 1.25: flag = "🟢 ассистирует (Марков>last — не резать!)"
        elif l >= 3 and m < l * 0.75: flag = "🔴 переоценён last-click"
        print(f"{c:12} {m:>8.1f} {l:>11.1f} {f:>12.1f}  {flag}")
    print("\nЧитать: если Марков заметно > last-click — канал ПОМОГАЕт покупкам в цепочке,")
    print("даже когда закрывает продажу другой. Резать такой канал = потерять ассистированные продажи.")


# ---------- B. SURVIVAL ----------
def days_between(d1, d2):
    from datetime import date
    a = date(*map(int, d1.split("-"))); b = date(*map(int, d2.split("-")))
    return (b - a).days


def km(times, events):
    """Kaplan-Meier: возвращает список (t, S(t))."""
    order = np.argsort(times)
    times = np.array(times)[order]; events = np.array(events)[order]
    uniq = sorted(set(times[events == 1]))
    S = 1.0; curve = [(0, 1.0)]
    for t in uniq:
        n_risk = np.sum(times >= t)
        d = np.sum((times == t) & (events == 1))
        if n_risk > 0:
            S *= (1 - d / n_risk); curve.append((t, S))
    return curve


def survival(js):
    print("\n" + "=" * 74)
    print("B. TIME-TO-PURCHASE (Kaplan-Meier) — сколько догревать новый трафик")
    print("=" * 74)
    # first-touch канал → журналы
    END = max(j["last"] for j in js)
    groups = defaultdict(lambda: ([], []))  # chan -> (times, events)
    touch_buy = []
    for j in js:
        ft = j["path"][0]
        if j["conv"]:
            t = days_between(j["first"], j["conv_date"]); ev = 1
            touch_buy.append(j["n_touch"])
        else:
            t = max(days_between(j["first"], j["last"]), 0); ev = 0
        groups[ft][0].append(t); groups[ft][1].append(ev)

    # доля покупок в первый день vs позже
    same = sum(1 for j in js if j["conv"] and days_between(j["first"], j["conv_date"]) == 0)
    later = sum(1 for j in js if j["conv"] and days_between(j["first"], j["conv_date"]) > 0)
    print(f"Покупки в ДЕНЬ первого визита: {same}  |  позже (догрев сработал): {later} "
          f"({100*later/(same+later):.0f}% покупок — отложенные)")
    tb = np.array(touch_buy)
    print(f"Касаний до покупки: медиана {np.median(tb):.0f}, среднее {tb.mean():.1f}, "
          f"доля за 1 касание: {100*np.mean(tb==1):.0f}%, за ≥3: {100*np.mean(tb>=3):.0f}%")

    print(f"\n{'канал 1-го касания':20} {'покупателей':>11} {'медиана дней*':>13} {'% отложенных':>13}")
    for ch, (times, events) in sorted(groups.items(), key=lambda x: -sum(x[1][1])):
        nb = sum(events)
        if nb < 5: continue
        conv_delays = [t for t, e in zip(times, events) if e == 1]
        med = np.median([d for d in conv_delays if d >= 0]) if conv_delays else 0
        deferred = 100 * np.mean([d > 0 for d in conv_delays]) if conv_delays else 0
        print(f"{ch:20} {nb:>11} {med:>13.0f} {deferred:>12.0f}%")
    print("* медиана дней до покупки среди купивших этого канала (0 = в тот же день)")
    print("\nВывод: каналы с высокой долей отложенных покупок = там ремаркетинг/догрев окупается;")
    print("где почти все в тот же день — там решает первое касание (лендинг/оффер).")


def main():
    js = journeys()
    print(f"Загружено {len(js)} клиентских путей, {sum(j['conv'] for j in js)} с покупкой, "
          f"{sum(1 for j in js if j['n_touch']>1)} мультитач\n")
    markov(js)
    survival(js)


if __name__ == "__main__":
    main()
