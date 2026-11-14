# sec-reports

Tracks SEC annual reports (10-K, 10-KT, 20-F, 40-F, no amendments) and fiscal years for the tickers in `data.csv`.

- Spec: `docs/superpowers/specs/2026-11-14-sec-annual-reports-design.md`; plan: `docs/superpowers/plans/2026-11-14-sec-annual-reports.md`.
- Code in `src/sec_reports/`; only `edgar_client.py` touches the network.
- Tests: `uv run pytest`. Tests never call SEC; use `tests/fixtures` and `FakeClient` in `tests/conftest.py`.
- Rows with `fy_source = verified` are never modified by code.
- Companies are keyed by CIK; a ticker can map to several CIKs.
