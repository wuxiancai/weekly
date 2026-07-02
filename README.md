# BTCUSDT 模拟自动交易系统

一个基于 Binance USDⓈ-M Futures BTCUSDT K 线的模拟自动交易与回测优化系统。

## 启动

```bash
bash scripts/start.sh
```

打开：

```text
http://127.0.0.1:8000
```

## 默认策略

- `EMA(15)` 与 `MA(50)` 判断主趋势。
- `ADX` 过滤趋势强度。
- `MACD` 确认动量。
- `RSI` 避免过热追多/过冷追空。
- `Bollinger Band` 过滤极端位置。
- `ATR` 计算止损止盈。
- 支持做多和做空。

## 数据来源

REST K 线使用 Binance 官方 USDⓈ-M Futures `GET /fapi/v1/klines`。

WebSocket 脚本使用 kline stream：`<symbol>@kline_<interval>`。

