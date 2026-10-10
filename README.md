# PEA Portfolio & Market Analytics Agent

A local Python application for BoursoBank PEA investors. It combines CSV-backed holdings and watchlists with Yahoo Finance price history, configurable risk limits, public web-search results, and user-provided news. It generates a Markdown action report and does not place trades.

## Start the interactive app

Requires Python 3.11 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
streamlit run app.py
```

The app maintains these files in the project folder by default (`PEA_AGENT_DATA_DIR` can point to another local folder):

- `holdings.csv`: add a new position, edit its share count or average cost, and delete positions from the holdings tab.
- `watchlist.csv`: add or remove symbols in the watchlist tab. Every listed symbol is included in analysis.
- `pea-agent-cash.csv`: the manually entered available cash value.

Holdings columns: `symbol,shares,average_cost,kind,name`. Watchlist columns: `symbol,kind,name`. The app creates/updates the CSV files when you save changes; do not edit these files while the app is writing them. Familiar aliases are normalized (`CW8` to `CW8.PA`, `MC` to `MC.PA`). Unknown tickers default to satellite assets unless their kind is explicitly set.

Paste article text or supply public HTTP(S) article URLs. URL retrieval is limited to public hosts and 2 MB per response. Optional web search uses DuckDuckGo via `ddgs`; search results and article text are evidence to verify, not authoritative recommendations. Yahoo Finance and web search require an internet connection.

## Analysis rules

- The sidebar displays available cash, estimated security valuation (“Evaluation titre”), and current total assets (“Total value actuelle”). Security valuation is the sum of current quoted prices times held shares; total value is securities plus manually entered cash. A failed quote is reported and can make the displayed estimate incomplete.
- Watchlist buy candidates are triggered by either a drawdown of at least 8% from the recent 63-session high or price below MA20 with RSI below 45. The thresholds can be changed in the sidebar.
- When multiple watchlist candidates qualify, available cash is allocated in proportion to the number of triggered signals. Orders are rounded down to whole shares and cannot exceed available cash. Any leftover cash is offered one share at a time to the highest-signal candidate that remains affordable.
- User-supplied news risk keywords suppress new watchlist buys for related symbols, pending human review. A risk keyword alone never triggers a sale.
- Satellite stop-loss: liquidate at a loss of 15% or more against entered average cost.
- Satellite concentration: above 15% of total assets (positions plus cash), suggest enough shares to rebalance toward 10%.
- Staged profit-taking: sell about 25% (whole shares) when RSI is at least 70 or price is at least 20% above MA200.
- Defensive weekly exit: liquidate a satellite after two consecutive completed weekly closes below its 200-week moving average.
- Explicit exits: set `removed_from_cac40` or `fundamental_exit_symbols` in the JSON config for user-confirmed CAC 40 removals or material fundamental deterioration.

There is no DCA schedule, monthly buy cap, or month-to-date purchase counter. The entered available cash is the sole upper limit for watchlist buy recommendations. Missing or failed price feeds are reported; missing quotes do not result in synthetic prices or trade instructions.

## Scheduled reports and email

The CLI can be run from Windows Task Scheduler, cron, or another scheduler. Keep `holdings.csv`, `watchlist.csv`, and `pea-agent-cash.csv` in the working folder, and copy `pea-agent-config.example.json` to `pea-agent-config.json` to customize cash and risk thresholds for CLI runs.

```powershell
pea-agent --holdings holdings.csv --watchlist watchlist.csv --config pea-agent-config.json --output reports\weekly.md --search-news --send-email
```

Configure email via environment variables (use an app password or SMTP credential; do not put secrets in the JSON file):

```text
PEA_SMTP_HOST, PEA_SMTP_PORT, PEA_SMTP_USER, PEA_SMTP_PASSWORD
PEA_EMAIL_FROM, PEA_EMAIL_TO
```

The CLI exits with an error when requested input, market data, or email delivery fails. Example config:

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

## Tests

```powershell
python -m pytest
```

This tool provides rule-based quantitative analysis, not personalized financial advice. Review eligibility, quotes, fees, taxes, and news before making an investment decision.
