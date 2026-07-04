# BTCUSDT 模拟自动交易系统

一个基于 Binance USDⓈ-M Futures BTCUSDT K 线的模拟自动交易与回测优化系统。

## 启动

```bash
./start.sh
```

`./start.sh` 会统一启动 Web 回测系统和 Paper 模拟交易系统。启动前会先停止本项目已存在的 Web/Paper 进程，避免重复运行。

打开：

```text
http://127.0.0.1:8001
```

## 默认策略

- `EMA(15)` 与 `MA(50)` 判断主趋势。
- `ADX` 过滤趋势强度。
- `MACD` 确认动量。
- `RSI` 避免过热追多/过冷追空。
- `Bollinger Band` 过滤极端位置。
- `ATR` 计算止损止盈。
- 支持做多和做空。
- 回测使用上一根已收盘 K 线生成信号，下一根 K 线开盘成交，避免未来函数。
- 支持 Walk-forward：训练段选参，测试段验证。

## 数据来源

REST K 线使用 Binance 官方 USDⓈ-M Futures `GET /fapi/v1/klines`。

WebSocket 脚本使用 kline stream：`<symbol>@kline_<interval>`。
