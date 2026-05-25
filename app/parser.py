from __future__ import annotations

import re

from .models import FareOption, FlightOption

FLIGHT_LINE = re.compile(
    r"(?P<flight>[A-Z0-9]{2}\d{3,4})\s+"
    r"(?P<depart>\d{4})\s+"
    r"(?P<arrive>\d{4})"
    r"(?:\s+(?P<cabin>[A-Z]))?"
    r"(?:\s*(?P<availability>[0-9A-Z]))?"
)
FARE_AMOUNT = re.compile(r"\b(?P<currency>[A-Z]{3})\s*(?P<amount>\d+(?:\.\d{1,2})?)\b")
FARE_RULE = re.compile(r"\b(?:RULE|RULES?|R)\s*[:\-]?\s*(?P<rule>[A-Z0-9]{1,12})\b")
PASSENGER_TYPE = re.compile(r"\b(?P<passenger_type>ADT|CNN|CHD|INF|SRC|STU)\b")


def parse_flight_options(raw_text: str) -> list[FlightOption]:
    """Parse simple flight rows from black-screen text.

    The regex is intentionally conservative and should be adjusted once you
    capture real output from your iEterm deployment.
    """

    flights: list[FlightOption] = []
    for line in raw_text.splitlines():
        match = FLIGHT_LINE.search(line.strip())
        if not match:
            continue
        flights.append(
            FlightOption(
                flight_no=match.group("flight"),
                depart_time=_format_time(match.group("depart")),
                arrive_time=_format_time(match.group("arrive")),
                cabin=match.group("cabin"),
                availability=match.group("availability"),
            )
        )
    return flights


def parse_fare_options(raw_text: str) -> list[FareOption]:
    """Parse conservative international fare rows from black-screen text.

    Fare displays vary significantly by deployment. This parser only emits a
    structured fare when a line clearly contains a currency and amount.
    """

    fares: list[FareOption] = []
    for line in raw_text.splitlines():
        normalized = " ".join(line.strip().split())
        if not normalized:
            continue

        amount_match = FARE_AMOUNT.search(normalized)
        if not amount_match:
            continue

        tokens = normalized.split()
        currency = amount_match.group("currency")
        passenger_match = PASSENGER_TYPE.search(normalized)
        rule_match = FARE_RULE.search(normalized)
        fares.append(
            FareOption(
                airline=_guess_airline(tokens, currency),
                fare_basis=_guess_fare_basis(tokens, currency),
                cabin=_guess_cabin(tokens),
                currency=currency,
                amount=amount_match.group("amount"),
                rule=rule_match.group("rule") if rule_match else None,
                passenger_type=passenger_match.group("passenger_type") if passenger_match else None,
                raw_line=normalized,
            )
        )
    return fares


def _format_time(value: str) -> str:
    if len(value) != 4 or not value.isdigit():
        return value
    return f"{value[:2]}:{value[2:]}"


def _guess_airline(tokens: list[str], currency: str) -> str | None:
    for token in tokens:
        clean = token.strip("/,:;")
        if clean == currency:
            continue
        if re.fullmatch(r"[A-Z0-9]{2}", clean) and any(char.isalpha() for char in clean):
            return clean
    return None


def _guess_fare_basis(tokens: list[str], currency: str) -> str | None:
    excluded = {currency, "RULE", "RULES", "ADT", "CNN", "CHD", "INF", "SRC", "STU"}
    for token in tokens:
        clean = token.strip("/,:;")
        if clean in excluded:
            continue
        if re.fullmatch(r"[A-Z][A-Z0-9]{1,19}", clean) and any(char.isdigit() for char in clean):
            return clean
        if re.fullmatch(r"[A-Z]{2,}[A-Z0-9]{0,18}", clean) and len(clean) > 2:
            return clean
    return None


def _guess_cabin(tokens: list[str]) -> str | None:
    known_cabins = {"F", "A", "J", "C", "D", "I", "W", "Y", "B", "M", "H", "K", "L", "Q", "V", "N", "T", "S", "X"}
    for token in tokens:
        clean = token.strip("/,:;")
        if clean in known_cabins:
            return clean
    return None
