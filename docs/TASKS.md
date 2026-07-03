# 任务清单

- [x] 初始化项目文档和 git 仓库。
- [x] 建立 SQLite 数据表。
- [x] 实现 Binance K 线 REST 拉取与入库。
- [x] 实现技术指标计算。
- [x] 实现 EMA/MA 趋势 + 专业指标过滤策略。
- [x] 实现多空回测、止盈止损、逐笔交易记录。
- [x] 实现参数搜索与优化结果持久化。
- [x] 实现 Web 页面和 API。
- [x] 提供虚拟环境启动脚本。
- [x] 提供 systemd 部署脚本。
- [ ] 接入长期运行的 WebSocket 守护进程并做页面实时状态增强。
- [x] 增加 Walk-forward / 样本外验证，降低过拟合风险。
- [x] 回测执行改为上一根已收盘 K 线出信号、下一根 K 线开盘成交，规避未来函数。
- [x] 新增根目录 `start.sh`，自适应 macOS/Ubuntu 一键启动。
- [x] 建立 BTCUSDT / ETHUSDT `1d/4h` 实盘模拟运行态，默认共享 `1000 USDT` 模拟账户。
- [x] 新增 `/paper` 模拟交易状态页和 `/api/paper/status`。
- [x] 新增 `scripts/deploy_one_click.sh` 一键部署脚本，安装 Web 与 Paper runner 两个 systemd 服务。
- [ ] 增加资金费率、强平价、杠杆保证金模型。
