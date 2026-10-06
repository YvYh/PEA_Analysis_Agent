from __future__ import annotations

import argparse
import os
import smtplib
import ssl
from dataclasses import replace
import sys
from email.message import EmailMessage
from pathlib import Path

from pea_agent.analysis import analyze_portfolio
from pea_agent.config import load_config
from pea_agent.market_data import fetch_market_data
from pea_agent.news import search_market_news
from pea_agent.portfolio import parse_positions
from pea_agent.report import render_report


def _send_email(report: str) -> None:
    required = ("PEA_SMTP_HOST", "PEA_SMTP_PORT", "PEA_SMTP_USER", "PEA_SMTP_PASSWORD", "PEA_EMAIL_FROM", "PEA_EMAIL_TO")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ValueError("Email delivery requires environment variables: " + ", ".join(missing))
    message = EmailMessage()
    message["Subject"] = "PEA Portfolio Analysis Report"
    message["From"] = os.environ["PEA_EMAIL_FROM"]
    message["To"] = os.environ["PEA_EMAIL_TO"]
    message.set_content(report)
    port = int(os.environ["PEA_SMTP_PORT"])
    context = ssl.create_default_context()
    with smtplib.SMTP(os.environ["PEA_SMTP_HOST"], port, timeout=20) as server:
        server.starttls(context=context)
        server.login(os.environ["PEA_SMTP_USER"], os.environ["PEA_SMTP_PASSWORD"])
        server.send_message(message)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a PEA portfolio analysis report.")
    parser.add_argument("--holdings", type=Path, default=Path("holdings.csv"), help="CSV with symbol,shares,average_cost[,kind,name].")
    parser.add_argument("--config", type=Path, default=Path("pea-agent-config.json"), help="JSON file with budget and risk settings.")
    parser.add_argument("--output", type=Path, help="Optional Markdown report output path.")
    parser.add_argument("--send-email", action="store_true", help="Send the report using PEA_SMTP_* environment variables.")
    parser.add_argument("--search-news", action="store_true", help="Search public web news (requires internet access).")
    parser.add_argument("--instant", action="store_true", help="Use the instant-diagnosis report title.")
    parser.add_argument("--no-base-dca", action="store_true", help="Disable scheduled base DCA while retaining any dip-triggered buys.")
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        positions = parse_positions(args.holdings.read_text(encoding="utf-8-sig"))
        if not positions:
            raise ValueError(f"No holdings found in {args.holdings}.")
        config = load_config(args.config)
        if args.no_base_dca:
            config = replace(config, include_base_dca=False)
        symbols = tuple(dict.fromkeys([position.symbol for position in positions] + list(config.dca_amounts)))
        news = search_market_news(symbols) if args.search_news else ()
        analysis = analyze_portfolio(positions, config, fetch_market_data, news)
        report = render_report(analysis, instant=args.instant)
        print(report)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report, encoding="utf-8")
        if args.send_email:
            _send_email(report)
    except (OSError, ValueError, RuntimeError, smtplib.SMTPException) as error:
        print(f"pea-agent: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
