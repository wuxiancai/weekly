from __future__ import annotations

import os
import subprocess
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .backtest import run_backtest
from .binance import BinanceClient
from .config import DEFAULTS
from .db import (
    connect,
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
from .paper import PaperEngine, init_paper_schema
from .strategy import StrategyParams, enrich_candles, params_from_dict
from .timeutils import ms_to_date, parse_date_ms


app = FastAPI(title="BTCUSDT 模拟自动交易系统")


class BacktestRequest(BaseModel):
    symbol: str = DEFAULTS.symbol
    interval: str = DEFAULTS.interval
    start_date: str = DEFAULTS.start_date
    end_date: str = DEFAULTS.end_date
    initial_equity: float = DEFAULTS.initial_equity
    leverage: float = DEFAULTS.leverage
    compound: bool = DEFAULTS.compound
    fee_rate: float = DEFAULTS.fee_rate
    slippage_rate: float = DEFAULTS.slippage_rate
    params: dict[str, Any] = {}


@app.on_event("startup")
def startup() -> None:
    init_db()
    with connect() as conn:
        init_paper_schema(conn)
        PaperEngine(conn).initialize()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.get("/eth", response_class=HTMLResponse)
def eth_index() -> str:
    return ETH_HTML


@app.get("/paper", response_class=HTMLResponse)
def paper_index() -> str:
    return PAPER_HTML


@app.get("/api/paper/status")
def paper_status() -> dict[str, Any]:
    with connect() as conn:
        init_paper_schema(conn)
        engine = PaperEngine(conn)
        return engine.status()


@app.get("/api/market/tickers")
def market_tickers() -> dict[str, Any]:
    symbols = ["BTCUSDT", "ETHUSDT"]
    try:
        rows = BinanceClient().fetch_utc_day_tickers(symbols)
    except Exception as exc:
        raise HTTPException(502, f"Binance 行情连接失败：{exc}") from exc
    by_symbol = {str(row.get("symbol", "")).upper(): row for row in rows}
    items = []
    for symbol in symbols:
        row = by_symbol.get(symbol)
        if row is None:
            continue
        price = float(row["lastPrice"])
        utc_open_price = float(row["utcOpenPrice"])
        change = price - utc_open_price
        items.append(
            {
                "symbol": symbol,
                "price": round(price, 4),
                "utc_open_price": round(utc_open_price, 4),
                "change": round(change, 4),
                "change_pct": round(change / utc_open_price * 100, 4) if utc_open_price else 0.0,
                "event_time": int(row.get("eventTime") or 0),
            }
        )
    return {"timezone": "UTC+0", "items": items}


@app.get("/api/system/runtime")
def system_runtime() -> dict[str, Any]:
    git_commit = os.getenv("APP_VERSION") or _git_commit()
    return {
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "app_version": git_commit,
        "git_commit": git_commit,
        "start_mode": os.getenv("START_MODE", ""),
        "paper_html_markers": {
            "dynamic_strategy_intervals": 'id="strategyIntervals"' in PAPER_HTML,
            "new_title": "<h1>币安合约交易系统</h1>" in PAPER_HTML,
            "hardcoded_old_intervals": "<strong>1d / 4h</strong>" in PAPER_HTML
            or "<strong>1d / 4h / 1h</strong>" in PAPER_HTML,
        },
    }


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.getcwd(),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


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
    result = run_backtest(
        data,
        params,
        initial_equity=request.initial_equity,
        leverage=request.leverage,
        compound=request.compound,
        fee_rate=request.fee_rate,
        slippage_rate=request.slippage_rate,
        start_trading_ms=start_ms,
    )
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
    results = optimize(
        data,
        max_results=max_results,
        start_trading_ms=start_ms,
        initial_equity=request.initial_equity,
        leverage=request.leverage,
        compound=request.compound,
        fee_rate=request.fee_rate,
        slippage_rate=request.slippage_rate,
    )
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
    .header-actions { display:flex; align-items:center; gap:12px; }
    .nav-button { display:inline-flex; align-items:center; justify-content:center; min-height:34px; padding:0 12px; border:1px solid #3b4654; border-radius:6px; color:var(--text); background:#202733; text-decoration:none; font-size:13px; font-weight:650; white-space:nowrap; }
    .nav-button:hover { filter:brightness(1.12); }
    main { padding:18px; display:grid; gap:14px; }
    .toolbar, .grid, .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; }
    .toolbar { display:grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); gap:10px; padding:12px; align-items:end; }
    label { display:grid; gap:5px; color:var(--muted); font-size:12px; }
    input { width:100%; border:1px solid var(--line); background:#0d1015; color:var(--text); border-radius:6px; padding:9px; font-size:13px; }
    select { width:100%; border:1px solid var(--line); background:#0d1015; color:var(--text); border-radius:6px; padding:9px; font-size:13px; }
    button { border:1px solid #3b4654; background:#202733; color:var(--text); border-radius:6px; padding:10px 12px; cursor:pointer; font-weight:650; min-height:38px; width:100%; }
    button.primary { background:#1b6b50; border-color:#27936f; }
    button:hover { filter:brightness(1.12); }
    .grid { display:grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap:0; overflow:hidden; }
    .metric { padding:13px; border-right:1px solid var(--line); }
    .metric:last-child { border-right:0; }
    .metric span { display:block; color:var(--muted); font-size:12px; margin-bottom:6px; }
    .metric strong { font-size:20px; }
    .panel { padding:12px; }
    .chart-wrap { height:520px; }
    canvas { width:100%; height:100%; display:block; background:#11151b; border-radius:6px; }
    table { width:100%; border-collapse:collapse; font-size:12px; }
    th, td { border-bottom:1px solid var(--line); padding:8px; text-align:right; white-space:nowrap; }
    th:first-child, td:first-child { text-align:left; }
    th { color:var(--muted); font-weight:600; }
    .pos { color:var(--green); }
    .neg { color:var(--red); }
    .muted { color:var(--muted); }
    .status { color:var(--muted); font-size:13px; }
    .formula { color:var(--muted); font-size:12px; line-height:1.6; margin:4px 0 12px; }
    .formula a { color:var(--blue); text-decoration:none; }
    @media (max-width: 980px) { .toolbar { grid-template-columns: repeat(2, 1fr); } .grid { grid-template-columns: repeat(2, 1fr); } }
  </style>
</head>
<body>
  <header>
    <h1>BTCUSDT U本位永续合约模拟交易系统</h1>
    <div class="header-actions">
      <a class="nav-button" href="/paper">模拟交易</a>
      <a class="nav-button" href="/eth">ETH 回测</a>
      <div class="status" id="status">USDT 保证金 / USDT 结算，默认本金 10000，默认复利，2倍杠杆，EMA15 / MA40，周期 1w</div>
    </div>
  </header>
  <main>
    <section class="toolbar">
      <label title="交易标的。推荐：BTCUSDT。此处固定按 Binance USDⓈ-M / U本位永续合约理解，不是币本位合约。">交易对<input id="symbol" value="BTCUSDT"></label>
      <label title="K 线周期。推荐：周线 1w；切换到 1d/4h/1h 时会自动套用当前交易对的独立周期默认参数。">周期<select id="interval" onchange="applyIntervalDefaults()"><option value="1w" selected>1w</option><option value="1d">1d</option><option value="4h">4h</option><option value="1h">1h</option></select></label>
      <label title="回测开始日期。推荐：2019-09-02；交易只从该日期后开始，指标可用之前历史预热。">开始日期<input id="start" value="2019-09-02"></label>
      <label title="回测结束日期。推荐：2026-06-29。">结束日期<input id="end" value="2026-06-29"></label>
      <label title="初始本金。复利=NO 时每笔按该固定本金开仓；复利=YES 时第一笔用该本金，之后按当前权益开仓。推荐：10000。">本金<input id="initialEquity" type="number" step="100" value="10000"></label>
      <label title="是否复利。NO：每笔按固定本金开仓；YES：每笔按当前权益开仓。推荐：YES。">复利<select id="compound"><option value="false">NO</option><option value="true" selected>YES</option></select></label>
      <label title="杠杆倍率。0 表示不使用杠杆；2 表示按 2 倍名义仓位计算盈亏和手续费。推荐：2。">杠杆<input id="leverage" type="number" step="0.1" value="2"></label>
      <label title="单边手续费率。推荐：0.0005。">手续费<input id="feeRate" type="number" step="0.0001" value="0.0005"></label>
      <label title="滑点率。推荐：0.0005，用于模拟成交价偏移。">滑点<input id="slippageRate" type="number" step="0.0001" value="0.0005"></label>
      <label title="快速趋势均线 EMA 周期。推荐：15。">EMA<input id="ema" type="number" value="15"></label>
      <label title="慢速趋势均线 MA 周期。推荐：40；不足 40 根周 K 不会出信号。">MA<input id="ma" type="number" value="40"></label>
      <label title="RSI 周期。推荐：14。">RSI周期<input id="rsiPeriod" type="number" value="14"></label>
      <label title="ATR 周期，用于止损止盈距离。推荐：14。">ATR周期<input id="atrPeriod" type="number" value="14"></label>
      <label title="ADX 周期。推荐：14。">ADX周期<input id="adxPeriod" type="number" value="14"></label>
      <label title="ADX 最小值，过滤弱趋势。推荐：0 表示不过滤。">ADX 最小<input id="adx" type="number" value="0"></label>
      <label title="做多 RSI 下限。推荐：35。">多RSI低<input id="longRsiMin" type="number" value="35"></label>
      <label title="做多 RSI 上限。推荐：85。">多RSI高<input id="longRsiMax" type="number" value="85"></label>
      <label title="做空 RSI 下限。推荐：0。">空RSI低<input id="shortRsiMin" type="number" value="0"></label>
      <label title="做空 RSI 上限。推荐：100。">空RSI高<input id="shortRsiMax" type="number" value="100"></label>
      <label title="ATR 止损倍数。推荐：1.8。">止损ATR<input id="stopAtr" type="number" step="0.1" value="1.8"></label>
      <label title="动态止盈启动 ATR 倍数。推荐：7.5。">止盈ATR<input id="takeAtr" type="number" step="0.1" value="7.5"></label>
      <label title="动态止盈保护位每次上移的 ATR 阶梯。推荐：1.25。">止盈阶梯<input id="takeAtrStep" type="number" step="0.05" value="1.25"></label>
      <label title="动态止盈最高 ATR 倍数上限。推荐：32。">止盈上限<input id="takeAtrMax" type="number" step="0.5" value="32"></label>
      <label title="动态止盈保护位缓冲比例。推荐：0。">止盈缓冲<input id="takeAtrBuffer" type="number" step="0.01" value="0"></label>
      <label title="成交量过滤倍数，当前量需大于成交量均线乘以该值。推荐：1。">量能倍数<input id="volumeMult" type="number" step="0.05" value="1"></label>
      <label title="盘中状态切换策略。YES：先识别 TREND/RANGE/NEUTRAL，趋势市顺势，震荡市均值回归，过渡市少交易。推荐：1h/4h YES，周线/日线 NO。">状态策略<select id="regimeSwitch"><option value="false" selected>NO</option><option value="true">YES</option></select></label>
      <label title="趋势状态要求 EMA 与 MA 至少分离的比例。推荐：1h/4h 0。">趋势间距<input id="trendMaGapMin" type="number" step="0.001" value="0.006"></label>
      <label title="震荡状态 ADX 上限。低于该值且布林带收窄时按震荡处理。推荐：18。">震荡ADX<input id="rangeAdxMax" type="number" step="1" value="18"></label>
      <label title="震荡状态布林带宽上限，(上轨-下轨)/中轨。推荐：0.08。">震荡带宽<input id="rangeBbWidthMax" type="number" step="0.005" value="0.08"></label>
      <label title="震荡策略做多 RSI 阈值。低于该值且接近布林下轨时做多。推荐：35。">震荡多RSI<input id="rangeRsiLow" type="number" value="35"></label>
      <label title="震荡策略做空 RSI 阈值。高于该值且接近布林上轨时做空。推荐：65。">震荡空RSI<input id="rangeRsiHigh" type="number" value="65"></label>
      <button class="primary" onclick="syncData()">同步 Binance 数据</button>
      <button onclick="runBacktest()">运行回测</button>
      <button onclick="runOptimize()">参数优化</button>
      <button onclick="runWalkForward()">样本外验证</button>
    </section>
    <section class="grid">
      <div class="metric"><span>最终资金(USDT)</span><strong id="finalEquity">-</strong></div>
      <div class="metric"><span>总收益率</span><strong id="returnPct">-</strong></div>
      <div class="metric"><span>最大单笔回撤</span><strong id="drawdown">-</strong></div>
      <div class="metric"><span>单笔最大亏损率</span><strong id="maxSingleLoss">-</strong></div>
      <div class="metric"><span>胜率</span><strong id="winRate">-</strong></div>
      <div class="metric"><span>交易次数</span><strong id="tradeCount">-</strong></div>
      <div class="metric"><span>收益回撤比</span><strong id="rdd">-</strong></div>
    </section>
    <section class="panel chart-wrap"><canvas id="chart"></canvas></section>
    <section class="panel">
      <h2>逐笔交易</h2>
      <p class="formula">
        BTCUSDT U本位永续合约按 USDT 保证金 / USDT 结算；合约数量单位是 BTC，盈亏单位是 USDT。
        多单收益 = (出场价 - 入场价) * 合约数量；空单收益 = (入场价 - 出场价) * 合约数量，手续费另扣。
        <a href="https://www.binance.com/en/support/faq/detail/3a55a23768cb416fb404f06ffedde4b2" target="_blank" rel="noreferrer">Binance PnL 说明</a>
      </p>
      <table><thead><tr><th>方向</th><th>入场</th><th>出场</th><th>入场价(USDT)</th><th>出场价(USDT)</th><th>合约数量(BTC)</th><th>收益(USDT)</th><th>收益率</th><th>盈亏比</th><th>最大回撤</th><th>收益回撤比</th><th>原因</th></tr></thead><tbody id="trades"></tbody></table>
    </section>
    <section class="panel">
      <h2>参数优化结果</h2>
      <table><thead><tr><th>排名</th><th>收益率</th><th>最大单笔回撤</th><th>胜率</th><th>交易</th><th>参数</th></tr></thead><tbody id="optimizations"></tbody></table>
    </section>
    <section class="panel">
      <h2>Walk-forward 样本外验证</h2>
      <div class="status" id="walkForwardRange">训练段选参，测试段只验证，不参与参数搜索</div>
      <table><thead><tr><th>排名</th><th>训练收益</th><th>测试收益</th><th>测试最大单笔回撤</th><th>测试胜率</th><th>测试交易</th><th>参数</th></tr></thead><tbody id="walkForward"></tbody></table>
    </section>
  </main>
<script>
let candles = [];
let lastResult = null;
const PAGE_SYMBOL = 'BTCUSDT';
const PAGE_INTERVAL = '1w';
const STRATEGY_DEFAULTS = {
  BTCUSDT: {
    '1w': {
      start: '2019-09-02', end: '2026-06-29', initialEquity: 10000, compound: true, leverage: 2,
      feeRate: 0.0005, slippageRate: 0.0005, ema: 15, ma: 40, rsiPeriod: 14, atrPeriod: 14,
      adxPeriod: 14, adx: 0, longRsiMin: 35, longRsiMax: 85, shortRsiMin: 0, shortRsiMax: 100,
      stopAtr: 1.8, takeAtr: 7.5, takeAtrStep: 1.25, takeAtrMax: 32, takeAtrBuffer: 0, volumeMult: 1,
      regimeSwitch: false, trendMaGapMin: 0.006, rangeAdxMax: 18, rangeBbWidthMax: 0.08, rangeRsiLow: 35, rangeRsiHigh: 65
    },
    '1d': {
      start: '2019-09-02', end: '2026-06-29', initialEquity: 10000, compound: true, leverage: 0,
      feeRate: 0.0005, slippageRate: 0.0005, ema: 8, ma: 40, rsiPeriod: 14, atrPeriod: 14,
      adxPeriod: 14, adx: 0, longRsiMin: 50, longRsiMax: 80, shortRsiMin: 0, shortRsiMax: 100,
      stopAtr: 1.6, takeAtr: 13.0, takeAtrStep: 0.75, takeAtrMax: 18.0, takeAtrBuffer: 0, volumeMult: 0.75,
      regimeSwitch: false, trendMaGapMin: 0.006, rangeAdxMax: 18, rangeBbWidthMax: 0.08, rangeRsiLow: 35, rangeRsiHigh: 65
    },
    '4h': {
      start: '2019-09-02', end: '2026-06-29', initialEquity: 10000, compound: true, leverage: 0,
      feeRate: 0.0005, slippageRate: 0.0005, ema: 8, ma: 35, rsiPeriod: 14, atrPeriod: 14,
      adxPeriod: 14, adx: 25, longRsiMin: 50, longRsiMax: 80, shortRsiMin: 0, shortRsiMax: 100,
      stopAtr: 0.8, takeAtr: 3.5, takeAtrStep: 0.5, takeAtrMax: 8.0, takeAtrBuffer: 0, volumeMult: 1.0,
      regimeSwitch: true, trendMaGapMin: 0.0, rangeAdxMax: 18, rangeBbWidthMax: 0.08, rangeRsiLow: 30, rangeRsiHigh: 65
    },
    '1h': {
      start: '2019-09-02', end: '2026-06-29', initialEquity: 10000, compound: true, leverage: 0,
      feeRate: 0.0005, slippageRate: 0.0005, ema: 12, ma: 35, rsiPeriod: 14, atrPeriod: 14,
      adxPeriod: 14, adx: 18, longRsiMin: 55, longRsiMax: 85, shortRsiMin: 0, shortRsiMax: 100,
      stopAtr: 0.45, takeAtr: 4.0, takeAtrStep: 1.0, takeAtrMax: 12.0, takeAtrBuffer: 0, volumeMult: 1.25,
      regimeSwitch: true, trendMaGapMin: 0.0, rangeAdxMax: 22, rangeBbWidthMax: 0.05, rangeRsiLow: 35, rangeRsiHigh: 65
    }
  },
  ETHUSDT: {
    '1w': {
      start: '2019-09-02', end: '2026-06-29', initialEquity: 10000, compound: true, leverage: 2,
      feeRate: 0.0005, slippageRate: 0.0005, ema: 15, ma: 40, rsiPeriod: 14, atrPeriod: 14,
      adxPeriod: 14, adx: 0, longRsiMin: 35, longRsiMax: 85, shortRsiMin: 0, shortRsiMax: 100,
      stopAtr: 1.8, takeAtr: 7.5, takeAtrStep: 1.25, takeAtrMax: 32, takeAtrBuffer: 0, volumeMult: 1,
      regimeSwitch: false, trendMaGapMin: 0.006, rangeAdxMax: 18, rangeBbWidthMax: 0.08, rangeRsiLow: 35, rangeRsiHigh: 65
    },
    '1d': {
      start: '2019-09-02', end: '2026-06-29', initialEquity: 10000, compound: true, leverage: 2,
      feeRate: 0.0005, slippageRate: 0.0005, ema: 15, ma: 40, rsiPeriod: 14, atrPeriod: 14,
      adxPeriod: 14, adx: 0, longRsiMin: 35, longRsiMax: 85, shortRsiMin: 0, shortRsiMax: 100,
      stopAtr: 1.8, takeAtr: 6.5, takeAtrStep: 1.25, takeAtrMax: 24, takeAtrBuffer: 0, volumeMult: 1,
      regimeSwitch: false, trendMaGapMin: 0.006, rangeAdxMax: 18, rangeBbWidthMax: 0.08, rangeRsiLow: 35, rangeRsiHigh: 65
    },
    '4h': {
      start: '2019-09-02', end: '2026-06-29', initialEquity: 10000, compound: true, leverage: 0,
      feeRate: 0.0005, slippageRate: 0.0005, ema: 8, ma: 35, rsiPeriod: 14, atrPeriod: 14,
      adxPeriod: 14, adx: 25, longRsiMin: 50, longRsiMax: 80, shortRsiMin: 0, shortRsiMax: 100,
      stopAtr: 0.8, takeAtr: 3.5, takeAtrStep: 0.5, takeAtrMax: 8, takeAtrBuffer: 0, volumeMult: 1,
      regimeSwitch: true, trendMaGapMin: 0.0, rangeAdxMax: 18, rangeBbWidthMax: 0.08, rangeRsiLow: 30, rangeRsiHigh: 65
    },
    '1h': {
      start: '2019-09-02', end: '2026-06-29', initialEquity: 10000, compound: true, leverage: 0,
      feeRate: 0.0005, slippageRate: 0.0005, ema: 15, ma: 50, rsiPeriod: 14, atrPeriod: 14,
      adxPeriod: 14, adx: 25, longRsiMin: 50, longRsiMax: 80, shortRsiMin: 0, shortRsiMax: 100,
      stopAtr: 0.45, takeAtr: 1.8, takeAtrStep: 0.5, takeAtrMax: 4, takeAtrBuffer: 0, volumeMult: 1,
      regimeSwitch: true, trendMaGapMin: 0.0, rangeAdxMax: 22, rangeBbWidthMax: 0.12, rangeRsiLow: 30, rangeRsiHigh: 65
    }
  }
};

function applyIntervalDefaults() {
  const symbol = document.getElementById('symbol').value.toUpperCase();
  const interval = document.getElementById('interval').value;
  const defaults = (STRATEGY_DEFAULTS[symbol] || STRATEGY_DEFAULTS[PAGE_SYMBOL] || {})[interval];
  if (!defaults) return;
  setValue('symbol', symbol);
  setValue('start', defaults.start);
  setValue('end', defaults.end);
  setValue('initialEquity', defaults.initialEquity);
  document.getElementById('compound').value = String(defaults.compound);
  setValue('leverage', defaults.leverage);
  setValue('feeRate', defaults.feeRate);
  setValue('slippageRate', defaults.slippageRate);
  setValue('ema', defaults.ema);
  setValue('ma', defaults.ma);
  setValue('rsiPeriod', defaults.rsiPeriod);
  setValue('atrPeriod', defaults.atrPeriod);
  setValue('adxPeriod', defaults.adxPeriod);
  setValue('adx', defaults.adx);
  setValue('longRsiMin', defaults.longRsiMin);
  setValue('longRsiMax', defaults.longRsiMax);
  setValue('shortRsiMin', defaults.shortRsiMin);
  setValue('shortRsiMax', defaults.shortRsiMax);
  setValue('stopAtr', defaults.stopAtr);
  setValue('takeAtr', defaults.takeAtr);
  setValue('takeAtrStep', defaults.takeAtrStep);
  setValue('takeAtrMax', defaults.takeAtrMax);
  setValue('takeAtrBuffer', defaults.takeAtrBuffer);
  setValue('volumeMult', defaults.volumeMult);
  document.getElementById('regimeSwitch').value = String(defaults.regimeSwitch);
  setValue('trendMaGapMin', defaults.trendMaGapMin);
  setValue('rangeAdxMax', defaults.rangeAdxMax);
  setValue('rangeBbWidthMax', defaults.rangeBbWidthMax);
  setValue('rangeRsiLow', defaults.rangeRsiLow);
  setValue('rangeRsiHigh', defaults.rangeRsiHigh);
  setStatus(`${symbol} ${interval} 默认参数已应用`);
  loadCandles().catch(() => {});
}

function setValue(id, value) {
  document.getElementById(id).value = value;
}

function payload() {
  return {
    symbol: document.getElementById('symbol').value,
    interval: document.getElementById('interval').value,
    start_date: document.getElementById('start').value,
    end_date: document.getElementById('end').value,
    initial_equity: num('initialEquity'),
    compound: document.getElementById('compound').value === 'true',
    leverage: num('leverage'),
    fee_rate: num('feeRate'),
    slippage_rate: num('slippageRate'),
    params: {
      ema_period: num('ema'),
      ma_period: num('ma'),
      rsi_period: num('rsiPeriod'),
      atr_period: num('atrPeriod'),
      adx_period: num('adxPeriod'),
      adx_min: num('adx'),
      long_rsi_min: num('longRsiMin'),
      long_rsi_max: num('longRsiMax'),
      short_rsi_min: num('shortRsiMin'),
      short_rsi_max: num('shortRsiMax'),
      stop_atr: num('stopAtr'),
      take_atr: num('takeAtr'),
      take_atr_step: num('takeAtrStep'),
      take_atr_max: num('takeAtrMax'),
      take_atr_buffer_pct: num('takeAtrBuffer'),
      volume_mult: num('volumeMult'),
      regime_switch: document.getElementById('regimeSwitch').value === 'true',
      trend_ma_gap_min: num('trendMaGapMin'),
      range_adx_max: num('rangeAdxMax'),
      range_bb_width_max: num('rangeBbWidthMax'),
      range_rsi_low: num('rangeRsiLow'),
      range_rsi_high: num('rangeRsiHigh')
    }
  };
}

function num(id) {
  return Number(document.getElementById(id).value);
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
  document.getElementById('maxSingleLoss').textContent = `${Number(m.max_single_loss_pct || 0).toFixed(2)}%`;
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
      <td>${Number(t.quantity).toFixed(6)}</td>
      <td class="${t.pnl >= 0 ? 'pos' : 'neg'}">${Number(t.pnl).toFixed(2)}</td>
      <td class="${t.pnl_pct >= 0 ? 'pos' : 'neg'}">${Number(t.pnl_pct).toFixed(2)}%</td>
      <td>${Number(t.reward_risk_ratio).toFixed(2)}</td>
      <td>${Number(t.max_drawdown_pct).toFixed(2)}%</td>
      <td>${Number(t.return_drawdown_ratio).toFixed(2)}</td>
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
      <td class="muted">${paramSummary(r.params)}</td>
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
      <td class="muted">${paramSummary(r.params)}</td>
    </tr>`).join('');
}

function paramSummary(p) {
  return `EMA${p.ema_period}/MA${p.ma_period}, RSI${p.rsi_period} L${p.long_rsi_min}-${p.long_rsi_max} S${p.short_rsi_min}-${p.short_rsi_max}, ATR${p.atr_period}, ADX${p.adx_min}/${p.adx_period}, SL${p.stop_atr}, TP${p.take_atr}, Step${p.take_atr_step}, Max${p.take_atr_max}, Buf${p.take_atr_buffer_pct}, Vol${p.volume_mult}, Regime${p.regime_switch ? 'Y' : 'N'}`;
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
document.addEventListener('DOMContentLoaded', () => {
  setValue('symbol', PAGE_SYMBOL);
  document.getElementById('interval').value = PAGE_INTERVAL;
  applyIntervalDefaults();
});
</script>
</body>
</html>
"""


PAPER_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>模拟交易状态</title>
  <style>
    :root { color-scheme: dark; --bg:#101216; --panel:#171b22; --line:#2a303a; --text:#e8edf5; --muted:#8d97a8; --green:#25c486; --red:#ff5266; --blue:#66b7ff; --purple:#b58cff; --yellow:#ffd166; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); }
    header { display:flex; align-items:center; justify-content:space-between; padding:18px 22px; border-bottom:1px solid var(--line); background:#0c0e12; }
    h1 { margin:0; font-size:20px; }
    main { padding:18px; display:grid; gap:14px; }
    .market-ticker { min-width:420px; flex:1; max-width:760px; border:1px solid var(--line); border-radius:8px; padding:8px 12px; background:#11151b; }
    .ticker-row { display:flex; align-items:center; justify-content:center; gap:14px; min-height:22px; white-space:nowrap; font-weight:700; }
    .ticker-item { display:inline-flex; align-items:baseline; gap:7px; }
    .ticker-label, .clock-label { color:var(--muted); font-size:12px; }
    .ticker-price { font-size:16px; }
    .ticker-change, .clock-value { font-size:13px; }
    .nav { display:flex; gap:10px; align-items:center; }
    a, button { border:1px solid #3b4654; background:#202733; color:var(--text); border-radius:6px; padding:9px 12px; text-decoration:none; cursor:pointer; font-weight:650; }
    .grid { display:grid; grid-template-columns:repeat(4,1fr); border:1px solid var(--line); border-radius:8px; overflow:hidden; background:var(--panel); }
    .metric { padding:14px; border-right:1px solid var(--line); }
    .metric:last-child { border-right:0; }
    .metric span { display:block; color:var(--muted); font-size:12px; margin-bottom:7px; }
    .metric strong { font-size:22px; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; overflow:auto; }
    .trade-records-scroll { max-height:214px; overflow-y:auto; border-bottom:1px solid var(--line); }
    table { width:100%; border-collapse:collapse; font-size:12px; }
    th, td { border-bottom:1px solid var(--line); padding:8px; text-align:right; white-space:nowrap; }
    th:first-child, td:first-child { text-align:left; }
    th { color:var(--muted); }
    .muted { color:var(--muted); }
    .pos { color:var(--green); }
    .neg { color:var(--red); }
    .symbol-btc, .interval-1w { color:var(--blue); font-weight:700; }
    .interval-1d { color:var(--red); font-weight:700; }
    .interval-4h { color:var(--purple); font-weight:700; }
    .interval-1h { color:var(--yellow); font-weight:700; }
    @media (max-width: 900px) { .grid { grid-template-columns:repeat(2,1fr); } header { align-items:stretch; flex-direction:column; gap:12px; } .market-ticker { min-width:0; max-width:none; width:100%; padding:8px 10px; } .ticker-row { justify-content:flex-start; gap:9px; overflow:auto; } .ticker-item { gap:4px; } .ticker-label, .clock-label { font-size:11px; } .ticker-price { font-size:14px; } .ticker-change, .clock-value { font-size:12px; } }
  </style>
</head>
<body>
  <header>
    <h1>币安合约交易系统</h1>
    <div class="market-ticker" id="marketTicker">
      <div class="ticker-row">
        <span class="ticker-item" id="tickerBtc"><span class="ticker-label">BTC 永续</span><span class="ticker-price">-</span><span class="ticker-change">-</span></span>
        <span class="ticker-item" id="tickerEth"><span class="ticker-label">ETH 永续</span><span class="ticker-price">-</span><span class="ticker-change">-</span></span>
        <span class="ticker-item"><span class="clock-label">UTC+8</span><span class="clock-value" id="utc8Clock">-</span></span>
      </div>
    </div>
    <div class="nav">
      <a href="/">BTC 回测</a>
      <a href="/eth">ETH 回测</a>
      <button onclick="loadAll()">刷新</button>
    </div>
  </header>
  <main>
    <section class="grid">
      <div class="metric"><span>模拟账户资金(USDT)</span><strong id="equity">-</strong></div>
      <div class="metric"><span>初始资金(USDT)</span><strong id="initial">1000.00</strong></div>
      <div class="metric"><span>复利</span><strong id="compound">YES</strong></div>
      <div class="metric"><span>策略周期</span><strong id="strategyIntervals">-</strong></div>
    </section>
    <section class="panel">
      <h2>当前持仓</h2>
      <table><thead><tr><th>交易对</th><th>周期</th><th>方向</th><th>入场时间</th><th>入场价</th><th>强平价格</th><th>数量</th><th>保证金</th><th>止损</th><th>保护/止盈</th><th>最新止盈</th></tr></thead><tbody id="positions"></tbody></table>
    </section>
    <section class="panel">
      <h2>策略状态</h2>
      <table><thead><tr><th>交易对</th><th>周期</th><th>启用</th><th>最后处理 K 线</th><th>参数</th></tr></thead><tbody id="strategies"></tbody></table>
    </section>
    <section class="panel">
      <h2>交易记录</h2>
      <div class="trade-records-scroll">
        <table><thead><tr><th>交易对</th><th>周期</th><th>方向</th><th>入场</th><th>出场</th><th>入场价</th><th>出场价</th><th>收益(USDT)</th><th>收益率</th><th>原因</th></tr></thead><tbody id="tradeRecords"></tbody></table>
      </div>
    </section>
    <section class="panel">
      <h2>最近平仓</h2>
      <table><thead><tr><th>交易对</th><th>周期</th><th>方向</th><th>入场</th><th>出场</th><th>入场价</th><th>出场价</th><th>收益(USDT)</th><th>收益率</th><th>原因</th></tr></thead><tbody id="trades"></tbody></table>
    </section>
    <section class="panel">
      <h2>运行日志</h2>
      <table><thead><tr><th>时间</th><th>交易对</th><th>类型</th><th>内容</th></tr></thead><tbody id="events"></tbody></table>
    </section>
  </main>
<script>
let marketTickerSocket = null;
let marketTickerReconnectTimer = null;
const marketTickerState = {};

async function loadStatus() {
  const res = await fetch('/api/paper/status');
  const data = await res.json();
  const account = data.account || {};
  document.getElementById('equity').textContent = Number(account.equity || 0).toFixed(2);
  document.getElementById('initial').textContent = Number(account.initial_equity || 1000).toFixed(2);
  document.getElementById('compound').textContent = account.compound ? 'YES' : 'NO';
  updateStrategyIntervals(data.strategies || []);
  fillStrategies(data.strategies || []);
  fillPositions(data.positions || []);
  fillTradeRecords(data.trade_records || data.trades || []);
  fillTrades(data.trades || []);
  fillEvents(data.events || []);
}
function loadAll() {
  loadStatus();
  return loadMarketTicker();
}
async function loadMarketTicker() {
  try {
    const res = await fetch('/api/market/tickers');
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '行情连接失败');
    const bySymbol = Object.fromEntries((data.items || []).map(item => {
      marketTickerState[item.symbol] = item;
      return [item.symbol, item];
    }));
    fillTicker('tickerBtc', bySymbol.BTCUSDT);
    fillTicker('tickerEth', bySymbol.ETHUSDT);
  } catch (error) {
    document.getElementById('tickerBtc').innerHTML = '<span class="ticker-label">BTC 永续</span><span class="ticker-change neg">行情连接失败</span>';
    document.getElementById('tickerEth').innerHTML = '<span class="ticker-label">ETH 永续</span><span class="ticker-change neg">行情连接失败</span>';
  }
}
function openMarketTickerStream() {
  if (marketTickerSocket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(marketTickerSocket.readyState)) return;
  if (marketTickerReconnectTimer) {
    clearTimeout(marketTickerReconnectTimer);
    marketTickerReconnectTimer = null;
  }
  const tickerEl = document.getElementById('marketTicker');
  tickerEl.dataset.streamState = 'connecting';
  marketTickerSocket = new WebSocket('wss://fstream.binance.com/stream?streams=btcusdt@bookTicker/ethusdt@bookTicker');
  window.marketTickerSocket = marketTickerSocket;
  marketTickerSocket.onopen = () => {
    tickerEl.dataset.streamState = 'open';
  };
  marketTickerSocket.onmessage = event => {
    const payload = JSON.parse(event.data);
    const ticker = payload.data || payload;
    const symbol = ticker.s;
    if (!symbol) return;
    const bid = Number(ticker.b);
    const ask = Number(ticker.a);
    const price = Number.isFinite(bid) && Number.isFinite(ask) ? (bid + ask) / 2 : Number(ticker.p || ticker.c);
    if (!Number.isFinite(price)) return;
    const previous = marketTickerState[symbol] || { symbol };
    const utcOpen = Number(previous.utc_open_price || 0);
    const change = price - utcOpen;
    const item = {
      ...previous,
      symbol,
      price,
      change,
      change_pct: utcOpen ? change / utcOpen * 100 : 0,
      event_time: Number(ticker.E || Date.now()),
    };
    marketTickerState[symbol] = item;
    tickerEl.dataset.streamUpdates = String(Number(tickerEl.dataset.streamUpdates || 0) + 1);
    fillTicker(symbol === 'BTCUSDT' ? 'tickerBtc' : 'tickerEth', item);
  };
  marketTickerSocket.onclose = () => {
    tickerEl.dataset.streamState = 'closed';
    marketTickerReconnectTimer = setTimeout(openMarketTickerStream, 3000);
  };
  marketTickerSocket.onerror = () => {
    tickerEl.dataset.streamState = 'error';
    marketTickerSocket.close();
  };
}
function fillTicker(id, item) {
  const el = document.getElementById(id);
  if (!item) {
    el.innerHTML = '<span class="ticker-label">永续</span><span class="ticker-change neg">暂无行情</span>';
    return;
  }
  const label = item.symbol === 'BTCUSDT' ? 'BTC 永续' : 'ETH 永续';
  const change = Number(item.change_pct || 0);
  const changeAmount = Number(item.change || 0);
  const cls = change >= 0 ? 'pos' : 'neg';
  const sign = change >= 0 ? '+' : '';
  el.innerHTML = `<span class="ticker-label">${label}</span><span class="ticker-price ${cls}">${Number(item.price).toFixed(2)}</span><span class="ticker-change ${cls}">${sign}${changeAmount.toFixed(2)}</span><span class="ticker-change ${cls}">${sign}${change.toFixed(2)}%</span>`;
}
function updateUtc8Clock() {
  const now = new Date();
  const utc8 = new Date(now.getTime() + (now.getTimezoneOffset() + 480) * 60000);
  const pad = value => String(value).padStart(2, '0');
  const text = `${utc8.getFullYear()}-${pad(utc8.getMonth() + 1)}-${pad(utc8.getDate())} ${pad(utc8.getHours())}:${pad(utc8.getMinutes())}:${pad(utc8.getSeconds())}`;
  document.getElementById('utc8Clock').textContent = text;
}
function formatDateTime(ms) {
  const value = Number(ms);
  if (!Number.isFinite(value) || value <= 0) return '-';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '-';
  const pad = item => String(item).padStart(2, '0');
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}:${pad(dt.getSeconds())}`;
}
function date(ms) { return formatDateTime(ms); }
function symbolClass(value) { return String(value || '').toUpperCase() === 'BTCUSDT' ? 'symbol-btc' : ''; }
function intervalClass(value) {
  const normalized = String(value || '').toLowerCase();
  return ['1w', '1d', '4h', '1h'].includes(normalized) ? `interval-${normalized}` : '';
}
function symbolCell(value) { return `<span class="${symbolClass(value)}">${value || '-'}</span>`; }
function intervalCell(value) { return `<span class="${intervalClass(value)}">${value || '-'}</span>`; }
function formatAmount(value) {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toFixed(2) : '-';
}
function formatPrice(value) {
  const price = Number(value);
  return Number.isFinite(price) ? price.toFixed(2) : '-';
}
function formatPayload(payload) {
  const source = typeof payload === 'string' ? safeJsonParse(payload) : payload;
  if (!source || typeof source !== 'object') return JSON.stringify(payload || {});
  const normalized = {};
  for (const [key, value] of Object.entries(source)) {
    normalized[key] = key.endsWith('_time') || key === 'event_time' ? formatDateTime(value) : value;
  }
  return JSON.stringify(normalized);
}
function safeJsonParse(value) {
  try { return JSON.parse(value); } catch (_) { return value; }
}
function updateStrategyIntervals(strategies) {
  const intervalOrder = ['1w', '1d', '4h', '1h'];
  const active = new Set(strategies.filter(s => s.enabled).map(s => s.interval));
  const ordered = intervalOrder.filter(interval => active.has(interval));
  document.getElementById('strategyIntervals').textContent = ordered.length ? ordered.join(' / ') : '-';
}
function fillStrategies(items) {
  document.getElementById('strategies').innerHTML = items.map(s => `
    <tr><td>${symbolCell(s.symbol)}</td><td>${intervalCell(s.interval)}</td><td>${s.enabled ? 'YES' : 'NO'}</td><td>${date(s.last_processed_open_time)}</td><td class="muted">${summary(s.params)}</td></tr>
  `).join('');
}
function fillPositions(items) {
  document.getElementById('positions').innerHTML = items.map(p => `
    <tr><td>${symbolCell(p.symbol)}</td><td>${intervalCell(p.interval)}</td><td class="${p.side === 'LONG' ? 'pos' : 'neg'}">${p.side}</td><td>${date(p.entry_time)}</td><td>${formatPrice(p.entry_price)}</td><td>${formatPrice(p.liquidation_price)}</td><td>${Number(p.quantity).toFixed(6)}</td><td>${formatAmount(p.entry_margin)}</td><td>${formatPrice(p.stop_price)}</td><td>${formatPrice(p.initial_take_price)}</td><td>${formatPrice(p.latest_take_price)}</td></tr>
  `).join('') || '<tr><td colspan="11" class="muted">暂无持仓</td></tr>';
}
function tradeRow(t) {
  return `<tr><td>${symbolCell(t.symbol)}</td><td>${intervalCell(t.interval)}</td><td class="${t.side === 'LONG' ? 'pos' : 'neg'}">${t.side}</td><td>${date(t.entry_time)}</td><td>${date(t.exit_time)}</td><td>${Number(t.entry_price).toFixed(2)}</td><td>${Number(t.exit_price).toFixed(2)}</td><td class="${t.pnl >= 0 ? 'pos' : 'neg'}">${Number(t.pnl).toFixed(2)}</td><td class="${t.pnl_pct >= 0 ? 'pos' : 'neg'}">${Number(t.pnl_pct).toFixed(2)}%</td><td>${t.exit_reason}</td></tr>`;
}
function fillTradeRecords(items) {
  document.getElementById('tradeRecords').innerHTML = items.map(tradeRow).join('') || '<tr><td colspan="10" class="muted">暂无交易记录</td></tr>';
}
function fillTrades(items) {
  document.getElementById('trades').innerHTML = items.map(tradeRow).join('') || '<tr><td colspan="10" class="muted">暂无平仓记录</td></tr>';
}
function fillEvents(items) {
  document.getElementById('events').innerHTML = items.map(e => `
    <tr><td>${date(e.event_time)}</td><td>${symbolCell(e.symbol)} ${intervalCell(e.interval)}</td><td>${e.event_type}</td><td class="muted">${formatPayload(e.payload)}</td></tr>
  `).join('') || '<tr><td colspan="4" class="muted">暂无运行日志</td></tr>';
}
function summary(p) {
  return `EMA${p.ema_period}/MA${p.ma_period}, ADX${p.adx_min}, RSI ${p.long_rsi_min}-${p.long_rsi_max}, SL${p.stop_atr}, TP${p.take_atr}, Step${p.take_atr_step}, Max${p.take_atr_max}, Regime ${p.regime_switch ? 'YES' : 'NO'}`;
}
document.addEventListener('DOMContentLoaded', () => {
  loadAll().finally(() => openMarketTickerStream());
  updateUtc8Clock();
  setInterval(updateUtc8Clock, 1000);
  setInterval(loadMarketTicker, 60000);
});
</script>
</body>
</html>
"""


ETH_HTML = (
    HTML.replace("<title>BTCUSDT 模拟自动交易系统</title>", "<title>ETHUSDT 日线回测系统</title>")
    .replace("BTCUSDT U本位永续合约模拟交易系统", "ETHUSDT U本位永续合约日线回测系统")
    .replace('href="/eth">ETH 回测</a>', 'href="/">BTC 回测</a>')
    .replace("推荐：BTCUSDT", "推荐：ETHUSDT")
    .replace('id="symbol" value="BTCUSDT"', 'id="symbol" value="ETHUSDT"')
    .replace("BTCUSDT U本位永续合约按", "ETHUSDT U本位永续合约按")
    .replace("合约数量单位是 BTC", "合约数量单位是 ETH")
    .replace("合约数量(BTC)", "合约数量(ETH)")
    .replace("const PAGE_SYMBOL = 'BTCUSDT';", "const PAGE_SYMBOL = 'ETHUSDT';")
    .replace("const PAGE_INTERVAL = '1w';", "const PAGE_INTERVAL = '1d';")
    .replace("周期 1w", "周期 1d")
    .replace('<option value="1w" selected>1w</option><option value="1d">1d</option><option value="4h">4h</option><option value="1h">1h</option>', '<option value="1w">1w</option><option value="1d" selected>1d</option><option value="4h">4h</option><option value="1h">1h</option>')
    .replace("动态止盈启动 ATR 倍数。推荐：7.5", "动态止盈启动 ATR 倍数。推荐：6.5")
    .replace('id="takeAtr" type="number" step="0.1" value="7.5"', 'id="takeAtr" type="number" step="0.1" value="6.5"')
    .replace("动态止盈最高 ATR 倍数上限。推荐：32", "动态止盈最高 ATR 倍数上限。推荐：24")
    .replace('id="takeAtrMax" type="number" step="0.5" value="32"', 'id="takeAtrMax" type="number" step="0.5" value="24"')
)
