---
name: financial-analysis
description: Analyze a business or sole proprietor from financial statements, bank transactions and debt documents. Calculate cash flow, debt service and liquidity when supported, and deliver a branded PDF with a sourced credit bureau score when available. Анализирует финансы бизнеса и ИП по отчётности, выпискам и долгам, готовит PDF.
---

# Financial analysis

Use the user's documents to assess the financial position of one business on a stated date. Work in the user's language. Determine the purpose, reporting date, entity, currency and proposed loan terms when relevant. Use local files or attachments available in the session. Obtain explicit source locators before using a figure.

## Prepare the evidence

1. Inventory statements, trial balances, bank accounts and dates, contracts, creditor statements and payment schedules. Identify whether each figure is confirmed, calculated, disputed or missing. Request the missing documents that materially affect the requested analysis. Continue with the supported parts when the user supplies only part of the evidence.
2. Extract readable PDF text first. For scans, use local OCR if available, then confirm material amounts, dates, rows and columns against the original. For CSV, verify the header, debit and credit convention and currency before importing. Keep the unmodified source and a record of file, page, sheet or row.
3. Use a single currency for a given calculation. Prepare separate calculations for different currencies or document the user's conversion basis and retain the original amounts. Compare periods of equivalent length and keep balance dates distinct from turnover periods.

## Calculate

- **Financial statements.** Read [the accounting input contract](references/input-contract.md). Run `scripts/analyze.py` on verified figures to calculate leverage, interest coverage, cash coverage and liquidity. Compare like periods, explain one-offs and stale balances, and treat the script's color thresholds as method assumptions. Preserve uncertain denominators and missing loan terms.
- **Bank statements.** Read [the bank input contract](references/local-cashflow.md). Use the [CSV import profile](references/local-statement-csv.md) for CSV, [overlap reconciliation](references/local-statement-overlaps.md) for repeated exports, and [own-transfer matching](references/local-own-transfers.md) where both accounts or other transfer evidence are available. Check the bank's independent balances and turnover. Separate customer receipts, financing, owner contributions, transfers, refunds, expenses and creditor payments. Bank receipts for a sole proprietor support a cash-flow analysis. Accounting revenue and profit require their own evidence.
- **Debt.** Read [the debt register contract](references/local-debt-register.md). Reconcile contracts, roles, as-of dates, outstanding principal, interest, overdue amounts and verified schedules. Keep guarantees separate unless payment has been demanded and confirmed. Read [the loan schedule contract](references/local-loan-schedule.md) to calculate documented or explicitly modeled new-loan terms.
- **Cash coverage scenario.** Read [the cash position workflow](references/cash-position.md) to calculate the available historical periods and six-month obligations. Assess opening balances, restrictions, predictable cash flows, scheduled obligations and dated shortfalls. Keep documented totals, incomplete subtotals and scenarios distinct. Use [the coverage contract](references/coverage.md) when the evidence supports a forward scenario.

See [running the tools](references/tools.md) for dependency setup and invocations. The calculations use prepared inputs. Recheck classification and material assumptions against the source documents before drawing conclusions.

## Deliver the report

Read [the branded report contract](references/report.md). Preserve the original A4 layout. Select the accounting form for statements, current debt, the receipts and repayments chart and the before-and-after loan comparison. For a sole proprietor without accounting statements, use the IP form with side-by-side receipts and payments, monthly receipt bars, creditor payments and the six-month calendar. Put verified partial subtotals in the tables. Mark missing values with short textual statuses.

If the user supplies a credit bureau report, check the subject, issuance date, original score, scale and page. Associate the score with that report in the PDF input. Use the original bureau value. Missing, calculated and disputed scores leave the circle empty or absent. If several confirmed ratings are available, use the approved header priority and preserve the sources in the report input.

Render the reviewed report with `scripts/render_report.py`. Use `--cash-position` to populate the IP calendar or company coverage directly from the calculation result. Inspect the PDF visually and compare its displayed numbers and rating against the evidence. Keep the JSON input and sources alongside the PDF so another analyst can trace its figures. Deliver the PDF with its date and material limitations. Keep source documents within the user's chosen environment.
