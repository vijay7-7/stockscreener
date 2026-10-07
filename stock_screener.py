"""
Stock Screener with Fundamental Ratios for Equity Research
=============================================================

A Python-based system that collects fundamental financial data for a list
of companies, computes key valuation/performance ratios, and filters
("screens") the universe according to user-defined criteria.

Ratios computed
----------------
- P/E   : Price to Earnings ratio
- P/B   : Price to Book ratio
- ROE   : Return on Equity            = Net Income / Shareholders' Equity
- ROCE  : Return on Capital Employed  = EBIT / (Total Assets - Current Liabilities)
- D/E   : Debt to Equity ratio        = Total Debt / Shareholders' Equity
- EPS   : Earnings Per Share
- Profit Margin (Net Margin)          = Net Income / Revenue

Data source
-----------
Yahoo Finance, via the `yfinance` package (free, no API key required).
Because data providers occasionally omit fields for a given company,
every ratio is computed defensively (falls back to None if inputs are
missing) rather than crashing the whole run.

Usage
-----
    python stock_screener.py --tickers AAPL MSFT GOOGL --config config.json

    python stock_screener.py --tickers-file tickers.txt --min-roe 15 \
        --max-pe 25 --max-de 1.0 --output results.csv

See README.md for the full command-line reference and config.json for
an example of declarative screening criteria.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print(
        "ERROR: the 'yfinance' package is required.\n"
        "Install it with:  pip install yfinance",
        file=sys.stderr,
    )
    raise


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------

@dataclass
class ScreeningCriteria:
    """User-defined thresholds. A None value means 'no constraint'."""
    min_pe: Optional[float] = None
    max_pe: Optional[float] = None
    min_pb: Optional[float] = None
    max_pb: Optional[float] = None
    min_roe: Optional[float] = None        # in %
    max_roe: Optional[float] = None
    min_roce: Optional[float] = None       # in %
    max_roce: Optional[float] = None
    min_de: Optional[float] = None
    max_de: Optional[float] = None
    min_eps: Optional[float] = None
    min_profit_margin: Optional[float] = None  # in %
    sectors: Optional[list] = field(default=None)  # e.g. ["Technology", "Healthcare"]

    @classmethod
    def from_json(cls, path: str) -> "ScreeningCriteria":
        with open(path, "r") as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# --------------------------------------------------------------------------
# Data collection
# --------------------------------------------------------------------------

class StockDataFetcher:
    """Pulls raw fundamentals for one ticker at a time from Yahoo Finance."""

    def fetch(self, ticker: str) -> dict:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # ROCE needs EBIT and Capital Employed, which aren't given directly
        # by `info`, so pull them from the financial statements.
        ebit, capital_employed = self._get_roce_inputs(t)

        return {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "pe": info.get("trailingPE"),
            "pb": info.get("priceToBook"),
            "roe": self._to_pct(info.get("returnOnEquity")),
            "de": self._normalize_de(info.get("debtToEquity")),
            "eps": info.get("trailingEps"),
            "profit_margin": self._to_pct(info.get("profitMargins")),
            "market_cap": info.get("marketCap"),
            "ebit": ebit,
            "capital_employed": capital_employed,
        }

    @staticmethod
    def _to_pct(value):
        """yfinance often returns ratios (0.15) rather than percents (15)."""
        if value is None:
            return None
        return round(value * 100, 2) if abs(value) < 5 else round(value, 2)

    @staticmethod
    def _normalize_de(value):
        """yfinance reports debtToEquity already as a percent-like number
        (e.g. 45.2 meaning 0.452 debt per 1 equity in some cases, or as a
        ratio in others depending on the source snapshot). We normalize to
        a plain ratio (Debt / Equity)."""
        if value is None:
            return None
        # Heuristic: values > 10 are almost always already *100 form.
        return round(value / 100, 2) if value > 10 else round(value, 2)

    @staticmethod
    def _get_roce_inputs(t: "yf.Ticker"):
        ebit = None
        capital_employed = None
        try:
            fin = t.financials
            if fin is not None and not fin.empty:
                for row_name in ("EBIT", "Ebit", "Operating Income"):
                    if row_name in fin.index:
                        ebit = float(fin.loc[row_name].iloc[0])
                        break
        except Exception:
            pass

        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty:
                total_assets = None
                current_liab = None
                for row_name in ("Total Assets",):
                    if row_name in bs.index:
                        total_assets = float(bs.loc[row_name].iloc[0])
                for row_name in ("Current Liabilities", "Total Current Liabilities"):
                    if row_name in bs.index:
                        current_liab = float(bs.loc[row_name].iloc[0])
                if total_assets is not None and current_liab is not None:
                    capital_employed = total_assets - current_liab
        except Exception:
            pass

        return ebit, capital_employed


# --------------------------------------------------------------------------
# Ratio calculation
# --------------------------------------------------------------------------

class RatioCalculator:
    """Fills in any ratios not already supplied directly by the data source
    (currently: ROCE, which we derive ourselves)."""

    @staticmethod
    def compute(row: dict) -> dict:
        row = dict(row)  # copy
        ebit = row.get("ebit")
        cap_employed = row.get("capital_employed")
        if ebit is not None and cap_employed not in (None, 0):
            row["roce"] = round((ebit / cap_employed) * 100, 2)
        else:
            row["roce"] = None
        return row


# --------------------------------------------------------------------------
# Screening engine
# --------------------------------------------------------------------------

class StockScreener:
    COLUMNS = [
        "ticker", "name", "sector", "price", "pe", "pb",
        "roe", "roce", "de", "eps", "profit_margin", "market_cap",
    ]

    def __init__(self, criteria: Optional[ScreeningCriteria] = None):
        self.criteria = criteria or ScreeningCriteria()
        self.fetcher = StockDataFetcher()

    def build_dataset(self, tickers: list[str], verbose: bool = True) -> pd.DataFrame:
        rows = []
        for i, ticker in enumerate(tickers, 1):
            if verbose:
                print(f"[{i}/{len(tickers)}] Fetching {ticker} ...")
            try:
                raw = self.fetcher.fetch(ticker)
                enriched = RatioCalculator.compute(raw)
                rows.append(enriched)
            except Exception as e:
                print(f"  WARNING: failed to fetch {ticker}: {e}", file=sys.stderr)
        df = pd.DataFrame(rows)
        return df[self.COLUMNS] if not df.empty else df

    def apply_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        c = self.criteria
        mask = pd.Series(True, index=df.index)

        def bound(col, lo, hi):
            nonlocal mask
            if lo is not None:
                mask &= df[col].notna() & (df[col] >= lo)
            if hi is not None:
                mask &= df[col].notna() & (df[col] <= hi)

        bound("pe", c.min_pe, c.max_pe)
        bound("pb", c.min_pb, c.max_pb)
        bound("roe", c.min_roe, c.max_roe)
        bound("roce", c.min_roce, c.max_roce)
        bound("de", c.min_de, c.max_de)
        if c.min_eps is not None:
            mask &= df["eps"].notna() & (df["eps"] >= c.min_eps)
        if c.min_profit_margin is not None:
            mask &= df["profit_margin"].notna() & (df["profit_margin"] >= c.min_profit_margin)
        if c.sectors:
            mask &= df["sector"].isin(c.sectors)

        return df[mask].reset_index(drop=True)

    def rank(self, df: pd.DataFrame, by: str = "roe", ascending: bool = False) -> pd.DataFrame:
        if by not in df.columns:
            raise ValueError(f"Cannot rank by unknown column '{by}'")
        return df.sort_values(by=by, ascending=ascending, na_position="last").reset_index(drop=True)

    def screen(self, tickers: list[str], rank_by: str = "roe", verbose: bool = True) -> pd.DataFrame:
        df = self.build_dataset(tickers, verbose=verbose)
        if df.empty:
            return df
        filtered = self.apply_filters(df)
        return self.rank(filtered, by=rank_by)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Fundamental-ratio stock screener")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--tickers", nargs="+", help="Space-separated list of tickers")
    src.add_argument("--tickers-file", help="Text file with one ticker per line")

    p.add_argument("--config", help="JSON file with screening criteria")
    p.add_argument("--min-pe", type=float)
    p.add_argument("--max-pe", type=float)
    p.add_argument("--min-pb", type=float)
    p.add_argument("--max-pb", type=float)
    p.add_argument("--min-roe", type=float)
    p.add_argument("--min-roce", type=float)
    p.add_argument("--max-de", type=float)
    p.add_argument("--min-eps", type=float)
    p.add_argument("--min-profit-margin", type=float)

    p.add_argument("--rank-by", default="roe", choices=[
        "pe", "pb", "roe", "roce", "de", "eps", "profit_margin", "market_cap",
    ])
    p.add_argument("--output", help="Path to save results (.csv or .xlsx)")
    return p.parse_args()


def load_tickers(args) -> list[str]:
    if args.tickers:
        return [t.upper() for t in args.tickers]
    with open(args.tickers_file) as f:
        return [line.strip().upper() for line in f if line.strip()]


def build_criteria(args) -> ScreeningCriteria:
    if args.config:
        criteria = ScreeningCriteria.from_json(args.config)
    else:
        criteria = ScreeningCriteria()
    # CLI flags override / fill in config values when provided
    for attr in ("min_pe", "max_pe", "min_pb", "max_pb", "min_roe",
                 "min_roce", "max_de", "min_eps", "min_profit_margin"):
        cli_val = getattr(args, attr, None)
        if cli_val is not None:
            setattr(criteria, attr, cli_val)
    return criteria


def main():
    args = parse_args()
    tickers = load_tickers(args)
    criteria = build_criteria(args)

    screener = StockScreener(criteria)
    results = screener.screen(tickers, rank_by=args.rank_by)

    if results.empty:
        print("\nNo companies matched the given criteria (or data could not be fetched).")
        return

    pd.set_option("display.width", 140)
    pd.set_option("display.max_columns", None)
    print(f"\n{len(results)} companies matched:\n")
    print(results.to_string(index=False))

    if args.output:
        if args.output.endswith(".xlsx"):
            results.to_excel(args.output, index=False)
        else:
            results.to_csv(args.output, index=False)
        print(f"\nSaved results to {args.output}")


if __name__ == "__main__":
    main()
