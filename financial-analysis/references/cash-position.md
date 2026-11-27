# Cash position and existing debt

Prepare a debt summary with `summarize_debt_register.py`. For historical calculation also prepare outgoing and incoming bank operations with `calculate_cashflow.py`. The assessment date and the debt summary must relate to the same borrower and the same set of verified obligations.

Write a case file and pass it to `analyze_cash_position.py`. Monetary amounts throughout the case, including the debt register, use the same declared currency with at most two decimal places. Paths are relative to the case file. Source IDs across inventories must be unique or refer to the same file and locator. The program records SHA-256 of the source files used for history and checks declared hashes.

```json
{
  "assessment_date": "2026-01-01",
  "borrower_id": "DEMO-01",
  "currency": "USD",
  "debt_summary": "debt-result.json",
  "cashflow": "bank-result.json",
  "history": {
    "reviewed_by": "Financial analyst",
    "classifications": []
  }
}
```

For a debt calendar only, omit `cashflow` and `history`. Read [the calendar contract](obligation-calendar.md) to distinguish known payments and modeled dates. For history, read [the classification rules](historical-cashflow.md). Add `sources` for supplemental evidence. Use `outside_transfers` from the own-transfer result and `duplicate_lineage` from the overlap result when available.

To calculate six months of forward coverage, add `coverage` using [the coverage contract](coverage.md), and declare the accounts checked in `bank_scope`:

```json
{
  "bank_scope": {
    "bank_target": {"all_accounts_confirmed": true},
    "bank_accounts": [
      {
        "account": "OPERATING",
        "periods": [{"start": "2025-01-01", "end": "2025-12-31", "sources": ["BANK"]}]
      }
    ]
  }
}
```

Use `all_accounts_confirmed: false` when the available records leave account coverage uncertain. This restricts aggregate opening balances. Credit bureau credentials are unnecessary. If the available record set does not establish completeness of obligations, leave the relevant totals limited.

The result has `obligation_calendar`, then `historical_cashflow` and `coverage` when requested. Read dated shortfalls and incomplete data before using summary ratios. Opening money, funds earmarked for specific obligations, recurring flow and timing assumptions are explicitly identified. A proposed loan does not enter the funds available for existing obligations.
