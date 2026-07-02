# 项目约束

- 默认使用中文沟通。
- 长期上下文写入仓库文档，不依赖当前会话。
- 修改完成或中断前维护 `docs/HANDOFF.md`。
- Web 服务启动脚本必须监听 `0.0.0.0`，使用虚拟环境；部署脚本提供 systemd 安装入口。
- 每次修改都使用 git 进行版本控制。

## Agent skills

本项目是币安 BTCUSDT 永续合约模拟自动交易系统，默认读取以下文档后再开发：

- `docs/PROJECT_CONTEXT.md`
- `docs/TASKS.md`
- `docs/DECISIONS.md`
- `docs/HANDOFF.md`

