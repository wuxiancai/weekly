# Handoff

## 当前状态

已搭建 BTCUSDT 模拟自动交易系统第一版：

- FastAPI Web 页面。
- SQLite 数据库。
- Binance Futures REST K 线同步。
- 可选 Binance WebSocket kline 采集脚本。
- EMA/MA + RSI/ADX/MACD/Bollinger/ATR/Volume 策略。
- 多空回测、止盈止损、参数优化。
- 虚拟环境启动脚本和 systemd 安装脚本。
- 根目录 `start.sh` 可在 macOS/Ubuntu 自适应一键启动。
- 回测已改为上一根已收盘 K 线出信号、下一根 K 线开盘成交，降低未来函数风险。
- 周线止盈止损已改为收盘确认，不再用周内最高价/最低价插针触发。
- Web 页面新增 Walk-forward 样本外验证。

## 本轮验证

- `python3 -m py_compile app/*.py` 通过。
- `python3 -m unittest discover -s tests -v`：2 个测试通过。
- Binance REST 拉取 `2021-11-15` 到 `2026-07-02` 的 `BTCUSDT 1w`：入库 242 根周 K。
- 默认 `EMA15/MA50` 回测：初始 `1000`，最终 `2489.91`，收益率 `148.99%`，最大回撤 `33.15%`，6 笔交易，胜率 `66.67%`。
- 参数搜索当前最高收益组合：`EMA21/MA60`、`ADX>=14`、`SL=3.0 ATR`、`TP=5.5 ATR`、`volume_mult=0.75`，历史收益率 `331.71%`，最大回撤 `29.68%`，5 笔交易。
- 已用浏览器验证页面标题、按钮、图表、指标和逐笔交易展示。

## 最新验证

- `python3 -m py_compile app/*.py` 通过。
- `python3 -m unittest discover -s tests -v`：4 个测试通过。
- `./start.sh` 在 macOS 上识别系统并启动到 `0.0.0.0:8000`。
- 防未来函数后，默认回测第一笔交易信号日为 `2023-03-27`，实际入场日为下一根周 K `2023-04-03`。
- Walk-forward API：训练段 `2021-11-15` 至 `2025-02-03`，测试段 `2025-02-10` 至 `2026-06-29`。
- 页面点击“样本外验证”成功渲染 10 条结果，无水平溢出。

## 2026-07-02 更新

- 用户确认策略必须是周线收盘确认趋势，不吃周内插针止损。
- `app/backtest.py` 已将止盈止损触发从周内 `high/low` 改为当前 K 线 `close` 确认；反向信号仍按下一根 K 线开盘成交。
- 新增回归测试：多单周内最低价跌破止损、但收盘价收回止损线上方时，不触发 `STOP_LOSS`。
- `python3 -m unittest discover -s tests -v`：5 个测试通过。
- 使用数据库全量 `BTCUSDT 1w` 复算默认 `EMA15/MA50`：初始 `1000`，最终 `3910.7953`，收益率 `291.0795%`，最大回撤 `33.1507%`，6 笔交易，胜率 `83.3333%`。
- 原 `2024-04-22 -> 2024-08-05` 插针止损交易已变为 `2024-04-22 -> 2024-11-18` 止盈，入场 `64925.6825`，出场 `90716.1685`，收益 `921.1991`，原因 `TAKE_PROFIT`。

## 2026-07-02 趋势内再入场更新

- `app/strategy.py` 新增趋势内再入场：`EMA > MA` 大趋势中，上一根周 K 回调到 EMA/MA 下方后重新收上 EMA，且方向指标、RSI、成交量过滤通过，则允许 `LONG`。
- 新增回归测试：回调后重新站上趋势，即使 MACD/Bollinger 的原追涨过滤不通过，也能给出再入场 `LONG`。
- 使用 `EMA15/MA40, stop_atr=2.4, take_atr=8.0, long_rsi=35-85, short_rsi=0-100, ADX>=0` 测试成交量参数：
  - `volume_mult=0.75`：2020-07-01 至 2026-06-29 窗口收益 `1512.5933%`，最大回撤 `47.1446%`，8 笔，胜率 `87.5%`；红框内多头信号 26 个，但 2025-07-21 多单后续止损 `-18.2445%`。
  - `volume_mult=1.0`：窗口收益 `2092.7637%`，最大回撤 `47.1446%`，7 笔，胜率 `100%`；红框内多头信号 7 个。
  - `volume_mult=1.25`：窗口收益 `1888.1636%`，最大回撤 `44.7556%`，7 笔，胜率 `100%`；红框内没有新的多头信号，但 2024-03-25 已有多单持有到 2025-07-07。

## 2026-07-02 动态阶梯止盈更新

- `app/backtest.py` 新增动态阶梯止盈参数：`take_atr_step`、`take_atr_max`、`take_atr_buffer_pct`。默认 `take_atr_step=0`，保持固定止盈旧行为；显式设置后启用 `TRAIL_TAKE_PROFIT`。
- 新增回归测试：多单达到 8ATR 后不立即固定止盈，而是上移保护位；后续收盘跌回保护位后 `TRAIL_TAKE_PROFIT`。
- 验证：
  - `python3 -m py_compile app/*.py` 通过。
  - `python3 -m unittest discover -s tests -v`：7 个测试通过。
- 正式代码回测，窗口 `2020-07-01` 至 `2026-06-29`：
  - 固定 8ATR，`EMA15/MA40, long_rsi=35-85, short_rsi=0-100, stop_atr=2.4, volume_mult=1.25`：收益 `1888.1636%`，最大回撤 `44.7556%`，7 笔，胜率 `100%`。
  - 动态止盈同参数，加 `take_atr_step=0.25, take_atr_max=20, take_atr_buffer_pct=0`：收益 `2068.7418%`，最大回撤 `44.7556%`，6 笔，胜率 `100%`。
  - 动态止盈且 `volume_mult=1.0`：收益 `4106.2958%`，最大回撤 `47.1446%`，7 笔，胜率 `100%`。
  - 低回撤候选：`long_rsi=55-75, short_rsi=0-100, stop_atr=0.8, take_atr_step=1.0, take_atr_max=20, volume_mult=1.25`：收益 `1268.1879%`，最大回撤 `23.6011%`，4 笔，胜率 `100%`。
- 注意：动态止盈与“趋势内再入场”叠加后，收益/回撤不再完全等同于此前临时模拟；趋势内再入场会增加部分 2021 或 2024 的再入场，需要重新筛参数。

## 2026-07-02 默认收益最大化参数更新

- 默认策略参数已更新为本轮固定 `volume_mult=1.0` 的收益最大组合：
  - `EMA15 / MA40`
  - `ADX >= 0`
  - `long_rsi = 35 - 85`
  - `short_rsi = 0 - 100`
  - `stop_atr = 1.8`
  - `take_atr = 7.5`
  - `take_atr_step = 1.25`
  - `take_atr_max = 24.0`
  - `take_atr_buffer_pct = 0`
  - `volume_mult = 1.0`
- 回测 API 改为加载结束日前全部本地历史 K 线做指标预热，并用 `start_trading_ms` 限制只在用户选择开始日期后开仓；页面返回的 K 线和权益曲线仍过滤到用户选择窗口内。
- 默认页面参数已同步为 `2020-07-01` 至 `2026-06-29`、`EMA15 / MA40`、`ADX=0`。
- 参数优化网格已同步到当前动态止盈策略空间，固定默认 `volume_mult=1.0` 搜索，并包含 `take_atr_step`、`take_atr_max`。
- 默认 API 回测 `BacktestRequest()` 结果：
  - 收益率 `7057.9855%`
  - 最大回撤 `47.1446%`
  - 交易 `7` 笔
  - 胜率 `100%`
  - 逐笔：
    - `LONG 2020-08-03 -> 2021-01-11 +240.3694% TRAIL_TAKE_PROFIT`
    - `LONG 2021-01-25 -> 2021-11-15 +100.4495% TRAIL_TAKE_PROFIT`
    - `SHORT 2022-02-07 -> 2023-02-27 +44.3915% REVERSE_SIGNAL`
    - `LONG 2023-02-27 -> 2023-12-11 +78.576% TRAIL_TAKE_PROFIT`
    - `LONG 2023-12-18 -> 2024-04-01 +70.9716% TRAIL_TAKE_PROFIT`
    - `LONG 2024-04-15 -> 2025-07-14 +80.6315% TRAIL_TAKE_PROFIT`
    - `SHORT 2025-12-08 -> 2026-06-29 +32.1202% END_OF_TEST`
- 验证：
  - `python3 -m py_compile app/*.py` 通过。
  - `python3 -m unittest discover -s tests -v`：8 个测试通过。
  - `python3` 直接调用 `app.main.backtest(BacktestRequest())` 已生成 `run_id=9` 并复现上述指标。
  - `python3` 直接调用 `app.main.optimize_api(BacktestRequest(), max_results=5)`：第 1 名为默认参数，收益率 `7057.9855%`，最大回撤 `47.1446%`，7 笔。

## 2026-07-02 默认开始日期更新为 2019-09-02

- 默认开始日期已从 `2020-07-01` 改为 `2019-09-02`：
  - `app/config.py` 的 `DEFAULTS.start_date`
  - Web 页面开始日期输入框
  - `docs/PROJECT_CONTEXT.md`
- 新增测试：
  - 默认开始日期必须是 `2019-09-02`。
  - `EMA15/MA40` 下，少于 40 根周 K 时 `MA40=None` 且信号全部为 `HOLD`；第 40 根周 K 后 MA40 才成型。
- 当前本地数据验证：
  - `2019-09-02 -> 2026-06-29` 默认 API 回测收益率 `7045.059%`，最大回撤 `47.1446%`，7 笔，胜率 `100%`。
  - 第一笔交易信号：`2020-07-27`，入场：`2020-08-03`，说明信号来自上一根已收盘周 K，交易在下一根周 K 开盘执行。
  - 从 `2019-09-02` 起，第一个 MA40 出现在 `2020-06-01`，第一笔非 `HOLD` 信号是窗口内第 48 根周 K。
- 对未来函数的当前结论：
  - 入场信号路径规避未来函数：`row.signal` 用该周收盘后数据生成，`run_backtest()` 使用 `previous["signal"]` 在下一根周 K 的 `open` 入场。
  - 指标计算不会在 MA40 未成型前出信号：`sma()` 在 `i + 1 < period` 时返回 `None`，`signal_for()` 发现必需指标为 `None` 直接返回 `HOLD`。
  - 止盈/止损是周线收盘确认模型，非周内插针模型；当前实现确认后按保护价/止盈价成交，这是策略撮合假设，不是用未来 K 线生成入场信号。

## 2026-07-02 资金模型与回测参数页面更新

- 默认初始本金从 `1000` 调整为 `10000`。
- 新增杠杆参数：
  - 默认 `0`，表示不使用杠杆。
  - 正数表示名义仓位倍率，例如 `2` 表示按 2 倍名义仓位计算盈亏和手续费。
- 回测资金模型支持固定本金和复利；当时默认仍为复利模式，后续已在 `2026-07-03` 改为默认固定本金。
- 回测页面已显示并可手动修改所有会影响回测结果的主要参数：
  - 本金、杠杆、手续费、滑点
  - EMA/MA
  - RSI/ATR/ADX 周期
  - ADX 最小值
  - 多空 RSI 区间
  - 止损 ATR、止盈 ATR、动态止盈阶梯、动态止盈上限、止盈缓冲
  - 成交量过滤倍数
- 每个参数输入框已增加鼠标悬停说明和推荐值。
- 参数优化结果和 Walk-forward 参数列已改为显示完整参数摘要，不再只显示 EMA/MA、ADX、SL、TP。
- 当前验证：
  - `python3 -m py_compile app/*.py` 通过。
  - `python3 -m unittest discover -s tests -v`：13 个测试通过。
  - 默认回测：本金 `10000`，杠杆 `0`，最终资金 `713275.6931`，收益率 `7032.7569%`。
  - 杠杆 `2` 回测：最终资金 `8722639.1458`，收益率 `87126.3915%`；第一笔收益从 `24027.3293` 放大到 `48054.6587`。
  - `curl http://127.0.0.1:8000/` 已确认页面返回新字段：本金、杠杆、止盈阶梯、量能倍数等。

## 2026-07-03 BTCUSDT U本位永续页面口径更新

- 已查 Binance 官方文档确认 BTCUSDT USDⓈ-M Futures 盈亏口径：
  - USDⓈ-M Futures 使用 USDT 等稳定币作为保证金。
  - 仓位和合约数量按币数量计算，例如 BTCUSDT 数量单位是 BTC。
  - BTCUSDT 多单收益公式：`(出场价 - 入场价) * 合约数量`，收益单位为 USDT。
  - BTCUSDT 空单收益公式可等价写为 `(入场价 - 出场价) * 合约数量`，收益单位为 USDT。
- 页面已更新以避免币本位误解：
  - 标题改为 `BTCUSDT U本位永续合约模拟交易系统`。
  - 顶部状态显示 `USDT 保证金 / USDT 结算`。
  - 逐笔交易表头改为 `入场价(USDT)`、`出场价(USDT)`、`合约数量(BTC)`、`收益(USDT)`。
  - 逐笔交易上方新增公式说明和 Binance PnL 官方说明链接。
- 新增测试：页面必须包含 `BTCUSDT U本位永续合约`、`USDT 保证金 / USDT 结算`、`收益(USDT)`、`合约数量(BTC)` 和多单收益公式。

## 2026-07-03 复利参数更新

- 回测页面新增 `复利` 参数：
  - 默认 `NO`。
  - `NO`：每笔按固定本金开仓，不把上一笔收益自动加入下一笔开仓本金。
  - `YES`：每笔按当前权益开仓，上一笔收益或亏损会影响下一笔仓位。
- 后端 `BacktestRequest`、`run_backtest()`、`optimize()` 已增加 `compound` 参数。
- 默认配置 `DEFAULTS.compound=False`。
- 新增测试：
  - 默认复利为 `False`。
  - 页面有 `复利` 下拉框且默认 `NO`。
  - 复利开启后，盈利后的第二笔交易合约数量大于固定本金模式。

## 2026-07-03 逐笔交易指标与布局更新

- 回测页面已将 `参数优化结果` 从逐笔交易右侧移动到 `逐笔交易` 下方，避免两张宽表在同一行挤压。
- `逐笔交易` 新增列：
  - `收益率`：单笔净收益 / 本笔开仓本金。
  - `盈亏比`：单笔净收益 / 初始止损风险金额。
  - `最大回撤`：持仓期按周线收盘价计算的最大不利浮亏 / 本笔开仓本金，保持“收盘确认、不吃周内插针”的口径。
  - `收益回撤比`：单笔收益率 / 单笔最大回撤。
- 当前验证：
  - `python3 -m py_compile app/*.py` 通过。
  - `python3 -m unittest discover -s tests -v`：18 个测试通过。
  - 默认 API 回测仍为 7 笔交易，第一笔 `2020-08-03 -> 2021-01-11`：收益 `24027.3293 USDT`，收益率 `240.2733%`，盈亏比 `12.4894`，最大回撤 `7.442%`，收益回撤比 `32.2863`。

## 2026-07-03 周线默认策略参数固化

- 用户确认周线交易策略按最终截图参数作为默认值，后续不再修改默认参数。
- 当前默认参数：
  - `BTCUSDT`、`1w`、`2019-09-02 -> 2026-06-29`
  - 本金 `10000`、复利 `YES`、杠杆 `2`
  - 手续费 `0.0005`、滑点 `0.0005`
  - `EMA15 / MA40`
  - `RSI14 / ATR14 / ADX14`
  - `ADX >= 0`
  - 多头 RSI `35-85`，空头 RSI `0-100`
  - 止损 `1.8 ATR`，止盈启动 `7.5 ATR`，止盈阶梯 `1.25 ATR`，止盈上限 `32 ATR`，止盈缓冲 `0`
  - 量能倍数 `1`
- 当前默认 API 回测结果：
  - 最终资金 `8707618.282 USDT`
  - 总收益率 `86976.1828%`
  - 最大回撤 `64.4756%`
  - 交易 `7` 笔，胜率 `100%`

## 2026-07-03 BTC 日线基准与 ETH 回测页面

- 已同步 Binance Futures 日线数据：
  - `BTCUSDT 1d`：`2487` 根
  - `ETHUSDT 1d`：`2407` 根
- 第一步基准：`BTCUSDT 1d` 直接套周线默认参数，结果：
  - 最终资金 `127192.1885 USDT`
  - 总收益率 `1171.9219%`
  - 最大回撤 `82.9066%`
  - 交易 `80` 笔，胜率 `40%`
- ETHUSDT 日线优化结果：
  - 当前优化网格收益率最高参数为 `EMA15/MA40, ADX>=0, long RSI 35-85, short RSI 0-100, stop_atr=1.8, take_atr=6.5, take_atr_step=1.25, take_atr_max=24, volume_mult=1`
  - 回测结果：最终资金 `15372444.3602 USDT`，收益率 `153624.4436%`，最大回撤 `94.3642%`，交易 `76` 笔，胜率 `43.4211%`
- 首页右上角已增加 `ETH 回测`，进入 `/eth`。
- `/eth` 页面功能和排版与首页一致，默认 `ETHUSDT / 1d`，并使用上述 ETH 日线收益率最高参数。

## 2026-07-03 周线/日线独立周期默认参数

- 用户补充确认：所有周期交易策略都按独立模块看待，例如周线和日线相互不干涉；当周线有问题时，日线仍应能继续回测。
- 页面 `周期` 参数已从普通输入框改为下拉框，支持 `1w` 和 `1d`。
- 页面新增 `STRATEGY_DEFAULTS` 前端配置表，按 `symbol + interval` 应用默认参数：
  - `BTCUSDT / 1w`：保留已固化周线默认参数。
  - `BTCUSDT / 1d`：独立日线配置项，当前沿用此前 BTC 日线基准参数。
  - `ETHUSDT / 1w`：独立周线配置项，使用周线口径 `take_atr=7.5`、`take_atr_max=32`。
  - `ETHUSDT / 1d`：保留 ETH 日线优化默认参数 `take_atr=6.5`、`take_atr_max=24`。
- 首页默认 `BTCUSDT / 1w`；`/eth` 默认 `ETHUSDT / 1d`。切换周期时会自动刷新当前交易对对应周期的页面参数，方便回测。
- 注意：`ETHUSDT / 1w` 当前只是独立默认槽位，尚未做新的专门优化。

## 2026-07-03 BTCUSDT 日线默认参数更新

- 用户要求把无杠杆、最大单笔回撤 50% 内收益优先组合设为 BTC 日线默认，并同步到 Web 页面。
- `STRATEGY_DEFAULTS.BTCUSDT['1d']` 已更新：
  - `BTCUSDT`、`1d`、`2019-09-02 -> 2026-06-29`
  - 本金 `10000`、复利 `YES`、杠杆 `0`
  - 手续费 `0.0005`、滑点 `0.0005`
  - `EMA8 / MA40`
  - `RSI14 / ATR14 / ADX14`
  - `ADX >= 0`
  - 多头 RSI `50-80`，空头 RSI `0-100`
  - 止损 `1.6 ATR`，止盈启动 `13 ATR`，止盈阶梯 `0.75 ATR`，止盈上限 `18 ATR`，止盈缓冲 `0`
  - 量能倍数 `0.75`
- 本地 BTCUSDT 日线数据回测口径：`2019-09-02 -> 2026-06-29`，实际数据 `2019-09-08 -> 2026-06-29`，无杠杆、复利。
- 回测结果：最终资金 `423306.4908 USDT`，收益率 `4133.0649%`，最大单笔回撤 `16.7364%`，周期权益曲线最大回撤 `47.4249%`，交易 `72` 笔，胜率 `43.0556%`，盈利因子 `1.8982`。
- `BTCUSDT / 1w` 周线默认策略保持不变；`ETHUSDT / 1d` 默认策略保持不变。

## 2026-07-03 回撤口径修正

- 用户指出此前“最大回撤 50% 内”应按逐笔交易里的某一笔最大不利浮亏理解，不应按整段周期权益曲线总回撤理解。
- `run_backtest()` 的汇总 `metrics.max_drawdown_pct` 已改为最大单笔回撤，即 `max(trade.max_drawdown_pct)`。
- 新增 `metrics.max_trade_drawdown_pct` 明确表示最大单笔回撤。
- 原周期权益曲线总回撤保留为 `metrics.equity_max_drawdown_pct`，仅用于对照。
- Web 页面顶部、参数优化结果、Walk-forward 表头已改为 `最大单笔回撤`，避免误解。

## 2026-07-03 4h 独立周期默认参数与基准回测

- 用户要求按新增 `1d` 的逻辑再增加 `4h` 交易策略，并且 `4h` 必须与周线、日线完全独立。

## 2026-07-03 实盘模拟 / Paper Trading 更新

- 新增 `app/paper.py`：
  - 默认共享模拟账户 `1000 USDT`。
  - 默认运行 `BTCUSDT / 1d`、`BTCUSDT / 4h`、`ETHUSDT / 1d`、`ETHUSDT / 4h` 四个独立策略。
  - 复用现有 `StrategyParams`、`enrich_candles()`、`Position`、ATR 止损、动态止盈、U本位 PnL 计算。
  - SQLite 表包括 `paper_accounts`、`paper_strategies`、`paper_positions`、`paper_trades`、`paper_equity_curve`、`paper_events`。
  - `process_strategy()` 按 `last_processed_open_time` 增量处理，防止重复处理同一根 K 线。
  - `prime_strategy()` 用于首次启动：只预热历史 K 线并标记最新已收盘 K 线，不把历史信号模拟成交。
- 新增 `app/paper_runner.py`：
  - REST 轮询 Binance Futures 已收盘 K 线。
  - 默认 `PAPER_WARMUP_CANDLES=500`、`PAPER_POLL_SECONDS=60`。
  - 每轮同步 K 线、处理增量信号、记录运行事件；异常写入 `paper_events`。
- Web 更新：
  - 首页右上角新增 `模拟交易`，进入 `/paper`。
  - 新增 `/api/paper/status`，返回模拟账户、策略、持仓、最近平仓、权益曲线和运行日志。
  - `/paper` 页面展示模拟账户资金、当前持仓、策略状态、最近平仓和运行日志。
- 部署更新：
  - 新增 `scripts/run_paper.sh`，使用项目 `.venv` 运行 `app.paper_runner`。
  - 新增 `scripts/deploy_one_click.sh`，自适应 Ubuntu 安装依赖，创建虚拟环境，安装 Python requirements，并写入两个 systemd 服务：
    - `weekly-web`：运行 Web，监听 `0.0.0.0:${PORT:-8000}`。
    - `weekly-paper`：运行模拟交易 runner。
  - 一键部署后访问 `http://服务器IP:8000/paper` 查看实盘模拟状态。
- 本轮验证：
  - `python3 -m py_compile app/*.py` 通过。
  - `python3 -m unittest discover -s tests -v`：29 个测试通过。
  - `bash -n scripts/deploy_one_click.sh scripts/run_paper.sh start.sh scripts/start.sh` 通过。

## 2026-07-03 Paper Trading 补充日线策略

- 用户指出模拟交易系统也必须包含日线交易策略。
- `paper_strategy_defaults()` 已改为默认四个策略：
  - `BTCUSDT / 1d`：复用 BTC 日线默认 `EMA8 / MA40`、`ADX >= 0`、多头 RSI `50-80`、止损 `1.6 ATR`、动态止盈启动 `13 ATR`、阶梯 `0.75`、上限 `18`、量能 `0.75`。
  - `BTCUSDT / 4h`：保留状态切换默认策略。
  - `ETHUSDT / 1d`：复用 ETH 日线默认 `EMA15 / MA40`、`ADX >= 0`、多头 RSI `35-85`、止损 `1.8 ATR`、动态止盈启动 `6.5 ATR`、阶梯 `1.25`、上限 `24`、量能 `1`。
  - `ETHUSDT / 4h`：保留状态切换默认策略。
- `/paper` 状态页顶部改为展示策略周期 `1d / 4h`。

## 2026-07-04 增加 1h 独立周期策略

- 用户要求根据 `1d`、`4h` 的交易策略模块和回测模块逻辑，增加 BTCUSDT / ETHUSDT 的 `1h` 独立交易和回测模块。
- Web 页面更新：
  - `周期` 下拉新增 `1h`。
  - `STRATEGY_DEFAULTS.BTCUSDT['1h']` 与 `STRATEGY_DEFAULTS.ETHUSDT['1h']` 已新增独立配置。
  - `1h` 第一版采用盘中状态切换策略：`EMA8 / MA35`、`ADX >= 25`、趋势/震荡/过渡状态切换、震荡 RSI `30/65`、止损 `0.8 ATR`、动态止盈启动 `3.5 ATR`、阶梯 `0.5`、上限 `8`、无杠杆、复利。
- Paper Trading 更新：
  - 默认策略池扩展为六个：`BTCUSDT / 1d`、`BTCUSDT / 4h`、`BTCUSDT / 1h`、`ETHUSDT / 1d`、`ETHUSDT / 4h`、`ETHUSDT / 1h`。
  - `app.paper_runner.INTERVAL_MS` 新增 `1h`，后台会按已收盘 1h K 线增量处理。
  - `/paper` 状态页顶部策略周期改为 `1d / 4h / 1h`。
- 注意：当前 `1h` 参数是独立默认槽位的初始版本，尚未基于本地 1h 历史数据单独优化。
- 页面 `周期` 下拉已新增 `4h`。
- `STRATEGY_DEFAULTS` 已新增独立 4h 默认参数：
  - `BTCUSDT / 4h`：当前先复制 `BTCUSDT / 1d` 默认参数，`EMA8 / MA40`、无杠杆、复利、止损 `1.6 ATR`、动态止盈启动 `13 ATR`、止盈阶梯 `0.75 ATR`、止盈上限 `18 ATR`、量能 `0.75`。
  - `ETHUSDT / 4h`：当前先复制 `ETHUSDT / 1d` 默认参数，`EMA15 / MA40`、杠杆 `2`、复利、止损 `1.8 ATR`、动态止盈启动 `6.5 ATR`、止盈阶梯 `1.25 ATR`、止盈上限 `24 ATR`、量能 `1`。
- 已同步 Binance Futures `BTCUSDT 4h` 数据：`14913` 根，实际数据 `2019-09-08` 至 `2026-06-29`。
- 使用 `BTCUSDT / 4h` 当前默认参数回测，窗口 `2019-09-02 -> 2026-06-29`：
  - 最终资金 `14334.2162 USDT`
  - 总收益率 `43.3422%`
  - 最大单笔回撤 `12.9856%`
  - 周期权益曲线最大回撤 `78.9097%`
  - 交易 `523` 笔
  - 胜率 `26.0038%`
  - 盈利因子 `1.0454`
- 结论：这只是 1d 参数下放到 4h 的基准结果，不是 4h 专门优化参数；4h 周期噪音明显更高，交易次数大幅增加，后续若追求 4h 收益应单独优化过滤与出场参数。

## 2026-07-03 BTCUSDT 4h 默认参数与平衡候选

- 用户要求先将上一轮 `BTCUSDT / 4h` 收益最高参数设置为 4h 回测默认值，并继续寻找更平衡的优化点。
- 用户随后确认把更平衡候选写入默认；Web 页面 `STRATEGY_DEFAULTS.BTCUSDT['4h']` 当前默认：
  - `EMA8 / MA35`
  - `ADX >= 25`
  - 多头 RSI `50-80`，空头 RSI `0-100`
  - 止损 `0.8 ATR`
  - 动态止盈启动 `3.5 ATR`
  - 止盈阶梯 `0.5 ATR`
  - 止盈上限 `8 ATR`
  - `volume_mult = 1.0`
  - 本金 `10000`、复利 `YES`、杠杆 `0`
- 当前默认回测结果，`BTCUSDT 4h`，实际数据 `2019-09-08` 至 `2026-06-29`：
  - 最终资金 `319351.51 USDT`
  - 总收益率 `3093.52%`
  - 最大单笔回撤 `9.73%`
  - 周期权益曲线最大回撤 `40.23%`
  - 交易 `460` 笔
  - 胜率 `25.22%`
  - 盈利因子 `1.502`
- 结论：当前 4h 默认仍不是高胜率策略，而是低胜率、高盈亏比、趋势捕捉型参数；相比上一组 `ADX>=14, TP=4, Max=12, Vol=0.75`，交易次数接近减半、盈利因子明显更高、权益曲线回撤更低。

## 2026-07-03 BTCUSDT 4h 状态切换策略更新

- 用户要求 4h 策略支持趋势和震荡两类行情。
- `app/strategy.py` 新增 `market_regime_for()` 和 `regime_switch` 参数：
  - `TREND`：`ADX >= adx_min` 且 EMA/MA 分离度达到 `trend_ma_gap_min`，沿用原趋势信号。
  - `RANGE`：`ADX <= range_adx_max` 且布林带宽低于 `range_bb_width_max`，使用布林带 + RSI 均值回归。
  - `NEUTRAL`：趋势和震荡都不明确时不开仓。
- Web 页面新增可手动修改的状态策略参数：
  - 状态策略 `regimeSwitch`
  - 趋势间距 `trendMaGapMin`
  - 震荡 ADX `rangeAdxMax`
  - 震荡带宽 `rangeBbWidthMax`
  - 震荡多 RSI `rangeRsiLow`
  - 震荡空 RSI `rangeRsiHigh`
- 当前 `BTCUSDT / 4h` 默认：
  - `regimeSwitch = YES`
  - `EMA8 / MA35`
  - `ADX >= 25`
  - `trend_ma_gap_min = 0`
  - `range_adx_max = 18`
  - `range_bb_width_max = 0.08`
  - `range_rsi_low = 30`
  - `range_rsi_high = 65`
  - 止损 `0.8 ATR`、动态止盈启动 `3.5 ATR`、止盈阶梯 `0.5 ATR`、止盈上限 `8 ATR`
  - 本金 `10000`、复利 `YES`、杠杆 `0`
- 当前本地 BTCUSDT 4h 数据 `2019-09-08` 至 `2026-06-29` 的内存回测结果：
  - 最终资金 `440399.81 USDT`
  - 总收益率 `4304.00%`
  - 最大单笔回撤 `9.73%`
  - 周期权益曲线最大回撤 `34.16%`
  - 交易 `538` 笔
  - 胜率 `25.84%`
  - 盈利因子 `1.5005`
- 对比上一版单一趋势 4h 默认：
  - 最终资金 `319351.51 USDT`
  - 总收益率 `3093.52%`
  - 周期权益曲线最大回撤 `40.23%`
  - 交易 `460` 笔
  - 胜率 `25.22%`
  - 盈利因子 `1.5023`
- 结论：新 4h 状态切换策略收益更高、权益曲线最大回撤更低，但交易次数增加，胜率仍低；它是趋势 + 震荡混合策略的第一版，不应被理解为高胜率策略。

## 2026-07-03 ETHUSDT 4h 状态切换策略更新

- 用户要求 ETH 4h 同理按趋势 + 震荡状态切换逻辑修改。
- Web 页面 `STRATEGY_DEFAULTS.ETHUSDT['4h']` 已改为独立 4h 状态切换默认：
  - `regimeSwitch = YES`
  - `EMA8 / MA35`
  - `ADX >= 25`
  - `trend_ma_gap_min = 0`
  - `range_adx_max = 18`
  - `range_bb_width_max = 0.08`
  - `range_rsi_low = 30`
  - `range_rsi_high = 65`
  - 止损 `0.8 ATR`、动态止盈启动 `3.5 ATR`、止盈阶梯 `0.5 ATR`、止盈上限 `8 ATR`
  - 本金 `10000`、复利 `YES`、杠杆 `0`
- 当前本地 ETHUSDT 4h 数据 `2019-11-27` 至 `2026-06-29` 的内存回测结果：
  - 最终资金 `310644.88 USDT`
  - 总收益率 `3006.45%`
  - 最大单笔回撤 `12.81%`
  - 周期权益曲线最大回撤 `47.12%`
  - 交易 `525` 笔
  - 胜率 `23.43%`
  - 盈利因子 `1.3682`
- 对照：仅在 ETH 旧 4h 参数上打开状态策略但保留 `ADX >= 0` 时结果不变，因为所有 K 线都会被判定为 `TREND`，震荡分支不会生效。
- 该修改只影响 `ETHUSDT / 4h`，不改变 ETH 日线、ETH 周线或 BTC 任一周期默认策略。

## 2026-07-04 1h 参数优化与默认值同步

- 用户要求先提交端口修改，再执行 1h 策略优化，找出收益率最高、胜率最高组合；一旦发现最优参数就写为默认。
- 端口提交已完成：`7c0886f Set deploy default port to 8001`。
- 已同步本地 Binance Futures 1h 数据：
  - `BTCUSDT 1h`：`59648` 根，实际数据 `2019-09-08` 至 `2026-06-29`。
  - `ETHUSDT 1h`：`57738` 根，实际数据 `2019-11-27` 至 `2026-06-29`。
- 本轮优化口径：`2019-09-02 -> 2026-06-29`，本金 `10000`，复利 `YES`，杠杆 `0`，手续费 `0.0005`，滑点 `0.0005`。
- `BTCUSDT / 1h` 已写入收益最高/综合评分第一默认参数：
  - `EMA12 / MA35`
  - `ADX >= 18`
  - 多头 RSI `55-85`，空头 RSI `0-100`
  - 止损 `0.45 ATR`
  - 动态止盈启动 `4.0 ATR`
  - 止盈阶梯 `1.0 ATR`
  - 止盈上限 `12 ATR`
  - `volume_mult = 1.25`
  - `regimeSwitch = YES`
  - `trend_ma_gap_min = 0`
  - `range_adx_max = 22`
  - `range_bb_width_max = 0.05`
  - `range_rsi_low = 35`
  - `range_rsi_high = 65`
- BTC 该默认回测结果：
  - 最终资金 `1135530.27 USDT`
  - 总收益率 `11255.30%`
  - 最大单笔回撤 `9.19%`
  - 周期权益曲线最大回撤 `25.47%`
  - 交易 `3290` 笔
  - 胜率 `17.36%`
  - 盈利因子 `1.3347`
- BTC 胜率最高候选：`EMA15/MA50, ADX>=35, stop_atr=1.5, take_atr=1.8, volume_mult=1.25`，胜率 `43.97%`，收益率 `716.77%`。当前默认仍按用户目标采用收益最高组合。
- `ETHUSDT / 1h` 已写入收益最高/综合评分第一默认参数：
  - `EMA15 / MA50`
  - `ADX >= 25`
  - 多头 RSI `50-80`，空头 RSI `0-100`
  - 止损 `0.45 ATR`
  - 动态止盈启动 `1.8 ATR`
  - 止盈阶梯 `0.5 ATR`
  - 止盈上限 `4 ATR`
  - `volume_mult = 1`
  - `regimeSwitch = YES`
  - `trend_ma_gap_min = 0`
  - `range_adx_max = 22`
  - `range_bb_width_max = 0.12`
  - `range_rsi_low = 30`
  - `range_rsi_high = 65`
- ETH 该默认回测结果：
  - 最终资金 `44505509.77 USDT`
  - 总收益率 `444955.10%`
  - 最大单笔回撤 `7.34%`
  - 周期权益曲线最大回撤 `40.91%`
  - 交易 `3280` 笔
  - 胜率 `23.87%`
  - 盈利因子 `1.6648`
- ETH 胜率最高候选：`EMA15/MA50, ADX>=35, stop_atr=1.5, take_atr=1.8, volume_mult=1.25`，胜率 `45.19%`，收益率 `2382.19%`。当前默认仍按用户目标采用收益最高组合。
- Web `STRATEGY_DEFAULTS` 与 Paper Trading `paper_strategy_defaults()` 已同步上述 1h 参数；BTC/ETH 1h 不再共用 4h 默认参数对象。

## 2026-07-04 1h 分段参数复验

- 用户反馈 1h 默认参数不是不同短窗口的最优值，要求不要一次性长跑，而是按 `1个月 / 2个月 / 6个月` 分段回测，并列出高胜率、低单笔最大亏损率、高收益率、高盈亏比等多组参数。
- 新增离线脚本 `scripts/optimize_1h_segmented.py`：
  - 默认分段窗口：`1m=2026-06-02 -> 2026-06-29`、`2m=2026-05-01 -> 2026-06-29`、`6m=2026-01-02 -> 2026-06-29`。
  - 每段先用 90 天预热筛选 864 组 1h 状态切换候选。
  - 入围候选再用页面同口径全历史预热复验 `1m / 2m / 6m / full`。
- 输出文件：
  - `reports/1h_segmented/BTCUSDT_1h_*_raw.csv`
  - `reports/1h_segmented_eth/ETHUSDT_1h_*_raw.csv`
  - `reports/1h_segmented_validated/validated.csv`
  - `reports/1h_segmented_recommendations.md`
- BTCUSDT 当前默认仍是全历史收益最高候选之一：`1m 0.01% / 2m 1.54% / 6m 21.66% / full 11255.30%`，但短窗口表现弱。
- BTCUSDT 三段稳健候选：`EMA8/MA35 ADX>=25 RSI55-85 SL0.45 TP4/1/12 VOL1.25 R22/0.12/30-65`，复验结果 `1m 14.32% / 2m 15.85% / 6m 54.71% / full 3277.98%`，6m 最大单笔回撤 `3.53%`、胜率 `20.21%`、盈利因子 `1.7711`。
- BTCUSDT 高胜率候选：`EMA12/MA35 ADX>=35 RSI50-80 SL1.5 TP1.8/0.5/4 VOL1.25 R22/0.12/30-65`，6m 收益 `26.93%`、胜率 `44.44%`、最大单笔回撤 `3.80%`、盈利因子 `1.4821`。
- ETHUSDT 当前默认仍是全历史收益最高候选之一：`1m 11.35% / 2m 9.32% / 6m 59.61% / full 444955.10%`。
- ETHUSDT 6m 高收益候选：`EMA15/MA50 ADX>=25 RSI50-80 SL0.45 TP4/1/12 VOL1 R22/0.05/35-65`，复验结果 `1m 14.96% / 2m 12.33% / 6m 108.14% / full 203676.50%`，6m 最大单笔回撤 `4.34%`、胜率 `18.55%`、盈利因子 `1.7418`。
- ETHUSDT 三段稳健候选：`EMA8/MA35 ADX>=35 RSI50-80 SL0.45 TP3.5/0.5/8 VOL1.25 R22/0.05/35-65`，复验结果 `1m 22.93% / 2m 21.91% / 6m 84.76% / full 17719.21%`，6m 最大单笔回撤 `4.34%`、胜率 `21.97%`、盈利因子 `2.2036`。
- 本轮只整理候选和证据，未修改 Web / Paper 的 1h 默认参数；如要切默认，建议优先让用户在 `当前默认 / 三段稳健 / 高胜率` 中确认目标。

## 2026-07-04 单笔最大亏损率指标

- 用户要求在回测结果顶部指标卡增加 `单笔最大亏损率`。
- 后端 metrics 使用 `max_single_loss_pct = abs(min(trade.pnl_pct))`，即逐笔交易中亏损率最大的一笔；若无亏损交易则为 `0`。
- Web 顶部指标卡已在 `最大单笔回撤` 后展示 `单笔最大亏损率`，与现有 `最大单笔回撤` 口径区分：
  - `最大单笔回撤`：持仓期间最大不利浮亏。
  - `单笔最大亏损率`：最终平仓后最亏一笔的实现亏损率。

## 2026-07-04 Paper 顶部实时行情与 UTC+8 时钟

- 用户要求在 `/paper` 顶部标题与导航之间增加 BTC/ETH 永续合约实时行情和 UTC+8 实时读秒时间。
- 新增 `/api/market/tickers`，通过 Binance USD-M Futures 当前价格和 UTC+0 当日 `1d` K 线开盘价计算 `BTCUSDT`、`ETHUSDT` 的当日涨跌额与涨跌率，返回口径标记为 `UTC+0`。
- `/paper` 顶部新增单行紧凑状态条：
  - 同一行显示 `BTC 永续`、`ETH 永续` 实时价格、UTC+0 当日涨跌额、UTC+0 当日涨跌率，以及转换后的 `UTC+8 YYYY-MM-DD HH:mm:ss`。
  - 涨为绿色，跌为红色；前端每秒更新时间。
- 行情刷新已改为实时推送：
  - 页面先通过 `/api/market/tickers` 初始化 UTC+0 当日开盘价和当前价。
  - 然后连接 Binance Futures WebSocket `btcusdt@bookTicker/ethusdt@bookTicker`，用买一卖一中间价实时更新 BTC/ETH 永续价格，并按 UTC+0 当日开盘价即时重算涨跌额和涨跌率。
  - REST 行情接口保留为 60 秒一次的 UTC+0 基准价刷新与兜底，不再使用 10 秒轮询作为主行情源。
  - WebSocket 断开后 3 秒自动重连；“刷新”按钮会同时刷新 Paper 状态和 REST 行情基准。若 Binance 行情连接失败，会在行情条直接显示 `行情连接失败`。
- `/paper` 顶部 H1 已按用户在浏览器中选中的标题位置改为 `币安合约交易系统`。

## 2026-07-04 Paper 交易记录模块

- 用户要求在 `/paper` 的 `最近平仓` 上方新增 `交易记录` 显示模块。
- `/api/paper/status` 新增 `trade_records`，按 `paper_trades.id DESC` 返回完整模拟交易记录；原 `trades` 仍保留最近 20 条，用于 `最近平仓`。
- 页面新增 `交易记录` 区块并放在 `最近平仓` 上方，默认容器高度约显示 5 条记录，超过部分在该模块内部滚动。

## 2026-07-04 start.sh 统一启动 Web 与 Paper

- 用户明确要求云服务器部署成功后执行 `./scripts/start.sh` / 根目录 `./start.sh`，所有服务都通过 `start.sh` 启动。
- 根目录 `start.sh` 已改为统一编排入口：
  - 创建/使用 `.venv` 并安装依赖。
  - 启动前用本项目 `.venv` 路径匹配并停止旧 `uvicorn app.main:app` 与 `app.paper_runner` 进程，避免重复启动。
  - 后台启动 `app.paper_runner`，日志写入 `runtime/logs/paper_runner.log`。
  - 同时启动 FastAPI Web/回测系统，监听 `0.0.0.0`；脚本监控 Web 与 Paper，任一子进程退出都会清理另一个并退出，交给 systemd 重启。
- `scripts/deploy_one_click.sh` 已改为只安装/重启 `weekly-web` 一个 systemd 服务，`ExecStart=/usr/bin/env bash ${ROOT_DIR}/start.sh`；如果服务器残留旧 `weekly-paper` 服务，会停止、禁用并删除，避免双 runner。
- `app/paper_runner.py` 的预热 K 线数量改为动态计算：`PAPER_WARMUP_CANDLES`、策略指标周期需求、固定下限 60 取最大值。比如某周期使用 `EMA15/MA50`，至少从执行 `start.sh` 的时间往前拉取 60 根该周期已收盘 K 线。
- Paper 初次启动仍只预热并把最新已收盘 K 线标记为已处理，不会把历史信号立即模拟成交；后续新 K 线收盘才增量处理。

## 启动

```bash
./start.sh
```

默认访问：

```text
http://127.0.0.1:8001
```

## 2026-07-04 Web 默认端口与占用处理

- Web 默认端口已从 `8000` 改为 `8001`，`start.sh`、`scripts/deploy_one_click.sh`、`scripts/install_systemd_service.sh` 保持一致。
- `start.sh` 端口处理规则：
  - 如果候选端口被本项目进程占用，直接终止旧进程并复用该端口重新启动。
  - 如果候选端口被其他应用占用，自动顺延到下一个端口，例如 `8002`、`8003`。
  - 默认最多从起始端口向后检查 50 个端口。

## 2026-07-04 Paper 增加 1w 并动态展示策略周期

- 用户截图显示 `/paper` 顶部策略周期仍是 `1d / 4h`，询问 `1w`、`1h` 是否没有模拟交易。
- 核对代码后结论：
  - `1h` 已经在本地代码中纳入 Paper Trading，截图对应远端页面是旧版本或服务未重启。
  - `1w` 周线此前确实没有加入 Paper Trading 默认策略池。
- `app/paper.py` 已将默认策略池扩展为 8 个：
  - `BTCUSDT / 1w`
  - `BTCUSDT / 1d`
  - `BTCUSDT / 4h`
  - `BTCUSDT / 1h`
  - `ETHUSDT / 1w`
  - `ETHUSDT / 1d`
  - `ETHUSDT / 4h`
  - `ETHUSDT / 1h`
- `1w` 使用已固化周线默认参数：`EMA15 / MA40`、`ADX >= 0`、多头 RSI `35-85`、空头 RSI `0-100`、止损 `1.8 ATR`、动态止盈启动 `7.5 ATR`、阶梯 `1.25 ATR`、上限 `32 ATR`、`volume_mult = 1`。
- `/paper` 顶部“策略周期”改为从 `/api/paper/status` 的已启用策略动态计算，按 `1w / 1d / 4h / 1h` 顺序展示，不再写死。
- 验证：
  - 目标测试红灯确认旧行为缺 `1w` 且页面硬编码。
  - 修改后目标测试通过：`test_paper_defaults_use_shared_1000_usdt_account_and_all_strategy_intervals`、`test_paper_engine_initializes_account_and_strategies_once`、`test_paper_page_derives_strategy_intervals_from_status`。

## 2026-07-04 start.sh 手动后台启动修正

- 用户指出：终端执行 `start.sh` 后不能关闭终端肯定不行；同时再次强调 `start.sh` 必须启动一切。
- 根因：此前 `start.sh` 只有前台 supervisor 行为，适合 systemd 托管，但不适合 SSH 手动执行后关闭终端。
- 修改：
  - `./start.sh` 在 Ubuntu/systemd 环境默认安装/更新并重启 `weekly-web`，该服务执行 `./start.sh --foreground`；非 systemd 环境才用 `nohup` 后台启动同一个 supervisor，写入 `runtime/start.pid`，日志写入 `runtime/logs/start.log`。
  - `./start.sh --foreground` 前台启动同一个 supervisor，供 systemd 托管。
  - `scripts/deploy_one_click.sh` 的 systemd `ExecStart` 已改为 `/usr/bin/env bash ${ROOT_DIR}/start.sh --foreground`。
  - Web 和 Paper runner 仍由根目录 `start.sh` 统一启动、监控和清理，没有恢复独立 `weekly-paper` 服务。
- 手动启动：

```bash
./start.sh
```

- systemd 托管启动：

```bash
sudo systemctl restart weekly-web
```

- 手动停止：

```bash
kill $(cat runtime/start.pid)
```

## 2026-07-04 start.sh 处理旧 systemd 双轨部署

- 用户贴出的服务器日志显示：
  - 手动执行 `bash scripts/start.sh` 启动的是旧前台 Web 进程，监听 `8002`，输出 `停止: Ctrl+C`。
  - `Ctrl+C` 后 `8002` 不再监听。
  - 但 `systemctl status weekly-web` 仍 active，因为旧 `weekly-web` 服务直接运行 `uvicorn app.main:app` 并监听 `8001`。
  - `weekly-paper` 旧独立服务仍 active。
- 根因：服务器还处在旧部署形态，存在三条启动路径：
  - 手动前台 `scripts/start.sh` 临时进程。
  - 旧 `weekly-web` 直接 `uvicorn`。
  - 旧 `weekly-paper` 直接 `app.paper_runner`。
- 修改：
  - 根目录 `start.sh` 默认模式在 systemd 环境下不再起临时 `8002` 进程，而是写入/更新 `weekly-web.service`，`ExecStart=/usr/bin/env bash ${ROOT_DIR}/start.sh --foreground`，然后 `systemctl restart weekly-web`。
  - 根目录 `start.sh` 会停止、禁用并删除旧 `weekly-paper.service`。
  - 根目录 `start.sh` 会先 `systemctl stop weekly-web`，再清理本项目遗留 Python 进程，避免旧 service 自动重启抢占端口。
  - `--foreground` 模式里的 Web 输出已写入 `runtime/logs/web.log`，不再直接把 uvicorn 的 `Press CTRL+C to quit` 打到手动终端。
  - `scripts/deploy_one_click.sh` 复用根目录 `start.sh` 做 systemd 安装和重启，避免两套 unit 写法漂移。
  - 非 systemd 环境保留 `nohup "$0" --foreground` fallback。
- 服务器更新到此版本后，执行：

```bash
./start.sh
```

- 诊断当前 Web 进程实际运行版本：

```bash
curl -s http://127.0.0.1:8001/api/system/runtime
```

- 如果返回里 `paper_html_markers.hardcoded_old_intervals=true`，或页面标题仍是旧 `BTCUSDT / ETHUSDT U本位永续合约模拟交易`，说明当前浏览器访问的 Web 进程不是最新代码。

## 2026-07-04 删除 scripts/start.sh 并增加运行态版本诊断

- 用户已删除 `scripts/start.sh`，要求默认只使用项目根目录 `start.sh`。
- 仓库同步该决定：
  - 删除 `scripts/start.sh`。
  - `scripts/deploy_one_click.sh` 不再 chmod 或引用 `scripts/start.sh`。
  - 测试新增约束：`scripts/start.sh` 不应存在。
- 新增 `/api/system/runtime`：
  - 返回 `pid`、`cwd`、`app_version`、`git_commit`、`start_mode`。
  - 返回 Paper HTML 标记：是否使用动态策略周期、是否使用新标题、是否仍含旧硬编码周期。
- `start.sh` 会把当前 `git rev-parse --short HEAD` 写入 `APP_VERSION`，systemd unit 也会带上该环境变量。
- 用途：以后出现“端口有监听但页面还是旧”的情况，先查 `/api/system/runtime`，确认服务实际运行 commit 和页面标记。

## 2026-07-04 8002 残留旧进程与 Paper 页面旧版本诊断

- 用户重新部署后反馈 `8001` 和 `8002` 都能访问，且 `/paper` 页面仍显示旧标题 `BTCUSDT / ETHUSDT U本位永续合约模拟交易` 和策略周期 `1d / 4h`。
- 本地当前代码结论：
  - `PAPER_HTML` 不再硬编码 `1d / 4h`，而是通过 `id="strategyIntervals"` 从 `/api/paper/status` 返回的启用策略动态计算。
  - `paper_strategy_defaults()` 当前应初始化 8 个策略：`BTCUSDT/ETHUSDT` 各 `1w / 1d / 4h / 1h`。
  - 因此截图中的旧标题和 `1d / 4h` 不是当前代码渲染结果，而是远端仍有旧 Web 进程或旧代码实例在提供页面。
- 本次修正：
  - `start.sh` 的旧进程清理范围从本项目 `.venv` 下的 `uvicorn` / `app.paper_runner` 扩展到本项目根目录 `start.sh` 和旧 `scripts/start.sh` supervisor，避免旧 `8002` shell supervisor 残留。
  - 新增 `scripts/diagnose_runtime.sh`，用于在服务器上同时检查 `8001/8002` 的监听进程、`/api/system/runtime` 返回 commit、以及 `/paper` HTML 是否仍是旧硬编码标题/周期。
- 服务器更新到此版本后建议执行：

```bash
git pull
chmod +x start.sh scripts/diagnose_runtime.sh
./start.sh
./scripts/diagnose_runtime.sh
```

- 预期结果：
  - 只有 `8001` 是本项目服务；如果 `8002` 仍监听，诊断脚本会显示它的 PID 和运行版本。
  - `/api/system/runtime.paper_html_markers.hardcoded_old_intervals=false`。
  - `/api/system/runtime.paper_html_markers.dynamic_strategy_intervals=true`。
  - `/api/paper/status` 的 `strategies` 应包含 8 条策略。

## 2026-07-05 Paper 页面列与时间显示更新

- `/paper` 的 `交易记录` 和 `最近平仓` 表格在 `交易对` 后新增 `周期` 列，直接显示 `1w / 1d / 4h / 1h`。
- `/paper` 的 `当前持仓` 表格在 `数量` 后新增 `金额(USDT)`，使用 `paper_positions.entry_margin` 展示本次开仓使用的 USDT 金额。
- `BTCUSDT` 在 Paper 页面表格中统一显示为蓝色；周期颜色统一为：
  - `1w` 蓝色
  - `1d` 红色
  - `4h` 紫色
  - `1h` 黄色
- 运行日志首列时间改为固定 `YYYY-MM-DD HH:mm:ss` 格式；日志内容 payload 中的 `*_time` 和 `event_time` 字段也会转成标准时间，避免继续显示类似 `783036800000` 的毫秒时间戳。
- 验证：
  - `python3 -m py_compile app/*.py` 通过。
  - `python3 -m unittest discover -s tests -v`：42 个测试通过。

## 2026-07-05 Paper 当前持仓保证金、强平价和动态止盈展示

- 上一节提到的 `当前持仓` 表格 `金额(USDT)` 确认为 `paper_positions.entry_margin`，即当前系统开仓时占用的保证金，因此页面列名改为 `保证金`。
- `当前持仓` 在截图空红框位置新增 `强平价格` 列，位于 `入场价` 后、`数量` 前。
- 当前强平价是简化估算：`LONG = max(0, entry_price - entry_margin / quantity)`，`SHORT = entry_price + entry_margin / quantity`。该字段用于页面运行态提示，尚未引入 Binance 维护保证金、资金费率或真实强平阶梯模型。
- 策略当前使用动态阶梯止盈：`take_atr_step > 0` 且 `take_atr_max > take_atr_start` 时，价格达到初始止盈后会激活保护并更新 `take_price`。
- 页面保留 `保护/止盈` 列显示开仓时的初始止盈价，并在其后新增 `最新止盈`，显示当前动态更新后的 `paper_positions.take_price`。
- `/api/paper/status` 会为持仓补充：
  - `initial_take_price`
  - `latest_take_price`
  - `liquidation_price`
- 验证：
  - `python3 -m py_compile app/*.py` 通过。
  - `python3 -m unittest discover -s tests -v`：43 个测试通过。

## 下一步建议

1. 在页面点击“同步 Binance 数据”确认 2019-09-02 到 2026-06-29 的周线入库。
2. 运行默认回测，确认逐笔交易与收益曲线。
3. 运行参数优化，筛选高收益但最大回撤可接受的组合。
4. 增加样本外验证，避免只针对这一段行情过拟合。
