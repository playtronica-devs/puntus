#!/usr/bin/env python3
"""
validate_levers.py — доказать, что мы нашли СИЛЬНЕЙШИЕ рычаги (а не первые попавшиеся).
Работает на сыром Logs API (сессии). 4 теста уверенности:

  1. ИСЧЕРПЫВАЮЩИЙ СКАН — перебор всех сегментов (одиночные + пары) по возвратным ₽.
     Если ручной топ-5 = алгоритмический топ-5 → ничего крупнее не пропустили.
  2. ДЕКОНФАУНДИНГ — мультивариантная логистическая регрессия: какой драйвер сильнейший
     НЕЗАВИСИМО (пересечения соц/новые/мобайл/spring убраны). Odds ratio + 95% CI.
  3. ПЕРЕСЕЧЕНИЯ — соц/новые/spring/мобайл это во многом ОДНИ сессии → возвраты не складываются.
  4. СТАБИЛЬНОСТЬ — рычаг держится в обеих половинах периода (не артефакт даты).

Запуск: python3 scripts/metrika/validate_levers.py
"""
import os, csv
from urllib.parse import urlparse
from collections import Counter, defaultdict
import numpy as np, pandas as pd
import statsmodels.formula.api as smf

LOG = os.path.expanduser("~/ProjectData/Puntus/metrica-logs/visits_2026-03-30_2026-07-06.tsv")
PURCHASE = "543386484"; AOV = 20808
DEVMAP = {"1": "desktop", "2": "mobile", "3": "tablet"}


def load():
    rows = list(csv.reader(open(LOG, encoding="utf-8"), delimiter="\t"))
    h = rows[0]; I = {c.split(":")[-1]: i for i, c in enumerate(h)}
    recs = []
    for r in rows[1:]:
        path = urlparse(r[I["startURL"]]).path.rstrip("/") or "/"
        bucket = "/" + path.split("/")[1] if path != "/" else "/"
        recs.append(dict(
            date=r[I["date"]],
            source=r[I["lastTrafficSource"]],
            device=DEVMAP.get(r[I["deviceCategory"]], "other"),
            city=r[I["regionCity"]],
            landing=bucket,
            isnew=int(r[I["isNewUser"]]),
            pv=float(r[I["pageViews"]] or 0),
            dur=float(r[I["visitDuration"]] or 0),
            buy=1 if PURCHASE in r[I["goalsID"]] else 0,
        ))
    return pd.DataFrame(recs)


def site_cr(df): return df.buy.mean()


# ---------- ТЕСТ 1: исчерпывающий скан ----------
def scan(df):
    scr = site_cr(df)
    print("\n" + "="*74)
    print(f"ТЕСТ 1 — ИСЧЕРПЫВАЮЩИЙ СКАН (site CR {100*scr:.2f}%, порог: ≥300 визитов)")
    print("="*74)
    rows = []
    dims = ["source", "device", "city", "landing"]
    # одиночные
    for d in dims:
        for val, g in df.groupby(d):
            v = len(g); o = g.buy.sum()
            if v < 300: continue
            rec = max(0, scr - o/v) * v * AOV
            rows.append((f"{d}={val}", v, o, o/v, rec))
    # пары (ключевые)
    for d1, d2 in [("source","landing"),("source","device"),("landing","device"),("source","isnew")]:
        for (a,b), g in df.groupby([d1,d2]):
            v = len(g); o = g.buy.sum()
            if v < 300: continue
            rec = max(0, scr - o/v) * v * AOV
            rows.append((f"{d1}={a} & {d2}={b}", v, o, o/v, rec))
    rows.sort(key=lambda x: -x[4])
    print(f"{'сегмент (недоконвертит)':44} {'виз':>6} {'зак':>4} {'CR%':>5} {'возврат₽':>10}")
    for name, v, o, cr, rec in rows[:15]:
        print(f"{name:44} {v:>6} {int(o):>4} {100*cr:>4.2f} {rec/1000:>8.0f}К")
    return rows


# ---------- ТЕСТ 2: деконфаундинг ----------
def deconfound(df):
    print("\n" + "="*74)
    print("ТЕСТ 2 — ДЕКОНФАУНДИНГ (логистическая регрессия, независимый эффект)")
    print("="*74)
    # только реальные каналы привлечения; internal=self-referral убираем; планшеты (0 покупок) исключаем
    d = df[df.source.isin(["social","direct","organic","referral"]) & df.device.isin(["desktop","mobile"])].copy()
    d["src"] = d.source.astype("category")
    d["dev"] = d.device.astype("category")
    d["land"] = d.landing.where(d.landing.isin(["/","/spring","/rings","/treasures","/clothes"]),"other").astype("category")
    # референсы: direct / desktop / "/"
    d["src"] = d.src.cat.reorder_categories(["direct"]+[c for c in d.src.cat.categories if c!="direct"])
    d["dev"] = d.dev.cat.reorder_categories(["desktop"]+[c for c in d.dev.cat.categories if c!="desktop"])
    m = smf.logit("buy ~ C(src) + C(dev) + isnew + C(land)", data=d).fit(disp=0)
    orr = np.exp(m.params); ci = np.exp(m.conf_int())
    print("Драйвер (эффект на ШАНС покупки, controlling for остальных):")
    print(f"{'фактор':30} {'odds ratio':>11} {'95% CI':>18} {'p':>7}")
    for name in m.params.index:
        if name == "Intercept": continue
        lbl = (name.replace("C(src)[T.","источник=").replace("C(dev)[T.","устройство=")
                   .replace("C(land)[T.","лендинг=").replace("]","").replace("isnew","новый_юзер"))
        star = "  ←" if m.pvalues[name] < 0.05 else ""
        print(f"{lbl:30} {orr[name]:>10.2f}x [{ci.loc[name,0]:>5.2f};{ci.loc[name,1]:>5.2f}] {m.pvalues[name]:>7.3f}{star}")
    print("\nЧитать: OR<1 = снижает шанс покупки НЕЗАВИСИМО от других. Самый сильный независимый рычаг = минимальный OR со звёздочкой.")
    return m


# ---------- ТЕСТ 3: пересечения ----------
def overlap(df):
    print("\n" + "="*74)
    print("ТЕСТ 3 — ПЕРЕСЕЧЕНИЯ (возвраты НЕ складываются — это одни сессии)")
    print("="*74)
    soc = df.source == "social"; new = df.isnew == 1
    spr = df.landing == "/spring"; mob = df.device == "mobile"
    print(f"Соц-сессий: {soc.sum()}")
    print(f"  из них новых:      {(soc&new).sum():>6} ({100*(soc&new).sum()/soc.sum():.0f}%)")
    print(f"  из них на /spring: {(soc&spr).sum():>6} ({100*(soc&spr).sum()/soc.sum():.0f}%)")
    print(f"  из них мобайл:     {(soc&mob).sum():>6} ({100*(soc&mob).sum()/soc.sum():.0f}%)")
    core = soc & new & mob
    print(f"\nЯдро утечки (соц ∩ новые ∩ мобайл): {core.sum()} сессий, CR {100*df[core].buy.mean():.2f}%")
    print(f"  → ЭТО и есть один рычаг, а не три. /spring — его лендинг.")
    # честный потолок: всё, что ниже среднего, поднять до среднего
    scr = site_cr(df)
    under = df.groupby(["source","landing","device","isnew"]).buy.agg(["size","mean"])
    ceil = ((scr - under["mean"]).clip(lower=0) * under["size"] * AOV).sum()
    print(f"\nЧЕСТНЫЙ ПОТОЛОК (все под-средние сегменты → среднее, без двойного счёта): ~{ceil/1e6:.1f} млн ₽ / 90д")


# ---------- ТЕСТ 4: стабильность ----------
def stability(df):
    print("\n" + "="*74)
    print("ТЕСТ 4 — СТАБИЛЬНОСТЬ ВО ВРЕМЕНИ (рычаг держится в обеих половинах?)")
    print("="*74)
    med = sorted(df.date)[len(df)//2]
    h1, h2 = df[df.date <= med], df[df.date > med]
    scr1, scr2 = site_cr(h1), site_cr(h2)
    print(f"H1 (до {med}): {len(h1)} сессий, CR {100*scr1:.2f}%  |  H2: {len(h2)} сессий, CR {100*scr2:.2f}%")
    print(f"\n{'рычаг':34} {'H1 CR%':>7} {'H2 CR%':>7}  вердикт")
    levers = {"источник=social": df.source=="social", "новые юзеры": df.isnew==1,
              "/spring": df.landing=="/spring", "устройство=ПК": df.device=="desktop",
              "вернувшиеся": df.isnew==0, "мужчины(нет в логах)": None}
    for name, mask in levers.items():
        if mask is None: continue
        c1 = h1[mask.loc[h1.index]].buy.mean(); c2 = h2[mask.loc[h2.index]].buy.mean()
        # стабилен, если в обеих половинах на той же стороне от site
        side1 = "выше" if c1 > scr1 else "ниже"; side2 = "выше" if c2 > scr2 else "ниже"
        ok = "✅ стабилен" if side1 == side2 else "⚠️ НЕустойчив"
        print(f"{name:34} {100*c1:>6.2f} {100*c2:>6.2f}  {ok} ({side1}/{side2})")


def main():
    df = load()
    print(f"Загружено {len(df)} сессий, {df.buy.sum()} покупок, site CR {100*site_cr(df):.2f}%")
    scan(df)
    deconfound(df)
    overlap(df)
    stability(df)
    print("\n" + "="*74)
    print("ИТОГ: если топ скана = ручной топ, драйвер деконфаундинга ясен, потолок понятен")
    print("и рычаги стабильны — тогда МЫ ЗНАЕМ, что нашли сильнейшие, а не первые попавшиеся.")


if __name__ == "__main__":
    main()
