"""Веб-дашборд: графики капитала и цены, журнал сделок, баланс и вывод.

Запуск:  python dashboard.py
Открой:  http://localhost:8000

Данные берутся из equity.csv и trades.csv, которые пишет бот. Дашборд можно
держать запущенным параллельно с ботом — он просто читает файлы.
"""
from __future__ import annotations

from flask import Flask, jsonify, render_template_string

import journal
from config import Config

app = Flask(__name__)
cfg = Config.load()

PAGE = """
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading Bot — дашборд</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root { color-scheme: dark; }
  body { font-family: -apple-system, system-ui, sans-serif; margin: 0; background:#0e1117; color:#e6e6e6; }
  header { padding: 16px 24px; background:#161b22; border-bottom:1px solid #222; }
  h1 { font-size: 18px; margin:0; }
  .sub { color:#8b949e; font-size:12px; margin-top:4px; }
  .cards { display:flex; flex-wrap:wrap; gap:12px; padding:16px 24px; }
  .card { background:#161b22; border:1px solid #222; border-radius:10px; padding:14px 18px; min-width:150px; }
  .card .label { color:#8b949e; font-size:12px; }
  .card .value { font-size:22px; font-weight:600; margin-top:4px; }
  .pos { color:#3fb950; } .neg { color:#f85149; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; padding:0 24px 24px; }
  .panel { background:#161b22; border:1px solid #222; border-radius:10px; padding:16px; }
  .panel h2 { font-size:14px; margin:0 0 12px; color:#c9d1d9; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid #222; }
  th { color:#8b949e; font-weight:500; }
  .full { grid-column: 1 / -1; }
  @media (max-width: 900px){ .grid { grid-template-columns:1fr; } }
</style>
</head>
<body>
<header>
  <h1>🤖 Trading Bot — дашборд</h1>
  <div class="sub">{{ symbols }} · стратегия {{ strategy }} · режим {{ mode }} · обновляется автоматически</div>
</header>
<div id="hint" style="display:none; margin:0 24px; padding:12px 16px; background:#3a2a00; border:1px solid #6b4f00; border-radius:8px; color:#e3b341;"></div>
<div class="cards" id="cards"></div>
<div class="grid">
  <div class="panel full"><h2>Кривая капитала (equity)</h2><canvas id="equityChart" height="90"></canvas></div>
  <div class="panel full"><h2>Цена и сделки</h2><canvas id="priceChart" height="90"></canvas></div>
  <div class="panel full"><h2>Журнал сделок (последние 50)</h2><div id="trades"></div></div>
</div>
<script>
const PRIMARY = "{{ symbol }}";
let equityChart, priceChart;
function money(x){ return (x>=0?'':'-') + '$' + Math.abs(x).toFixed(2); }
function cls(x){ return x>=0?'pos':'neg'; }

async function load(){
  const d = await (await fetch('/api/data')).json();
  // подсказка, если данных ещё нет
  const hint = document.getElementById('hint');
  if(d.equity.length === 0){
    hint.style.display = 'block';
    hint.textContent = '⏳ Данных пока нет. Запущен ли бот (python main.py) в этой же папке? '
      + 'График заполнится после первого опроса рынка (см. POLL_INTERVAL_SECONDS).';
  } else { hint.style.display = 'none'; }
  // карточки
  const c = d.summary;
  document.getElementById('cards').innerHTML = `
    <div class="card"><div class="label">Капитал (equity)</div><div class="value">${money(c.equity)}</div></div>
    <div class="card"><div class="label">Реализованная прибыль</div><div class="value ${cls(c.realized)}">${money(c.realized)}</div></div>
    <div class="card"><div class="label">Нереализованная</div><div class="value ${cls(c.unrealized)}">${money(c.unrealized)}</div></div>
    <div class="card"><div class="label">Сделок / прибыльных</div><div class="value">${c.trades} / ${c.wins}</div></div>
    <div class="card"><div class="label">Выведено на кошелёк</div><div class="value">${money(c.withdrawn)}</div></div>
    <div class="card"><div class="label">В резерве к выводу</div><div class="value">${money(c.reserve)}</div></div>`;

  // equity
  const eLabels = d.equity.map(r => r.time.slice(5,16).replace('T',' '));
  if(!equityChart){
    equityChart = new Chart(document.getElementById('equityChart'), {
      type:'line',
      data:{ labels:eLabels, datasets:[{ label:'Equity, $', data:d.equity.map(r=>r.equity),
        borderColor:'#58a6ff', backgroundColor:'rgba(88,166,255,.1)', fill:true, tension:.2, pointRadius:0 }]},
      options:{ plugins:{legend:{display:false}}, scales:{x:{ticks:{maxTicksLimit:8,color:'#8b949e'}},y:{ticks:{color:'#8b949e'}}} }
    });
  } else { equityChart.data.labels=eLabels; equityChart.data.datasets[0].data=d.equity.map(r=>r.equity); equityChart.update(); }

  // price + маркеры сделок (по основной монете — у разных монет разный масштаб цены)
  const pLabels = d.equity.map(r => r.time.slice(5,16).replace('T',' '));
  const prim = d.trades.filter(t => (t.symbol||PRIMARY) === PRIMARY);
  const buys = prim.filter(t=>t.side==='BUY').map(t=>({x:t.time.slice(5,16).replace('T',' '), y:+t.price}));
  const sells = prim.filter(t=>t.side==='SELL').map(t=>({x:t.time.slice(5,16).replace('T',' '), y:+t.price}));
  if(!priceChart){
    priceChart = new Chart(document.getElementById('priceChart'), {
      type:'line',
      data:{ labels:pLabels, datasets:[
        { label:'Цена', data:d.equity.map(r=>r.price), borderColor:'#8b949e', pointRadius:0, tension:.2 },
        { label:'Покупки', data:buys, type:'scatter', backgroundColor:'#3fb950', pointRadius:5 },
        { label:'Продажи', data:sells, type:'scatter', backgroundColor:'#f85149', pointRadius:5 }
      ]},
      options:{ plugins:{legend:{labels:{color:'#8b949e'}}}, scales:{x:{ticks:{maxTicksLimit:8,color:'#8b949e'}},y:{ticks:{color:'#8b949e'}}} }
    });
  } else {
    priceChart.data.labels=pLabels;
    priceChart.data.datasets[0].data=d.equity.map(r=>r.price);
    priceChart.data.datasets[1].data=buys; priceChart.data.datasets[2].data=sells;
    priceChart.update();
  }

  // таблица сделок
  const rows = d.trades.slice(-50).reverse().map(t=>`<tr>
    <td>${t.time.slice(0,16).replace('T',' ')}</td>
    <td>${t.symbol||PRIMARY}</td>
    <td class="${t.side==='BUY'?'pos':'neg'}">${t.side}</td>
    <td>${t.reason}</td><td>$${(+t.price).toFixed(2)}</td>
    <td>${(+t.qty).toFixed(6)}</td><td>$${(+t.quote).toFixed(2)}</td>
    <td class="${cls(+t.realized_pnl)}">${t.side==='SELL'?money(+t.realized_pnl):''}</td></tr>`).join('');
  document.getElementById('trades').innerHTML =
    `<table><thead><tr><th>Время</th><th>Монета</th><th>Сторона</th><th>Причина</th><th>Цена</th><th>Кол-во</th><th>Сумма</th><th>P&L</th></tr></thead><tbody>${rows}</tbody></table>`;
}
load(); setInterval(load, 15000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    mode = "DRY_RUN" if cfg.dry_run else ("TESTNET" if cfg.testnet else "РЕАЛЬНЫЙ")
    return render_template_string(
        PAGE, symbols=", ".join(cfg.symbols), symbol=cfg.symbol,
        strategy=cfg.strategy, mode=mode,
    )


@app.route("/api/data")
def data():
    equity = journal.read_csv(journal.EQUITY_CSV)
    trades = journal.read_csv(journal.TRADES_CSV)
    last = equity[-1] if equity else {}
    wins = sum(1 for t in trades if t["side"] == "SELL" and float(t["realized_pnl"]) > 0)
    sells = sum(1 for t in trades if t["side"] == "SELL")
    summary = {
        "equity": float(last.get("equity", cfg.trade_quote_amount)),
        "realized": float(last.get("realized_pnl", 0)),
        "unrealized": float(last.get("unrealized_pnl", 0)),
        "withdrawn": float(last.get("withdrawn", 0)),
        "reserve": float(last.get("reserve", 0)),
        "trades": sells,
        "wins": wins,
    }
    # Не перегружаем график: максимум последние 1000 точек.
    return jsonify({"summary": summary, "equity": equity[-1000:], "trades": trades[-200:]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=cfg.dashboard_port, debug=False)
