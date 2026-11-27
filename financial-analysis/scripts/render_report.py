#!/usr/bin/env python3
"""Render the standalone branded financial report using the original A4 layout."""

import argparse
from datetime import date
from decimal import Decimal
from io import BytesIO
import math
from pathlib import Path
from urllib.parse import urlsplit

from pypdf import PdfReader, PdfWriter

from analyze_cash_position import read_json
from currency import currency_code
from calculate_obligation_calendar import add_months
from financial_layout import (
    A, CASHFLOW, CURRENT_DEBT, GRAY, H, L, R, RATIOS, STATEMENTS, VERSION, W,
    Pages, ReportError, financial, load_assets,
)
from historical_cashflow import shifted_month
from ip_layout import normalize_ip, render_ip
from report_facts import fact, missing, normalize_score, obj, sequence, stamp, text

FIELD_KEYS = ("summary", "amount", "rate", "term", "chart_period", "debt_date", "ratio_period", "footnote")
HISTORY_KEYS = {
    "business_flow": "business_flow_before_creditors",
    "creditor_payments": "creditor_payments",
    "external_receipts": "external_receipts",
    "borrowed_receipts": "borrowed_receipts",
    "owner_contributions": "owner_contributions",
}


def source_catalog(raw, assessment):
    catalog = {}
    for source in sequence(raw, "sources"):
        obj(source, {"id", "title", "locator", "document_date", "credit_report", "url"}, "source")
        sid = text(source.get("id"), "source.id")
        if sid in catalog:
            raise ReportError(f"Повтор источника {sid}")
        text(source.get("title"), f"{sid}.title")
        text(source.get("locator"), f"{sid}.locator")
        if "document_date" in source:
            stamp(source["document_date"], f"{sid}.document_date")
        if "credit_report" in source:
            bureau = obj(source["credit_report"], {"bureau", "person_id"}, f"{sid}.credit_report")
            text(bureau.get("bureau"), f"{sid}.bureau")
            text(bureau.get("person_id"), f"{sid}.person_id")
            if source.get("document_date", "9999-12-31") > assessment:
                raise ReportError(f"{sid}: нужна дата кредитного отчёта не позже даты анализа")
        if "url" in source:
            parsed = urlsplit(text(source["url"], f"{sid}.url"))
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ReportError(f"{sid}: ссылка источника должна быть HTTPS без учётных данных")
        catalog[sid] = source
    return catalog


def persons(raw, sources, subject, business_id):
    result = []
    seen = set()
    for person in sequence(raw, "persons"):
        obj(person, {"id", "name", "score", "score_max"}, "person")
        person_id = text(person.get("id"), "person.id")
        name = text(person.get("name"), "person.name")
        if person_id in seen or (person_id == business_id and name != subject):
            raise ReportError(f"Карточка участника {person_id} дублируется или относится к другому лицу")
        seen.add(person_id)
        score = normalize_score(fact(person.get("score"), sources, "person.score"), sources, person_id)
        maximum = person.get("score_max")
        if score["value"] is not None:
            score_value = score["value"]
            if (type(maximum) is not int or maximum <= 0 or type(score_value) is not int
                    or not 0 <= score_value <= maximum):
                raise ReportError("Число рейтинга должно входить в указанную исходную шкалу бюро")
        result.append({**person, "score": score, "roles": ["borrower"] if person_id == business_id else []})
    return result


def display_fact(raw, sources, where, *, numeric=False):
    result = fact(raw, sources, where)
    if result["status"] not in {"confirmed", "calculated"}:
        return {**result, "value": None}
    if numeric and not isinstance(result["value"], (int, float)):
        raise ReportError(f"{where}: требуется числовое значение")
    return result


def date_range(start, end):
    return {"start": start.isoformat(), "end": end.isoformat()}


def financial_review(position, sources, day, accounting_mode, unit):
    if position and "obligation_calendar" not in position:
        raise ReportError("Нужен результат analyze_cash_position.py")
    calendar = position.get("obligation_calendar", {})
    coverage = position.get("coverage", {})
    history = position.get("historical_cashflow", {})
    stage_ids = sorted({source["id"] for stage in (calendar, coverage, history)
                        for source in stage.get("sources", [])})
    start = date.fromisoformat(day)
    first_this_month = start.replace(day=1)
    last = date.fromordinal(first_this_month.toordinal() - 1)
    horizon = calendar.get("horizon") or {
        "start": day, "end_exclusive": add_months(start, 6).isoformat(),
    }

    def calculated(raw, unit_label=None):
        raw = raw or {}
        refs = raw.get("sources", [])
        value = raw.get("value")
        scenario = value is None and raw.get("scenario_value") is not None
        if scenario:
            value = raw["scenario_value"]
        if value is None:
            return missing()
        if not refs:
            refs = stage_ids
        if not refs:
            raise ReportError("Расчётное значение требует источника")
        decimal = Decimal(str(value))
        number = float(decimal)
        if not math.isfinite(number) or Decimal(str(number)) != decimal:
            raise ReportError("Число не помещается в точность финансовой формы")
        return fact({"status": "calculated", "value": number, "sources": refs,
                     "derivation": raw.get("formula") or "Результат расчёта денежной позиции",
                     **({"unit": unit_label} if unit_label else {}),
                     "conservative": bool(raw.get("conservative")),
                     "scenario_only": scenario}, sources, "calculated")

    metrics = {
        key: calculated(coverage.get(key), label)
        for key, label in (("coverage_ratio", "раз"), ("payments", unit),
                           ("max_dated_deficit", unit), ("relative_deficit", "%"))
    }
    if not coverage and calendar:
        payment = {**calendar["totals"], "sources": [s["id"] for s in calendar["sources"]]}
        metrics["payments"] = calculated(payment, unit)
    metrics["opening_money"] = calculated(coverage.get("opening", {}).get("available_for_legacy"), unit)
    metrics["forecast_flow"] = calculated(coverage.get("trend", {}).get("last_six_month_total"), unit)

    windows = {}
    for size in (6, 12):
        key = f"{size}m"
        window = history.get("windows", {}).get(key, {})
        totals = window.get("totals", {})
        windows[key] = {
            "period": window.get("period") or date_range(shifted_month(first_this_month, -size), last),
            "fields": {**{dest: calculated(totals.get(src), unit) for dest, src in HISTORY_KEYS.items()},
                       "historical_coverage": calculated(window.get("historical_coverage")),
                       "borrowed_share": calculated(window.get("borrowed_share"))},
        }
    maximum = coverage.get("max_dated_deficit", {})
    result = {
        "accounting_mode": accounting_mode, "horizon": horizon, "metrics": metrics, "history": windows,
        "maximum_date": maximum.get("date"), "maximum_month_index": maximum.get("month_index"),
    }
    if budget := coverage.get("borrower_budget", {}).get("operating_flow"):
        if budget.get("period"):
            result["borrower_budget"] = {"period": budget["period"], "flow": calculated(budget, unit)}
    return result


def normalize(raw, position=None):
    obj(raw, {"schema_version", "report_id", "title", "subject", "borrower_id", "as_of", "currency",
              "demo", "layout", "accounting_mode", "sources", "persons", "financial"}, "report")
    if raw.get("schema_version") != 1 or type(raw.get("demo", False)) is not bool:
        raise ReportError("Требуются schema_version: 1 и логическое demo")
    day = stamp(raw["as_of"], "as_of")
    currency = currency_code(raw["currency"])
    unit = "₽" if currency == "RUB" else currency
    subject = text(raw["subject"], "subject")
    borrower_id = text(raw["borrower_id"], "borrower_id")
    accounting_mode = raw.get("accounting_mode", "corporate")
    if accounting_mode not in {"corporate", "ip"}:
        raise ReportError("accounting_mode: corporate или ip")
    default_layout = "ip" if accounting_mode == "ip" else "coverage" if position else "statement"
    layout = raw.get("layout", default_layout)
    if accounting_mode == "ip" and layout == "coverage":
        layout = "ip"
    if layout not in ({"ip"} if accounting_mode == "ip" else {"statement", "coverage"}):
        raise ReportError("layout: ip для ИП, statement или coverage для компании")
    position = position or {}
    if position and (position.get("currency"), position.get("assessment_date"), position.get("borrower_id")) != (
            currency, day, borrower_id):
        raise ReportError("Валюта, дата или заёмщик расчёта денежной позиции не совпадают с отчётом")
    catalog = source_catalog(raw.get("sources", []), day)
    for stage in ("obligation_calendar", "historical_cashflow", "coverage"):
        for source in position.get(stage, {}).get("sources", []):
            catalog.setdefault(source["id"], {"id": source["id"], "title": Path(source["file"]).name,
                                             "locator": source["locator"]})
    section = obj(raw.get("financial", {}), {"fields", "periods", "balance_dates", "statements",
                                                  "cashflow", "current_debt", "ratios", "ip"}, "financial")

    def fact_fields(raw_fields, keys, where, *, numeric=False):
        obj(raw_fields, keys, where)
        return {key: display_fact(raw_fields.get(key), catalog, f"{where}.{key}", numeric=numeric) for key in keys}

    def columns(items, where, *, numeric=False):
        if not isinstance(items, list) or len(items) != 3:
            raise ReportError(f"{where}: нужны три периода, отсутствующие можно оставить null")
        return [display_fact(item, catalog, where, numeric=numeric) for item in items]

    raw_statements = obj(section.get("statements", {}), {key for key, _ in STATEMENTS}, "statements")
    raw_ratios = obj(section.get("ratios", {}), {key for key, _ in RATIOS}, "ratios")
    financial_data = {
        "fields": fact_fields(section.get("fields", {}), FIELD_KEYS, "fields"),
        "periods": columns(section.get("periods", [None] * 3), "periods"),
        "balance_dates": columns(section.get("balance_dates", [None] * 3), "balance_dates"),
        "statements": {key: columns(raw_statements.get(key, [None] * 3), key, numeric=True) for key, _ in STATEMENTS},
        "cashflow": fact_fields(section.get("cashflow", {}), [key for key, _ in CASHFLOW], "cashflow", numeric=True),
        "current_debt": fact_fields(section.get("current_debt", {}), [key for key, _ in CURRENT_DEBT],
                                    "current_debt", numeric=True),
        "ratios": {key: fact_fields(raw_ratios.get(key, {}), ("before", "after"), f"ratios.{key}", numeric=True)
                   for key, _ in RATIOS},
    }
    if financial_data["fields"]["amount"]["value"] is not None:
        amount = financial_data["fields"]["amount"]
        if not isinstance(amount["value"], (int, float)):
            raise ReportError("Сумма займа должна быть числом")
        amount["unit"] = unit
    if layout == "ip":
        financial_data["ip"] = normalize_ip(section.get("ip", {}), catalog, day)
        financial_data["ip_calendar"] = position.get("obligation_calendar", {
            "horizon": {"start": day, "end_exclusive": add_months(date.fromisoformat(day), 6).isoformat()},
        })
    if layout == "coverage":
        financial_data["review"] = financial_review(position, catalog, day, accounting_mode, unit)
    return {
        "subject": subject, "as_of": day, "title": text(raw.get("title", "Финансовый отчёт"), "title"),
        "report_id": text(raw["report_id"], "report_id"), "demo": raw.get("demo", False), "money_unit": unit,
        "sources": list(catalog.values()), "persons": persons(raw.get("persons", []), catalog, subject, borrower_id),
        "sections": {"financial": financial_data},
    }


def render(raw, position=None):
    data = normalize(raw, position)
    pages = Pages(data, load_assets())
    is_ip = "ip" in data["sections"]["financial"]
    (render_ip if is_ip else financial)(pages)
    pages.end()
    if len(pages.pages) != 1:
        raise ReportError("Финансовый отчёт должен помещаться на одном A4")

    writer = PdfWriter()
    page = writer.add_page(PdfReader(BytesIO(pages.pages[0]["data"]), strict=True).pages[0])
    writer.add_outline_item("Финансовый отчёт", 0)
    footer = BytesIO()
    pages.c = pages.Canvas(footer, pagesize=(W, H), invariant=1)
    label = data["as_of"] + " / " + data["report_id"]
    if pages.stringWidth(label, "Body", 8) > A - 45:
        raise ReportError("Идентификатор отчёта слишком длинный для колонтитула")
    pages.rule(L, 797, R)
    pages.lab(label, L, 811, 8, color=GRAY)
    pages.lab("1 / 1", R, 811, 8, True, right=True)
    layout_name = "Лист финансового анализа ИП" if is_ip else "Оформление по принятому макету 0.8"
    pages.lab(layout_name + " / " + VERSION, L, 823, 7.8, color=GRAY)
    pages.c.save()
    page.merge_page(PdfReader(footer).pages[0])
    writer.add_metadata({"/Title": data["title"], "/Author": "ВБетон", "/Subject": VERSION + " / financial",
                         "/Keywords": "Информационный отчёт; " + data["as_of"]})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cash-position", type=Path)
    args = parser.parse_args()
    try:
        position = read_json(args.cash_position) if args.cash_position else None
        pdf = render(read_json(args.input), position)
        with args.output.open("xb") as stream:
            stream.write(pdf)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
