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

## 本轮验证

- `python3 -m py_compile app/*.py` 通过。
- `python3 -m unittest discover -s tests -v`：2 个测试通过。
- Binance REST 拉取 `2021-11-15` 到 `2026-07-02` 的 `BTCUSDT 1w`：入库 242 根周 K。
- 默认 `EMA15/MA50` 回测：初始 `1000`，最终 `2489.91`，收益率 `148.99%`，最大回撤 `33.15%`，6 笔交易，胜率 `66.67%`。
- 参数搜索当前最高收益组合：`EMA21/MA60`、`ADX>=14`、`SL=3.0 ATR`、`TP=5.5 ATR`、`volume_mult=0.75`，历史收益率 `331.71%`，最大回撤 `29.68%`，5 笔交易。
- 已用浏览器验证页面标题、按钮、图表、指标和逐笔交易展示。

## 启动

```bash
bash scripts/start.sh
```

默认访问：

```text
http://127.0.0.1:8000
```

## 下一步建议

1. 在页面点击“同步 Binance 数据”确认 2021-11-15 到 2026-07-02 的周线入库。
2. 运行默认回测，确认逐笔交易与收益曲线。
3. 运行参数优化，筛选高收益但最大回撤可接受的组合。
4. 增加样本外验证，避免只针对这一段行情过拟合。
