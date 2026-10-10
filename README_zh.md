# PEA 投资组合与市场分析助手

面向 BoursoBank PEA 投资者的本地 Python 应用。它将 CSV 持久化的持仓与观察名单、Yahoo Finance 历史行情、可配置风险限制、公开网页搜索结果及用户提供的资讯结合，生成 Markdown 分析报告。应用不会执行交易。

## 启动交互式应用

需要 Python 3.11 或更高版本。

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
streamlit run app.py
```

应用默认在项目目录下维护以下本地文件；可通过 `PEA_AGENT_DATA_DIR` 环境变量指定其他本地数据目录：

- `holdings.csv`：在“持仓管理”中新增持仓、修改股数或均价、删除持仓。
- `watchlist.csv`：在“Watch list 管理”中添加或删除标的。所有列表标的都会纳入分析。
- `pea-agent-cash.csv`：保存手动填写的可用现金。

持仓 CSV 列为 `symbol,shares,average_cost,kind,name`；观察名单列为 `symbol,kind,name`。保存时应用会创建或更新对应 CSV。请勿在应用写入时同时手动编辑这些文件。常见代码别名会自动标准化（例如 `CW8` 转为 `CW8.PA`、`MC` 转为 `MC.PA`）；未知代码如未填写类型，则默认为卫星仓。

可粘贴文章文本或公开的 HTTP(S) 网页链接。网页抓取仅允许公共主机，每个响应大小上限为 2 MB。可选联网搜索通过 `ddgs` 使用 DuckDuckGo；搜索结果和文章文本仅供核验，不是权威建议。Yahoo Finance 和网页搜索需要互联网连接。

## 分析规则

- 侧边栏显示可用现金、持仓证券估值（“Evaluation titre”）和当前总资产（“Total value actuelle”）。证券估值按最新可获取行情乘以持仓股数计算；当前总资产为证券估值加手动填写的现金。若行情获取失败，报告会指出，估值可能不完整。
- Watch list 标的在满足以下任一条件时成为买入候选：较近 63 个交易日高点回撤至少 8%；或价格低于 MA20 且 RSI 低于 45。阈值可在侧边栏调整。
- 多个候选标的按触发信号数量的比例分配可用现金。买入股数按整股向下取整，买入总额不超过可用现金。分配后剩余现金会按信号强度优先用于仍能买入的候选标的。
- 用户提供的资讯若含风险关键词，会暂停相关标的的新增买入建议，等待人工核实。关键词本身不会自动触发卖出。
- **卫星仓止损：** 相对于录入持仓均价亏损达到或超过 15% 时建议清仓。
- **卫星仓集中度：** 个股占总资产（持仓加现金）超过 15% 时，建议卖出部分股数，将占比再平衡至约 10%。
- **阶段性止盈：** RSI 达到 70，或价格高于 MA200 至少 20% 时，建议卖出约 25% 持仓（按整股计算）。
- **周线防守退出：** 卫星仓连续两个已完成周线收盘价低于 200 周均线时建议清仓。
- **明确清仓条件：** 可在 JSON 配置中填写 `removed_from_cac40` 或 `fundamental_exit_symbols`，分别表示用户确认的 CAC 40 成分剔除或重大基本面恶化。

已移除定投、每月买入上限和本月已买入额度统计。可用现金是观察名单买入建议的唯一金额上限。行情缺失或获取失败时会明确报告；应用不会用虚构价格填补缺失数据，也不会据此生成买卖建议。

## 定时报告与邮件

CLI 可由 Windows 任务计划程序、cron 或其他调度器运行。请在运行目录准备 `holdings.csv`、`watchlist.csv` 和 `pea-agent-cash.csv`；复制 `pea-agent-config.example.json` 为 `pea-agent-config.json`，即可为 CLI 自定义可用现金及风险阈值。

```powershell
pea-agent --holdings holdings.csv --watchlist watchlist.csv --config pea-agent-config.json --output reports\weekly.md --search-news --send-email
```

通过环境变量配置邮件服务。请使用应用专用密码或 SMTP 凭证，不要将密钥写入 JSON：

```text
PEA_SMTP_HOST, PEA_SMTP_PORT, PEA_SMTP_USER, PEA_SMTP_PASSWORD
PEA_EMAIL_FROM, PEA_EMAIL_TO
```

所需输入、行情数据或邮件发送失败时，CLI 会以错误退出。配置示例：

```json
{
  "cash_available": 250,
  "dip_drawdown_pct": 8,
  "dip_rsi_threshold": 45,
  "satellite_stop_loss_pct": 15,
  "max_satellite_weight_pct": 15,
  "target_satellite_weight_pct": 10,
  "take_profit_rsi": 70,
  "take_profit_ma200_premium_pct": 20,
  "take_profit_fraction": 0.25,
  "removed_from_cac40": [],
  "fundamental_exit_symbols": []
}
```

## 测试

```powershell
python -m pytest
```

本工具提供基于规则的量化分析，不构成个性化投资建议。投资前请核实 PEA 合规性、行情、费用、税务影响和资讯。
