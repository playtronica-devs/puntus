#!/usr/bin/env bash
# metrika-pull.sh — тянет агрегаты Яндекс.Метрики (Stat API) и дописывает
# строку в data/mirrors/metrica-timeseries.csv. Заменяет ручной браузерный скрап.
#
# Токен: файл ~/ProjectData/Puntus/ym_token.txt (вне git) или переменная $YM_TOKEN.
# Токен получается через OAuth (client_id приложения "Puntus API": f7cfac76fa494e07975abee9fb7da0b0).
#
# Использование:
#   bash scripts/metrika-pull.sh                 # последняя ПОЛНАЯ неделя (пн–вс)
#   bash scripts/metrika-pull.sh 2026-06-30 2026-07-06 [week|month] ["заметка"]
#
# RULE P1/P2: строка всегда с периодом, датой замера и источником.
set -euo pipefail

COUNTER=108324634
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CSV="$REPO/data/mirrors/metrica-timeseries.csv"
TOKEN_FILE="${YM_TOKEN_FILE:-$HOME/ProjectData/Puntus/ym_token.txt}"

# --- токен ---
TOKEN="${YM_TOKEN:-}"
if [[ -z "$TOKEN" && -f "$TOKEN_FILE" ]]; then TOKEN="$(cat "$TOKEN_FILE")"; fi
if [[ -z "$TOKEN" ]]; then
  echo "ОШИБКА: нет токена. Положи в $TOKEN_FILE или экспортируй YM_TOKEN=..." >&2
  exit 1
fi

# --- период ---
if [[ -n "${1:-}" && -n "${2:-}" ]]; then
  DATE1="$1"; DATE2="$2"
else
  # последняя полная неделя: прошлый понедельник .. прошлое воскресенье
  DATE1="$(date -v-mon -v-7d +%Y-%m-%d 2>/dev/null || date -d 'last monday -7 days' +%Y-%m-%d)"
  DATE2="$(date -v-sun +%Y-%m-%d 2>/dev/null || date -d 'last sunday' +%Y-%m-%d)"
fi
PTYPE="${3:-week}"
NOTE="${4:-авто-выгрузка Stat API}"
MEASURED="$(date +%Y-%m-%d)"

echo "→ Метрика #$COUNTER, период $DATE1..$DATE2 ($PTYPE)" >&2

export YM_RESP="$(curl -s "https://api-metrika.yandex.net/stat/v1/data" \
  -H "Authorization: OAuth $TOKEN" \
  --data-urlencode "ids=$COUNTER" \
  --data-urlencode "metrics=ym:s:visits,ym:s:users,ym:s:bounceRate,ym:s:ecommercePurchases,ym:s:ecommerceRevenue" \
  --data-urlencode "date1=$DATE1" --data-urlencode "date2=$DATE2" -G)"

# --- разбор + дозапись (python: считает AOV, экранирует, проверяет ошибки) ---
python3 - "$CSV" "$DATE1" "$DATE2" "$PTYPE" "$MEASURED" "$COUNTER" "$NOTE" <<'PY'
import sys, json, csv, os
csv_path, d1, d2, ptype, measured, counter, note = sys.argv[1:8]
data = json.loads(os.environ["YM_RESP"])
if data.get("errors"):
    sys.exit("ОШИБКА API: %s" % json.dumps(data["errors"], ensure_ascii=False))
visits, users, bounce, orders, revenue = data["totals"]
aov = round(revenue / orders) if orders else ""
row = [f"{d1}..{d2}", ptype, measured,
       int(visits), int(users), round(bounce, 2),
       "", "", "",                       # funnel_view/cart/purchase — только UI
       int(orders), round(revenue), aov, "",
       f"metrica#{counter} (API)", note]
with open(csv_path, "a", newline="", encoding="utf-8") as f:
    csv.writer(f).writerow(row)
print("✅ дописано:", d1, "..", d2, "| визиты", int(visits),
      "| заказы", int(orders), "| выручка", round(revenue), "| AOV", aov)
PY
