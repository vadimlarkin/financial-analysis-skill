# Running the tools

Run commands in a separate working directory, using the absolute path to the installed skill as `SKILL_DIR`. Replace file names with those in the current case. Use an interpreter with Python 3.11 or newer. Calculations use the standard library. PDF rendering and PDF text extraction use `reportlab` and `pypdf`.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r "$SKILL_DIR/scripts/requirements.txt"
```

In hosted environments check which packages are already present. If PDF tools are unavailable and cannot be installed, give the report as an editable Markdown file or text and state the missing PDF step. Leave working files outside the skill folder.

| Task | Command from the working directory |
| --- | --- |
| Extract PDF text by page | `python "$SKILL_DIR/scripts/extract_pdf_cached.py" statement.pdf --cache-dir pdf-cache --language eng --output statement-text.json` |
| Calculate accounting ratios | `python "$SKILL_DIR/scripts/analyze.py" accounting.json accounting-result.json` |
| Import a CSV statement | `python "$SKILL_DIR/scripts/import_statement_csv.py" statement.csv import-profile.json imported.json` |
| Reconcile overlapping exports | `python "$SKILL_DIR/scripts/reconcile_statement_overlaps.py" overlap.json overlap-result.json` |
| Match internal transfers | `python "$SKILL_DIR/scripts/match_own_transfers.py" transfers.json transfer-result.json` |
| Calculate bank flow | `python "$SKILL_DIR/scripts/calculate_cashflow.py" bank.json bank-result.json` |
| Summarize debt | `python "$SKILL_DIR/scripts/summarize_debt_register.py" debt.json debt-result.json` |
| Calculate a loan schedule | `python "$SKILL_DIR/scripts/calculate_loan_schedule.py" loan.json loan-result.json` |
| Calculate cash position | `python "$SKILL_DIR/scripts/analyze_cash_position.py" cash-position.json cash-position-result.json` |
| Generate PDF | `python "$SKILL_DIR/scripts/render_report.py" report.json financial-report.pdf` |

Use a fresh output file on each iteration. Check each exit status and read issues and limitations from the outputs. An error report can contain useful diagnostics but cannot substantiate a total. For OCR install Poppler (`pdftoppm`) and Tesseract with the document language, or use Apple Vision on macOS. Use `--language rus+eng` for Russian and English documents. Read the extractor's status for each page and spot-check material figures, including any pages sent to OCR.
