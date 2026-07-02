from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .backtest import run_backtest
from .binance import BinanceClient
from .config import DEFAULTS
from .db import (
    init_db,
    insert_backtest_run,
    insert_optimization_result,
    load_candles,
    load_trades,
    recent_backtests,
    recent_optimization,
    upsert_candles,
)
from .optimizer import optimize, walk_forward_optimize
from .strategy import StrategyParams, enrich_candles, params_from_dict
from .timeutils import ms_to_date, parse_date_ms


app = FastAPI(title="BTCUSDT 模拟自动交易系统")


class BacktestRequest(BaseModel):
    symbol: str = DEFAULTS.symbol
    interval: str = DEFAULTS.interval
    start_date: str = DEFAULTS.start_date
    end_date: str = DEFAULTS.end_date
    params: dict[str, Any] = {}


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.post("/api/sync")
def sync_data(
    symbol: str = DEFAULTS.symbol,
    interval: str = DEFAULTS.interval,
    start_date: str = DEFAULTS.start_date,
    end_date: str = DEFAULTS.end_date,
) -> dict[str, Any]:
    rows = BinanceClient().fetch_klines(symbol, interval, start_date, end_date)
    stored = upsert_candles(rows)
    return {"stored": stored, "symbol": symbol.upper(), "interval": interval, "start_date": start_date, "end_date": end_date}


@app.get("/api/candles")
def candles(
    symbol: str = DEFAULTS.symbol,
    interval: str = DEFAULTS.interval,
    start_date: str = DEFAULTS.start_date,
    end_date: str = DEFAULTS.end_date,
) -> dict[str, Any]:
    data = _load_range(symbol, interval, start_date, end_date)
    enriched = enrich_candles(data, StrategyParams())
    return {
        "count": len(enriched),
        "items": [_public_candle(row) for row in enriched],
        "backtests": recent_backtests(5),
        "optimization": recent_optimization(10),
    }


@app.post("/api/backtest")
def backtest(request: BacktestRequest) -> dict[str, Any]:
    start_ms = parse_date_ms(request.start_date)
    data = _load_for_backtest(request.symbol, request.interval, request.end_date)
    if not data:
        raise HTTPException(400, "没有 K 线数据，请先同步 Binance 数据")
    params = params_from_dict(request.params)
    result = run_backtest(data, params, start_trading_ms=start_ms)
    run_id = insert_backtest_run(
        request.symbol.upper(),
        request.interval,
        request.start_date,
        request.end_date,
        params.to_dict(),
        result["metrics"],
        result["trades"],
    )
    return {
        "run_id": run_id,
        "params": params.to_dict(),
        "metrics": result["metrics"],
        "trades": [_public_trade(t) for t in result["trades"]],
        "equity_curve": [row for row in result["equity_curve"] if int(row["time"]) >= start_ms],
        "candles": [_public_candle(row) for row in result["candles"] if int(row["open_time"]) >= start_ms],
    }


@app.post("/api/optimize")
def optimize_api(request: BacktestRequest, max_results: int = Query(20, ge=1, le=50)) -> dict[str, Any]:
    start_ms = parse_date_ms(request.start_date)
    data = _load_for_backtest(request.symbol, request.interval, request.end_date)
    if not data:
        raise HTTPException(400, "没有 K 线数据，请先同步 Binance 数据")
    results = optimize(data, max_results=max_results, start_trading_ms=start_ms)
    for row in results:
        insert_optimization_result(request.symbol.upper(), request.interval, row["params"], row["metrics"])
    return {"count": len(results), "items": results}


@app.post("/api/walk-forward")
def walk_forward_api(
    request: BacktestRequest,
    max_results: int = Query(10, ge=1, le=30),
    train_ratio: float = Query(0.7, ge=0.5, le=0.85),
) -> dict[str, Any]:
    data = _load_range(request.symbol, request.interval, request.start_date, request.end_date)
    if not data:
        raise HTTPException(400, "没有 K 线数据，请先同步 Binance 数据")
    try:
        result = walk_forward_optimize(data, train_ratio=train_ratio, max_results=max_results)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    for row in result["items"]:
        insert_optimization_result(
            request.symbol.upper(),
            request.interval,
            row["params"],
            {"train": row["train_metrics"], "test": row["test_metrics"], "score": row["score"]},
        )
    return {
        "train_count": result["train_count"],
        "test_count": result["test_count"],
        "train_start": ms_to_date(result["train_start"]),
        "train_end": ms_to_date(result["train_end"]),
        "test_start": ms_to_date(result["test_start"]),
        "test_end": ms_to_date(result["test_end"]),
        "count": len(result["items"]),
        "items": result["items"],
    }


@app.get("/api/backtests/{run_id}/trades")
def trades(run_id: int) -> dict[str, Any]:
    return {"items": [_public_trade(t) for t in load_trades(run_id)]}


def _load_range(symbol: str, interval: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    return load_candles(symbol.upper(), interval, parse_date_ms(start_date), parse_date_ms(end_date))


def _load_for_backtest(symbol: str, interval: str, end_date: str) -> list[dict[str, Any]]:
    return load_candles(symbol.upper(), interval, None, parse_date_ms(end_date))


def _public_candle(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "ema",
        "ma",
        "rsi",
        "atr",
        "macd_hist",
        "bb_upper",
        "bb_lower",
        "adx",
        "signal",
    ]
    out = {key: row.get(key) for key in keys}
    out["date"] = ms_to_date(int(row["open_time"]))
    return out


def _public_trade(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if out.get("signal_time") is not None:
        out["signal_date"] = ms_to_date(int(out["signal_time"]))
    out["entry_date"] = ms_to_date(int(out["entry_time"]))
    out["exit_date"] = ms_to_date(int(out["exit_time"]))
    return out


HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BTCUSDT 模拟自动交易系统</title>
  <style>
    :root { color-scheme: dark; --bg:#101216; --panel:#171b22; --line:#2a303a; --text:#e8edf5; --muted:#8d97a8; --green:#25c486; --red:#ff5266; --yellow:#f5c542; --blue:#66b7ff; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--text); }
    header { display:flex; align-items:center; justify-content:space-between; padding:18px 22px; border-bottom:1px solid var(--line); background:#0c0e12; }
    h1 { margin:0; font-size:20px; font-weight:700; letter-spacing:0; }
    main { padding:18px; display:grid; gap:14px; }
    .toolbar, .grid, .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; }
    .toolbar { display:grid; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)); gap:10px; padding:12px; align-items:end; }
    label { display:grid; gap:5px; color:var(--muted); font-size:12px; }
    input { width:100%; border:1px solid var(--line); background:#0d1015; color:var(--text); border-radius:6px; padding:9px; font-size:13px; }
    button { border:1px solid #3b4654; background:#202733; color:var(--text); border-radius:6px; padding:10px 12px; cursor:pointer; font-weight:650; min-height:38px; width:100%; }
    button.primary { background:#1b6b50; border-color:#27936f; }
    button:hover { filter:brightness(1.12); }
    .grid { display:grid; grid-template-columns: repeat(6, 1fr); gap:0; overflow:hidden; }
    .metric { padding:13px; border-right:1px solid var(--line); }
    .metric:last-child { border-right:0; }
    .metric span { display:block; color:var(--muted); font-size:12px; margin-bottom:6px; }
    .metric strong { font-size:20px; }
    .panel { padding:12px; }
    .chart-wrap { height:520px; }
    canvas { width:100%; height:100%; display:block; background:#11151b; border-radius:6px; }
    .split { display:grid; grid-template-columns: 1.1fr .9fr; gap:14px; }
    table { width:100%; border-collapse:collapse; font-size:12px; }
    th, td { border-bottom:1px solid var(--line); padding:8px; text-align:right; white-space:nowrap; }
    th:first-child, td:first-child { text-align:left; }
    th { color:var(--muted); font-weight:600; }
    .pos { color:var(--green); }
    .neg { color:var(--red); }
    .muted { color:var(--muted); }
    .status { color:var(--muted); font-size:13px; }
    @media (max-width: 980px) { .toolbar { grid-template-columns: repeat(2, 1fr); } .grid { grid-template-columns: repeat(2, 1fr); } .split { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>BTCUSDT 模拟自动交易系统</h1>
    <div class="status" id="status">默认 EMA15 / MA40，周期 1w</div>
  </header>
  <main>
    <section class="toolbar">
      <label>交易对<input id="symbol" value="BTCUSDT"></label>
      <label>周期<input id="interval" value="1w"></label>
      <label>开始日期<input id="start" value="2019-09-02"></label>
      <label>结束日期<input id="end" value="2026-06-29"></label>
      <label>EMA<input id="ema" type="number" value="15"></label>
      <label>MA<input id="ma" type="number" value="40"></label>
      <label>ADX 最小<input id="adx" type="number" value="0"></label>
      <button class="primary" onclick="syncData()">同步 Binance 数据</button>
      <button onclick="runBacktest()">运行回测</button>
      <button onclick="runOptimize()">参数优化</button>
      <button onclick="runWalkForward()">样本外验证</button>
    </section>
    <section class="grid">
      <div class="metric"><span>最终资金</span><strong id="finalEquity">-</strong></div>
      <div class="metric"><span>总收益率</span><strong id="returnPct">-</strong></div>
      <div class="metric"><span>最大回撤</span><strong id="drawdown">-</strong></div>
      <div class="metric"><span>胜率</span><strong id="winRate">-</strong></div>
      <div class="metric"><span>交易次数</span><strong id="tradeCount">-</strong></div>
      <div class="metric"><span>收益回撤比</span><strong id="rdd">-</strong></div>
    </section>
    <section class="panel chart-wrap"><canvas id="chart"></canvas></section>
    <section class="split">
      <div class="panel">
        <h2>逐笔交易</h2>
        <table><thead><tr><th>方向</th><th>入场</th><th>出场</th><th>入场价</th><th>出场价</th><th>收益</th><th>原因</th></tr></thead><tbody id="trades"></tbody></table>
      </div>
      <div class="panel">
        <h2>参数优化结果</h2>
        <table><thead><tr><th>排名</th><th>收益率</th><th>回撤</th><th>胜率</th><th>交易</th><th>参数</th></tr></thead><tbody id="optimizations"></tbody></table>
      </div>
    </section>
    <section class="panel">
      <h2>Walk-forward 样本外验证</h2>
      <div class="status" id="walkForwardRange">训练段选参，测试段只验证，不参与参数搜索</div>
      <table><thead><tr><th>排名</th><th>训练收益</th><th>测试收益</th><th>测试回撤</th><th>测试胜率</th><th>测试交易</th><th>参数</th></tr></thead><tbody id="walkForward"></tbody></table>
    </section>
  </main>
<script>
let candles = [];
let lastResult = null;

function payload() {
  return {
    symbol: document.getElementById('symbol').value,
    interval: document.getElementById('interval').value,
    start_date: document.getElementById('start').value,
    end_date: document.getElementById('end').value,
    params: {
      ema_period: Number(document.getElementById('ema').value),
      ma_period: Number(document.getElementById('ma').value),
      adx_min: Number(document.getElementById('adx').value)
    }
  };
}

async function syncData() {
  const p = payload();
  setStatus('正在从 Binance 同步 K 线...');
  const url = `/api/sync?symbol=${p.symbol}&interval=${p.interval}&start_date=${p.start_date}&end_date=${p.end_date}`;
  const res = await fetch(url, {method:'POST'});
  const data = await res.json();
  if (!res.ok) throwError(data);
  setStatus(`已同步 ${data.stored} 根 K 线`);
  await loadCandles();
}

async function loadCandles() {
  const p = payload();
  const url = `/api/candles?symbol=${p.symbol}&interval=${p.interval}&start_date=${p.start_date}&end_date=${p.end_date}`;
  const res = await fetch(url);
  const data = await res.json();
  candles = data.items || [];
  drawChart(candles, []);
}

async function runBacktest() {
  setStatus('正在运行回测...');
  const res = await fetch('/api/backtest', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload())});
  const data = await res.json();
  if (!res.ok) throwError(data);
  lastResult = data;
  candles = data.candles || candles;
  fillMetrics(data.metrics);
  fillTrades(data.trades);
  drawChart(candles, data.trades);
  setStatus(`回测完成，run_id=${data.run_id}`);
}

async function runOptimize() {
  setStatus('正在搜索参数组合...');
  const res = await fetch('/api/optimize?max_results=20', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload())});
  const data = await res.json();
  if (!res.ok) throwError(data);
  fillOptimizations(data.items || []);
  setStatus(`优化完成，返回 ${data.count} 组结果`);
}

async function runWalkForward() {
  setStatus('正在执行 walk-forward 样本外验证...');
  const res = await fetch('/api/walk-forward?max_results=10&train_ratio=0.7', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload())});
  const data = await res.json();
  if (!res.ok) throwError(data);
  fillWalkForward(data);
  setStatus(`样本外验证完成：训练 ${data.train_count} 根，测试 ${data.test_count} 根`);
}

function fillMetrics(m) {
  document.getElementById('finalEquity').textContent = Number(m.final_equity).toFixed(2);
  document.getElementById('returnPct').textContent = `${Number(m.total_return_pct).toFixed(2)}%`;
  document.getElementById('returnPct').className = m.total_return_pct >= 0 ? 'pos' : 'neg';
  document.getElementById('drawdown').textContent = `${Number(m.max_drawdown_pct).toFixed(2)}%`;
  document.getElementById('winRate').textContent = `${Number(m.win_rate_pct).toFixed(2)}%`;
  document.getElementById('tradeCount').textContent = m.trade_count;
  document.getElementById('rdd').textContent = Number(m.return_drawdown_ratio).toFixed(2);
}

function fillTrades(items) {
  document.getElementById('trades').innerHTML = items.map(t => `
    <tr>
      <td class="${t.side === 'LONG' ? 'pos' : 'neg'}">${t.side}</td>
      <td>${t.entry_date}</td><td>${t.exit_date}</td>
      <td>${Number(t.entry_price).toFixed(2)}</td><td>${Number(t.exit_price).toFixed(2)}</td>
      <td class="${t.pnl >= 0 ? 'pos' : 'neg'}">${Number(t.pnl).toFixed(2)}</td>
      <td>${t.exit_reason}</td>
    </tr>`).join('');
}

function fillOptimizations(items) {
  document.getElementById('optimizations').innerHTML = items.map((r, i) => `
    <tr>
      <td>${i + 1}</td>
      <td class="${r.metrics.total_return_pct >= 0 ? 'pos' : 'neg'}">${Number(r.metrics.total_return_pct).toFixed(2)}%</td>
      <td>${Number(r.metrics.max_drawdown_pct).toFixed(2)}%</td>
      <td>${Number(r.metrics.win_rate_pct).toFixed(1)}%</td>
      <td>${r.metrics.trade_count}</td>
      <td class="muted">EMA${r.params.ema_period}/MA${r.params.ma_period}, ADX${r.params.adx_min}, SL${r.params.stop_atr}, TP${r.params.take_atr}</td>
    </tr>`).join('');
}

function fillWalkForward(data) {
  document.getElementById('walkForwardRange').textContent = `训练段 ${data.train_start} 至 ${data.train_end}；测试段 ${data.test_start} 至 ${data.test_end}`;
  document.getElementById('walkForward').innerHTML = (data.items || []).map((r, i) => `
    <tr>
      <td>${i + 1}</td>
      <td class="${r.train_metrics.total_return_pct >= 0 ? 'pos' : 'neg'}">${Number(r.train_metrics.total_return_pct).toFixed(2)}%</td>
      <td class="${r.test_metrics.total_return_pct >= 0 ? 'pos' : 'neg'}">${Number(r.test_metrics.total_return_pct).toFixed(2)}%</td>
      <td>${Number(r.test_metrics.max_drawdown_pct).toFixed(2)}%</td>
      <td>${Number(r.test_metrics.win_rate_pct).toFixed(1)}%</td>
      <td>${r.test_metrics.trade_count}</td>
      <td class="muted">EMA${r.params.ema_period}/MA${r.params.ma_period}, ADX${r.params.adx_min}, SL${r.params.stop_atr}, TP${r.params.take_atr}</td>
    </tr>`).join('');
}

function drawChart(items, trades) {
  const canvas = document.getElementById('chart');
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.floor(rect.width * devicePixelRatio);
  canvas.height = Math.floor(rect.height * devicePixelRatio);
  const ctx = canvas.getContext('2d');
  ctx.scale(devicePixelRatio, devicePixelRatio);
  ctx.clearRect(0, 0, rect.width, rect.height);
  if (!items.length) {
    ctx.fillStyle = '#8d97a8';
    ctx.fillText('暂无 K 线，请先同步 Binance 数据', 20, 30);
    return;
  }
  const pad = {l:54, r:20, t:20, b:34};
  const plotW = rect.width - pad.l - pad.r;
  const plotH = rect.height - pad.t - pad.b;
  const highs = items.map(x => x.high), lows = items.map(x => x.low);
  const max = Math.max(...highs), min = Math.min(...lows);
  const x = i => pad.l + (i + 0.5) * plotW / items.length;
  const y = v => pad.t + (max - v) * plotH / (max - min || 1);
  ctx.strokeStyle = '#242b35';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i++) {
    const yy = pad.t + i * plotH / 5;
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(rect.width - pad.r, yy); ctx.stroke();
  }
  const candleW = Math.max(3, plotW / items.length * 0.52);
  items.forEach((c, i) => {
    const up = c.close >= c.open;
    ctx.strokeStyle = ctx.fillStyle = up ? '#25c486' : '#ff5266';
    ctx.beginPath(); ctx.moveTo(x(i), y(c.high)); ctx.lineTo(x(i), y(c.low)); ctx.stroke();
    const top = y(Math.max(c.open, c.close)), bottom = y(Math.min(c.open, c.close));
    ctx.fillRect(x(i) - candleW / 2, top, candleW, Math.max(1, bottom - top));
  });
  drawLine(ctx, items, 'ema', x, y, '#f5c542');
  drawLine(ctx, items, 'ma', x, y, '#eb4fb7');
  trades.forEach(t => {
    const idx = items.findIndex(c => c.open_time === t.entry_time);
    if (idx >= 0) {
      ctx.fillStyle = t.side === 'LONG' ? '#25c486' : '#ff5266';
      ctx.beginPath(); ctx.arc(x(idx), y(t.entry_price), 4, 0, Math.PI * 2); ctx.fill();
    }
  });
  ctx.fillStyle = '#8d97a8';
  ctx.fillText('K线 + EMA + MA + 入场点', pad.l, rect.height - 12);
}

function drawLine(ctx, items, key, x, y, color) {
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
  let started = false;
  items.forEach((c, i) => {
    if (c[key] == null) return;
    if (!started) { ctx.moveTo(x(i), y(c[key])); started = true; }
    else ctx.lineTo(x(i), y(c[key]));
  });
  ctx.stroke();
}

function setStatus(text) { document.getElementById('status').textContent = text; }
function throwError(data) { throw new Error(data.detail || JSON.stringify(data)); }
window.addEventListener('resize', () => drawChart(candles, lastResult ? lastResult.trades : []));
loadCandles().catch(() => {});
</script>
</body>
</html>
"""
