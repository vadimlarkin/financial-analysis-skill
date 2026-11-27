#!/usr/bin/env python3
"""Build a debt calendar, bank cash-flow history and optional coverage scenario."""

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path

from analyze import unique_pairs
from calculate_coverage import calculate as calculate_coverage
from calculate_obligation_calendar import calculate as calculate_calendar
from currency import currency_code
from historical_cashflow import calculate as calculate_history


def read_json(path):
    def reject_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                      parse_constant=reject_constant)


def analyze(case, root):
    assessment_date = date.fromisoformat(case["assessment_date"]).isoformat()
    currency = currency_code(case["currency"])
    result = {"assessment_date": assessment_date, "currency": currency, "borrower_id": case["borrower_id"]}
    debt = read_json(root / case["debt_summary"])
    if not debt["ok"] or debt["report_date"] > assessment_date:
        raise ValueError("Debt summary failed validation or postdates the assessment")
    if debt["borrower_id"] != case["borrower_id"] or debt["currency"] != currency:
        raise ValueError("Debt summary belongs to a different business or currency")
    calendar = calculate_calendar(debt, assessment_date)
    result["obligation_calendar"] = calendar
    if "cashflow" not in case:
        if "coverage" in case:
            raise ValueError("Coverage requires bank cash-flow history")
        return result

    cashflow = read_json(root / case["cashflow"])
    if cashflow["currency"] != currency or cashflow["period"]["end"] > assessment_date:
        raise ValueError("Cash-flow currency or dates differ from the assessment")
    sources = {}
    versions = {}
    for collection in (cashflow["sources"], debt["sources"], case.get("sources", [])):
        for source in collection:
            source_id = source["id"]
            path = root / source["file"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if source.get("sha256", digest).lower() != digest:
                raise ValueError(f"Source changed since preparation: {source_id}")
            identity = {"id": source_id, "file": source["file"], "locator": source["locator"]}
            if source_id in sources and (sources[source_id] != identity or versions[source_id] != digest):
                raise ValueError(f"Conflicting source ID: {source_id}")
            sources[source_id], versions[source_id] = identity, digest

    history = calculate_history(cashflow, debt, case["history"], assessment_date,
                                list(sources.values()), versions,
                                outside_transfers=case.get("outside_transfers", []),
                                duplicate_lineage=case.get("duplicate_lineage", []))
    result["historical_cashflow"] = history
    if "coverage" in case:
        intake = case["bank_scope"]
        result["coverage"] = calculate_coverage(history, calendar, case["coverage"], intake,
                                                cashflow=cashflow, register=debt)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = analyze(read_json(args.case), args.case.resolve().parent)
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
