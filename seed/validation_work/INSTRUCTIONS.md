# Validation task (one ticker)

Input: `seed/validation_work/{T}_rows.csv` (accession_no, ticker, cik, form, filing_date, period_of_report, fiscal_year, fy_source, doc_url).
Output: `seed/validation_work/{T}_validation.csv` with header
`accession_no,fiscal_year,period_of_report,status,evidence` - exactly one line per input row.

For each filing, read its primary document (doc_url) cover page and decide:
- `period_of_report`: the fiscal year end date stated on the cover ("For the fiscal year ended ...") as YYYY-MM-DD.
- `fiscal_year`: the company's own label for that year. If the document names it (e.g. Walmart "fiscal 2014" for the year ended January 31, 2014), use that. Otherwise use the calendar year of the fiscal year end date.
- `status`: `confirmed` if both match the input row, else `corrected`.
- `evidence`: short verbatim quote(s) from the document that justify the values (max ~200 chars, no commas -> replace commas with semicolons, or quote the field properly).

Fetching (SEC rules - mandatory):
- Download ALL documents in ONE curl command, sequentially, rate-limited:
  `curl -sS --rate 2/s -H "User-Agent: Terrence Stella terrence.s.stella@gmail.com" -o <file1> <url1> -o <file2> <url2> ...`
  into `$SCRATCH/val/{T}/` (one file per accession).
- No retries in loops. If a few files fail, re-fetch only those once in a single curl call. Never fetch anything other than the doc_url files.
- Then inspect locally (grep -i -m3 -o ".\{0,150\}fiscal year ended.\{0,80\}" etc., strip HTML as needed with python -I).

Do not modify any other file. Do not commit. Report: counts confirmed/corrected and each correction with evidence.
