# Backfill validation (2026-11-14)

All 110 annual reports (filed 2006-11-14 onwards) checked against each filing's own cover page by one agent per ticker. Result: every row `fy_source = verified`; evidence quote per row in `seed/validation.csv` and the `note` column.

| ticker | rows | confirmed | corrected |
|---|---|---|---|
| AAPL | 21 | 21 | 0 |
| JPM | 20 | 20 | 0 |
| XOM | 20 | 20 | 0 |
| SAP | 20 | 20 | 0 |
| WMT | 20 | 19 | 1 |
| CVNA | 9 | 9 | 0 |

## Corrections
- WMT `0000104169-09-000006`: EDGAR `reportDate` 2009-04-01 (the filing date) -> period 2009-01-31, fiscal year 2009. Evidence: "for the fiscal year ended January 31, 2009", "63.7% of our fiscal 2009 net sales".

## Findings that shaped the code
- WMT's own XBRL `fiscal_year` is one year too low for filings 2010-2014 (e.g. year ended Jan 31 2014 tagged 2013). Walmart's documents call that year "fiscal 2014". The job trusts XBRL only when it fits the company's majority pattern; the documents confirm this rule.
- XOM's ticker now maps to ExxonMobil Holdings Corp (CIK 2115436, no annual reports yet). History lives under Exxon Mobil Corp (CIK 34088). Both CIKs are tracked.
- Inferred years (pre-XBRL: US companies FY2006-2008, SAP FY2006-2016) were all confirmed.

## Method
- Agents downloaded each primary document once (single rate-limited curl, declared User-Agent), read the cover page, and wrote `seed/validation_work/{T}_validation.csv`.
- Independent spot check: cover dates parsed by script for 89 filings matched; the remaining inline-XBRL filings were confirmed via their embedded DEI header (fiscal year focus, period end).
- Applied with `scripts/apply_validation.py`, which fails unless every row ends up verified.
