# Stock Screener with Fundamental Ratios for Equity Research

A Python system that pulls company fundamentals from Yahoo Finance, computes
key ratios, and filters/ranks companies against criteria you define.

## Ratios calculated
| Ratio | Formula |
|---|---|
| P/E | Price / EPS |
| P/B | Price / Book Value per Share |
| ROE | Net Income / Shareholders' Equity |
| ROCE | EBIT / (Total Assets − Current Liabilities) |
| D/E | Total Debt / Shareholders' Equity |
| EPS | Net Income / Shares Outstanding |
| Profit Margin | Net Income / Revenue |

## Setup
```bash
pip install -r requirements.txt
```

## Usage

**Quick screen with inline flags:**
```bash
python stock_screener.py --tickers AAPL MSFT GOOGL AMZN --min-roe 15 --max-pe 30 --max-de 1.0
```

**Using a ticker file + a JSON criteria config (recommended for repeatable screens):**
```bash
python stock_screener.py --tickers-file tickers.txt --config config.json --rank-by roce --output results.csv
```

**Command-line options:**
- `--tickers TICK1 TICK2 ...` or `--tickers-file path.txt`
- `--config config.json` — declarative filter thresholds (see `config.json`)
- `--min-pe / --max-pe`, `--min-pb / --max-pb`, `--min-roe`, `--min-roce`,
  `--max-de`, `--min-eps`, `--min-profit-margin` — override/extend the config
- `--rank-by {pe,pb,roe,roce,de,eps,profit_margin,market_cap}` — sort key (default: roe)
- `--output results.csv` or `results.xlsx` — save the screened list

## Extending it
- **Different data source**: swap `StockDataFetcher.fetch()` for a call to
  another provider (Alpha Vantage, Financial Modeling Prep, a broker API);
  the rest of the pipeline (ratios, filters, ranking) is source-agnostic.
- **More ratios**: add fields in `StockDataFetcher.fetch()` and, if the
  provider doesn't supply them directly, compute them in `RatioCalculator`.
- **Web UI**: `StockScreener.screen(tickers, ...)` returns a pandas
  DataFrame, so it drops straight into a Streamlit or Flask front end.

## Notes
- Yahoo Finance data can lag or omit fields for some companies; rows with
  missing values are excluded by any filter that references that field
  rather than crashing the run.
- Run `python stock_screener.py --help` for the full CLI reference.
