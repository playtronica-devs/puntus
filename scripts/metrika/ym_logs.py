#!/usr/bin/env python3
"""
ym_logs.py — сырьё Яндекс.Метрики через Logs API (визиты/хиты построчно).
Для LTV, когорт, пути клиента — того, чего нет в агрегатах Stat API.

Асинхронно: создаёт запрос → ждёт готовности → качает TSV → чистит.
Тяжёлое → в ~/ProjectData/Puntus/metrica-logs/ (вне git).

Запуск:
  python3 scripts/metrika/ym_logs.py                         # визиты за 30 дней
  python3 scripts/metrika/ym_logs.py visits 2026-06-01 2026-06-30
  python3 scripts/metrika/ym_logs.py hits   2026-06-01 2026-06-30
"""
import os, sys, json, time, urllib.parse, urllib.request, urllib.error, pathlib

COUNTER = "108324634"
TOKEN = os.environ.get("YM_TOKEN") or \
    open(os.path.expanduser("~/ProjectData/Puntus/ym_token.txt")).read().strip()
OUTDIR = pathlib.Path(os.path.expanduser("~/ProjectData/Puntus/metrica-logs"))
OUTDIR.mkdir(parents=True, exist_ok=True)

SOURCE = sys.argv[1] if len(sys.argv) > 1 else "visits"
D1 = sys.argv[2] if len(sys.argv) > 2 else None
D2 = sys.argv[3] if len(sys.argv) > 3 else None
if not D1:
    import datetime
    today = datetime.date.today()
    D2 = str(today - datetime.timedelta(days=1))
    D1 = str(today - datetime.timedelta(days=30))

# Поля под анализ денег/пути клиента (визиты)
FIELDS = {
    "visits": ("ym:s:date,ym:s:clientID,ym:s:visitID,ym:s:lastTrafficSource,ym:s:deviceCategory,"
               "ym:s:regionCity,ym:s:startURL,ym:s:visitDuration,ym:s:pageViews,ym:s:isNewUser,"
               "ym:s:goalsID"),
    "hits": ("ym:pv:date,ym:pv:clientID,ym:pv:URLPath,ym:pv:referer,ym:pv:deviceCategory,ym:pv:regionCity"),
}[SOURCE]

BASE = f"https://api-metrika.yandex.net/management/v1/counter/{COUNTER}"
HDR = {"Authorization": "OAuth " + TOKEN}


def req(url, method="GET"):
    r = urllib.request.Request(url, headers=HDR, method=method)
    try:
        return json.load(urllib.request.urlopen(r, timeout=120))
    except urllib.error.HTTPError as e:
        return {"errors": e.read().decode()[:300], "code": e.code}


def main():
    print(f"→ Logs API: {SOURCE} {D1}..{D2}")

    # 1) проверить, что период потянет (оценка)
    ev = req(f"{BASE}/logrequests/evaluate?" + urllib.parse.urlencode(
        {"date1": D1, "date2": D2, "source": SOURCE, "fields": FIELDS}))
    poss = ev.get("log_request_evaluation", {}).get("possible")
    print("  оценка possible:", poss, ev.get("errors", ""))

    # 2) создать запрос
    cr = req(f"{BASE}/logrequests?" + urllib.parse.urlencode(
        {"date1": D1, "date2": D2, "source": SOURCE, "fields": FIELDS}), method="POST")
    if cr.get("errors"):
        sys.exit("ОШИБКА создания: " + str(cr["errors"]))
    rid = cr["log_request"]["request_id"]
    print("  request_id:", rid)

    # 3) ждать готовности
    for _ in range(60):
        st = req(f"{BASE}/logrequest/{rid}")
        status = st.get("log_request", {}).get("status")
        print("  status:", status)
        if status == "processed":
            parts = st["log_request"]["parts"]
            break
        if status in ("canceled", "processing_failed"):
            sys.exit("запрос не выполнен: " + status)
        time.sleep(15)
    else:
        sys.exit("таймаут ожидания")

    # 4) скачать части
    out = OUTDIR / f"{SOURCE}_{D1}_{D2}.tsv"
    with open(out, "wb") as f:
        for p in parts:
            n = p["part_number"]
            url = f"{BASE}/logrequest/{rid}/part/{n}/download"
            r = urllib.request.Request(url, headers=HDR)
            data = urllib.request.urlopen(r, timeout=300).read()
            if n > 0:  # у частей >0 срезаем повторный заголовок
                data = data.split(b"\n", 1)[1] if b"\n" in data else data
            f.write(data)
            print(f"  часть {n}: {len(data)} байт")

    # 5) очистить запрос на стороне Яндекса
    req(f"{BASE}/logrequest/{rid}/clean", method="POST")
    lines = sum(1 for _ in open(out, "rb")) - 1
    print(f"✅ {out}  (~{lines} строк)")


if __name__ == "__main__":
    main()
