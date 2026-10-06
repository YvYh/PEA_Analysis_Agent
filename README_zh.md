# PEA 投资组合与市场分析助手

面向 BoursoBank PEA 投资者的本地 Python 应用。它将手动录入的持仓、Yahoo Finance 历史行情、可配置的风险限制、公开网页搜索结果及用户提供的资讯整合为 Markdown 操作报告。应用不会执行交易。

## 启动交互式应用

需要 Python 3.11 或更高版本。

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
streamlit run app.py
```

仪表板接受 CSV 格式的持仓数据，必需列为 `symbol,shares,average_cost`。`kind`（`core` 或 `satellite`）和 `name` 为可选列。常见代码别名会自动标准化（例如 `CW8` 转为 `CW8.PA`，`MC` 转为 `MC.PA`）；除非显式指定类型，否则未知代码会被视为卫星仓。定投目标按每行一个 `ticker,amount` 填写。建议买入股数按整股向下取整。

可以粘贴文章内容，或提供公开的 HTTP(S) 文章链接。链接抓取仅允许访问公共主机，每个响应大小上限为 2 MB。可选的联网搜索通过 `ddgs` 使用 DuckDuckGo；搜索结果和文章文本仅供核验，不应视为权威建议。Yahoo Finance 和网页搜索都需要互联网连接。

## 规则与默认值

- **每月买入上限：** 默认 €500，并扣除用户填写的本月已执行买入金额，以及此前已推荐且仍计划执行的买入金额。整股买入建议不会超过剩余额度。
- **基础定投：** 可按标的配置，并可在本次报告中选择是否包含。
- **动态抄底：** 标的较近 63 个交易日高点回撤 8%，或价格低于 MA20 且 RSI 低于 45 时，在该标的定投金额上追加 50%。
- **卫星仓止损：** 相对于录入的持仓均价亏损达到或超过 15% 时建议清仓。
- **卫星仓集中度：** 当个股占总资产（持仓加现金）超过 15% 时，建议卖出相应股数，将占比再平衡至 10% 左右。
- **阶段性止盈：** RSI 达到 70，或价格高于 MA200 至少 20% 时，建议卖出约 25% 的持仓（按整股计算）。
- **周线防守退出：** 卫星仓连续两周收盘价低于 200 周均线时建议清仓。
- **明确的清仓条件：** 可在配置中填写 `removed_from_cac40` 或 `fundamental_exit_symbols`，分别表示用户已确认的 CAC 40 成分剔除或重大基本面恶化。新闻关键词匹配只会产生人工核验提示，不会自动触发清仓。

这些阈值可在仪表板或 JSON 配置中调整。行情数据缺失或获取失败时，应用会明确报告；不会用虚构行情补值，也不会据此生成交易指令。持仓占比计算会纳入证券和用户填写的现金余额；现金仅用于资产占比参考，不会成为额外的买入预算限制。

## 定时报告与邮件

CLI 可由 Windows 任务计划程序、cron 或其他调度器运行。创建 `holdings.csv`，并将 `pea-agent-config.example.json` 复制为 `pea-agent-config.json`，然后填写自己的持仓、定投金额、现金和预算。每次运行前，请更新 `month_to_date_buys`，计入已执行买入以及此前仍计划执行的建议，避免后续报告重复占用同一笔预算。应用不会假装拥有读取银行账户的权限。

```powershell
pea-agent --holdings holdings.csv --config pea-agent-config.json --output reports\weekly.md --search-news --send-email
```

可将上述命令安排在周日晚间运行。周三复核时，建议关闭本次基础定投，避免一周内重复提出相同的定投建议：

```powershell
pea-agent --holdings holdings.csv --config pea-agent-config.json --output reports\midweek.md --search-news --send-email --instant --no-base-dca
```

通过环境变量配置邮件服务（请使用应用专用密码或 SMTP 凭证，不要将密钥写入 JSON 文件）：

```text
PEA_SMTP_HOST, PEA_SMTP_PORT, PEA_SMTP_USER, PEA_SMTP_PASSWORD
PEA_EMAIL_FROM, PEA_EMAIL_TO
```

如果所需输入、行情数据或邮件发送失败，CLI 会以错误退出。请在调度器中分别设置周日和周三任务；周三的 24 小时复核使用 `--instant` 和 `--no-base-dca`。JSON 配置示例：

```json
{
  "monthly_budget_cap": 500,
  "month_to_date_buys": 0,
  "cash_available": 250,
  "include_base_dca": true,
  "dca_amounts": {"CW8": 200, "ESE": 100},
  "dip_drawdown_pct": 8,
  "dip_rsi_threshold": 45,
  "dip_additional_multiplier": 0.5,
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

本工具提供基于规则的量化分析，不构成个性化投资建议。请在投资前核实 PEA 合规性、行情、费用、税务影响和资讯。
