# PEA Portfolio & Market Analytics Agent

A local Python application for BoursoBank PEA investors. It combines manually entered holdings, Yahoo Finance price history, configurable risk limits, public web-search results, and user-supplied news into a Markdown action report. It does not place trades.

## Start the interactive app

Requires Python 3.11 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
streamlit run app.py
```

The dashboard accepts holdings as CSV with `symbol,shares,average_cost` columns. `kind` (`core` or `satellite`) and `name` are optional. Familiar aliases are normalized (`CW8` to `CW8.PA`, `MC` to `MC.PA`); unknown tickers are treated as satellite assets unless their kind is specified. DCA targets are one `ticker,amount` pair per line. Whole-share purchase quantities are rounded down.

Paste article text or supply public HTTP(S) article URLs. URL retrieval is limited to public hosts and 2 MB per response. Optional web search uses DuckDuckGo via `ddgs`; search results and article text are evidence to verify, not authoritative recommendations. Yahoo Finance and web search require an internet connection.

## Rules and defaults

- Monthly purchase cap: €500, reduced by the user's entered month-to-date executed or previously recommended/committed buys. Every recommended whole-share buy is capped to the remaining budget.
- Base DCA: configured per symbol; toggle whether to include it for this report.
- Dynamic dip: add 50% of that symbol's DCA amount after an 8% drawdown from the recent 63-session high, or when price is below MA20 and RSI is below 45.
- Satellite stop-loss: liquidate at a loss of 15% or more against entered average cost.
- Satellite concentration: above 15% of portfolio assets (positions plus cash), suggest enough shares to rebalance toward 10%.
- Staged profit-taking: sell about 25% (whole shares) when RSI is at least 70 or price is at least 20% above MA200.
- Defensive weekly exit: liquidate a satellite after two consecutive weekly closes below its 200-week moving average.
- Explicit exits: configure `removed_from_cac40` or `fundamental_exit_symbols` for user-confirmed CAC 40 removals or material fundamental deterioration. News keyword matches are warnings for human review, not automatic exit triggers.

These thresholds are editable in the dashboard or JSON config. Missing or failed price feeds are reported explicitly; missing quotes do not result in synthetic prices or trade instructions. Holdings percentages include both securities and the cash balance entered by the user; the cash amount is informational and is not an additional buy-budget limit.

## Scheduled reports and email

The CLI can be run from Windows Task Scheduler, cron, or another scheduler. Create a `holdings.csv` file and copy `pea-agent-config.example.json` to `pea-agent-config.json`, then update it with your own holdings, DCA amounts, cash and budget values. Before each run, update `month_to_date_buys` with executed buys plus prior recommendations you still intend to act on; this prevents later reports from recommending the same budget again. The app intentionally does not pretend to have read access to your bank account.

```powershell
pea-agent --holdings holdings.csv --config pea-agent-config.json --output reports\weekly.md --search-news --send-email
```

Schedule that command for Sunday evening. For Wednesday's review, disable the scheduled base DCA so it is not suggested a second time in the same week:

```powershell
pea-agent --holdings holdings.csv --config pea-agent-config.json --output reports\midweek.md --search-news --send-email --instant --no-base-dca
```

Configure email via environment variables (use an app password or SMTP credential; do not put secrets in the JSON file):

```text
PEA_SMTP_HOST, PEA_SMTP_PORT, PEA_SMTP_USER, PEA_SMTP_PASSWORD
PEA_EMAIL_FROM, PEA_EMAIL_TO
```

The CLI exits with an error when a requested input, market feed, or email delivery fails. Set up weekly Sunday and Wednesday runs in your scheduler; use `--instant` and `--no-base-dca` for Wednesday's 24-hour review. Example config:

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

## Tests

```powershell
python -m pytest
```

This tool provides rule-based quantitative analysis, not personalized financial advice. Review eligibility, quotes, fees, taxes, and news before making an investment decision.
