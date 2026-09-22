#!/usr/bin/env python3
"""Трекер готовности бота к реальным деньгам.

Читает equity.csv / trades.csv / логи бота и БД freqtrade-эталона, проверяет
числовые ворота выхода в реал и печатает по каждому GREEN / RED / n/a.

Запуск (на VM, где лежат данные):
    python3 go_live_check.py                 # дефолтные пути /opt/trading-bot
    python3 go_live_check.py --dir . --since 2026-09-22
    python3 go_live_check.py --json          # машиночитаемо (для таймера)

Только stdlib. Рыночную просадку BTC тянет с публичного api.binance.com.
Ничего не меняет — только читает. Пороги — в GATES ниже, правь под себя.
"""
from __future__ import annotations
import argparse, csv, json, os, subprocess, sys, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

# ── Пороги (одно место для настройки) ──────────────────────────────────
MIN_DAYS          = 30      # A: длительность теста, дней
MIN_MARKET_DROP   = 15.0    # A2: рынок BTC должен просесть хотя бы на, %
MAX_BOT_DD        = 25.0    # B: макс. просадка equity бота, %
MAX_DD_RATIO      = 0.8     # B2: просадка бота / просадка рынка
MAX_GAP_H         = 1.0     # A/E: дыра в данных, часов
MIN_UPTIME        = 99.0    # E: аптайм, %
WORST_CYCLE_PCT   = -12.0   # D3: худшая закрытая сделка не хуже, %
BENCH_DD_MULT     = 1.2     # D2: DD бота ≤ DD эталона × это
FT_WALLET         = 300.0   # кошелёк freqtrade для нормировки DD
DEFAULT_DIR       = "/opt/trading-bot"
FT_CONTAINER      = "freqtrade-compare"
FT_DB             = "/freqtrade/tradesv3.dryrun.sqlite"

G, R, Y, N = "GREEN", "RED", "WARN", "n/a"

def parse_ts(s: str) -> datetime:
    s = s.strip().replace("Z", "+00:00")
    try: return datetime.fromisoformat(s)
    except ValueError: return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

def max_drawdown(series: list[float]) -> float:
    peak, mdd = None, 0.0
    for v in series:
        peak = v if peak is None else max(peak, v)
        if peak > 0: mdd = max(mdd, (peak - v) / peak * 100)
    return mdd

# ── Загрузка данных бота ───────────────────────────────────────────────
def load_equity(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try: rows.append((parse_ts(r["time"]), float(r["equity"])))
            except (KeyError, ValueError): continue
    rows.sort()
    return rows

def load_trades(path, since):
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try: t = parse_ts(r["time"])
            except (KeyError, ValueError): continue
            if t < since: continue
            out.append(r)
    return out

def fetch_btc_closes(start: datetime, end: datetime):
    closes, cur, endms = [], int(start.timestamp()*1000), int(end.timestamp()*1000)
    while cur < endms:
        url = ("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h"
               f"&startTime={cur}&endTime={endms}&limit=1000")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                kl = json.load(resp)
        except Exception as e:
            print(f"  (не смог получить klines BTC: {e})", file=sys.stderr); break
        if not kl: break
        closes += [float(k[4]) for k in kl]
        nxt = kl[-1][0] + 1
        if nxt <= cur or len(kl) < 1000: break
        cur = nxt
    return closes

def freqtrade_stats(since: datetime):
    """Возвращает (net_pnl, cycles, approx_dd_pct) эталона или None."""
    py = (
        "import sqlite3,json;"
        f"c=sqlite3.connect('{FT_DB}');cur=c.cursor();"
        "rows=cur.execute(\"SELECT close_profit_abs FROM trades WHERE is_open=0 "
        f"AND close_date>='{since:%Y-%m-%d}' ORDER BY close_date\").fetchall();"
        "v=[x[0] or 0 for x in rows];"
        "print(json.dumps({'pnl':round(sum(v),2),'n':len(v),'curve':v}))"
    )
    try:
        out = subprocess.run(["docker","exec","-i",FT_CONTAINER,"python3","-c",py],
                             capture_output=True, text=True, timeout=20)
        d = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    cum, curve = 0.0, []
    for x in d["curve"]:
        cum += x; curve.append(FT_WALLET + cum)
    dd = max_drawdown(curve) if curve else 0.0
    return d["pnl"], d["n"], dd

# ── Ворота ─────────────────────────────────────────────────────────────
def evaluate(args):
    since = parse_ts(args.since + "T00:00:00+00:00") if len(args.since) == 10 else parse_ts(args.since)
    eq = load_equity(f"{args.dir}/equity.csv")
    eq = [(t, v) for t, v in eq if t >= since] or eq
    tr = load_trades(f"{args.dir}/trades.csv", since)
    gates = []

    if not eq:
        return [("A", R, "нет данных equity.csv")], since
    t0, t1 = eq[0][0], eq[-1][0]
    days = (t1 - t0).total_seconds() / 86400
    gates.append(("A  длительность", G if days >= MIN_DAYS else R,
                  f"{days:.1f} дн (нужно ≥{MIN_DAYS})"))

    # дыры / аптайм
    span = (t1 - t0).total_seconds()
    gaps = sum((eq[i][0]-eq[i-1][0]).total_seconds() for i in range(1, len(eq))
               if (eq[i][0]-eq[i-1][0]).total_seconds() > MAX_GAP_H*3600)
    uptime = (1 - gaps/span)*100 if span > 0 else 0.0
    gates.append(("E  аптайм", G if uptime >= MIN_UPTIME else R,
                  f"{uptime:.2f}% (дыр >{MAX_GAP_H}ч суммарно {gaps/3600:.1f}ч)"))

    # рынок и просадки
    closes = fetch_btc_closes(t0, t1)
    mkt_dd = max_drawdown(closes) if closes else 0.0
    gates.append(("A2 откат рынка BTC", G if mkt_dd >= MIN_MARKET_DROP else R,
                  f"{mkt_dd:.1f}% (нужно ≥{MIN_MARKET_DROP}% — иначе тест неполный)"))
    bot_dd = max_drawdown([v for _, v in eq])
    gates.append(("B  просадка бота", G if bot_dd <= MAX_BOT_DD else R,
                  f"{bot_dd:.1f}% (лимит ≤{MAX_BOT_DD}%)"))
    ratio = (bot_dd/mkt_dd) if mkt_dd > 0 else None
    gates.append(("B2 бот/рынок DD", (N if ratio is None else (G if ratio <= MAX_DD_RATIO else R)),
                  ("нет отката рынка" if ratio is None else f"{ratio:.2f} (лимит ≤{MAX_DD_RATIO})")))

    # механизмы: выходы из trades.csv, "входы: нет" из логов
    trail = sum(1 for r in tr if "трейлинг" in r.get("reason",""))
    estop = sum(1 for r in tr if "аварийный" in r.get("reason",""))
    no_entry = grep_logs(args.dir, "входы: нет", since)
    mech_ok = no_entry > 0 and (trail + estop) > 0
    gates.append(("C  механизмы сработали", G if mech_ok else R,
                  f"входы-нет={no_entry}, трейлинг={trail}, авар.стоп={estop}"))

    # худший цикл
    worst = 0.0
    for r in tr:
        if r.get("side") == "SELL":
            try:
                q = float(r["quote"]); pnl = float(r["realized_pnl"])
                if q > 0: worst = min(worst, pnl/(q-pnl)*100 if q-pnl else 0.0)
            except (ValueError, KeyError): pass
    gates.append(("D3 худший цикл", G if worst >= WORST_CYCLE_PCT else R,
                  f"{worst:+.1f}% (лимит ≥{WORST_CYCLE_PCT}%)"))

    # net PnL бота
    bot_pnl = sum(float(r["realized_pnl"]) for r in tr
                  if r.get("side")=="SELL" and r.get("realized_pnl"))
    gates.append(("D  net PnL бота", G if bot_pnl >= 0 else R, f"{bot_pnl:+.2f} USDT"))

    # против эталона
    ft = freqtrade_stats(since)
    if ft is None:
        gates.append(("D2 vs freqtrade", N, "БД эталона недоступна (docker/контейнер)"))
    else:
        ft_pnl, ft_n, ft_dd = ft
        ok = bot_pnl >= ft_pnl and bot_dd <= ft_dd*BENCH_DD_MULT
        gates.append(("D2 vs freqtrade", G if ok else R,
                      f"бот {bot_pnl:+.2f}/DD{bot_dd:.1f}% vs эталон {ft_pnl:+.2f}/DD{ft_dd:.1f}% (n={ft_n})"))
    return gates, since

NOTIFY_STATE = "go-live-notify-state.json"

def notify_telegram(base: str, text: str) -> None:
    """Шлёт в Telegram, если в .env есть TELEGRAM_BOT_TOKEN/CHAT_ID (как alert-check.sh)."""
    token = chat = None
    try:
        with open(f"{base}/.env", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=",1)[1].strip().strip('"\'')
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat = line.split("=",1)[1].strip().strip('"\'')
    except OSError:
        pass
    if not token or not chat:
        print(f"  (уведомление не отправлено: нет TELEGRAM_BOT_TOKEN/CHAT_ID в .env)\n  текст: {text}",
              file=sys.stderr)
        return
    host = os.uname().nodename
    data = urllib.parse.urlencode({"chat_id": chat, "text": f"🤖 go-live ({host}): {text}"}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=15)
    except Exception as e:
        print(f"  (ошибка отправки в Telegram: {e})", file=sys.stderr)

def handle_notify(base: str, gates: list) -> None:
    """Пингует на переходах: все зелёные / откат / ворота позеленело впервые. Без спама."""
    green_now = {g.split()[0] for g, s, _ in gates if s == G}
    go = all(s == G for _, s, _ in gates)
    path = f"{base}/{NOTIFY_STATE}"
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {"was_go": False, "ever_green": []}
    ever = set(st.get("ever_green", []))
    was_go = st.get("was_go", False)

    newly = green_now - ever
    if go and not was_go:
        notify_telegram(base, "✅ ВСЕ ВОРОТА ЗЕЛЁНЫЕ — можно в реал ($300 на BTC, см. правило запуска).")
    elif was_go and not go:
        reds = [g.split()[0] for g, s, _ in gates if s == R]
        notify_telegram(base, f"⚠️ откат: ворота больше не все зелёные. Красные: {', '.join(reds)}")
    elif newly:
        done = len(green_now); total = len(gates)
        notify_telegram(base, f"🟢 позеленело впервые: {', '.join(sorted(newly))} ({done}/{total} ворот)")

    st = {"was_go": go, "ever_green": sorted(ever | green_now)}
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False)
    except OSError as e:
        print(f"  (не смог сохранить {NOTIFY_STATE}: {e})", file=sys.stderr)

def grep_logs(base, needle, since):
    import glob, os
    n = 0
    for f in glob.glob(f"{base}/logs/*/*.log"):
        try:
            d = os.path.basename(os.path.dirname(f))
            if d < since.strftime("%Y-%m-%d"): continue
        except Exception: pass
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                n += sum(1 for line in fh if needle in line)
        except OSError: continue
    return n

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--since", default="2026-09-22", help="начало теста YYYY-MM-DD")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--notify", action="store_true",
                    help="слать в Telegram на переходах (все зелёные / откат / позеленело)")
    args = ap.parse_args()
    gates, since = evaluate(args)

    if args.notify:
        handle_notify(args.dir, gates)

    if args.json:
        print(json.dumps({"since": since.isoformat(),
                          "gates": [{"gate": g, "status": s, "detail": d} for g, s, d in gates],
                          "go": all(s == G for _, s, _ in gates)}, ensure_ascii=False))
        return

    icon = {G:"🟢", R:"🔴", Y:"🟡", N:"⚪"}
    print(f"\n  ГОТОВНОСТЬ К РЕАЛУ — тест с {since:%Y-%m-%d}\n" + "  " + "-"*58)
    for g, s, d in gates:
        print(f"  {icon.get(s,'?')} {g:24} {s:5} {d}")
    reds = [g for g, s, _ in gates if s == R]
    na   = [g for g, s, _ in gates if s == N]
    print("  " + "-"*58)
    if not reds and not na:
        print("  ✅ ВСЕ ЗЕЛЁНЫЕ → можно $300 на BTC (см. правило запуска).")
    else:
        if reds: print(f"  ❌ НЕ ГОТОВ. Красные: {', '.join(x.split()[0] for x in reds)}")
        if na:   print(f"  ⚪ не проверено: {', '.join(x.split()[0] for x in na)}")
    print()

if __name__ == "__main__":
    main()
