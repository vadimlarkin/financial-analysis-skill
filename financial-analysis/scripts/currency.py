"""Validate the declared currency label for single-currency calculations."""

import re


def currency_code(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("currency must be a three-letter uppercase currency code")
    return value
