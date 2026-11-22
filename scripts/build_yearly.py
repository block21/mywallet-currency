#!/usr/bin/env python3
"""Build composite files of daily exchange rates per year and per month.

Under the output directory (default ``public``) it writes, for every
finished year from ``--from`` to ``--to`` (default 2010 to the current
year)::

    years/YYYY.json      every day of the year
    months/YYYY-MM.json  every day of one month

and, for the current year, ``months/YYYY-MM.json`` for each month that has
ended. Both have the same shape::

    {"base": "USD", "year": 2010, "generatedAt": "...", "source": "...",
     "days": {
       "2010-01-01": {"AED": 3.6725, "EUR": 0.6977, ...},
       ...
     }}

with ``"month": "2010-01"`` in place of ``"year"`` in a month file.

Only missing files are built (``--rebuild`` rebuilds the range), so the
daily workflow can run this every day: it does nothing until a month or a
year ends. A past year's month files are cut from its year file, with no
new requests; a month of the current year is fetched on its own.

Every calendar day is present. Frankfurter publishes most currencies on
working days only, so a day without a fresh rate for a currency carries the
last rate published before it, the same rate the app would have shown that
day. A currency appears from the first day it has a rate and is never
invented before that.

The currencies are the ones the daily build (``build_rates.py``) publishes:
ISO 4217 currencies in Frankfurter's ``/currencies`` list. Retired codes that
Frankfurter no longer lists (EEK, HRK, BYR...) and crypto and metals are left
out. Numbers are written exactly as Frankfurter sent them, never through a
float.

A period is refused (nothing written for it, non-zero exit) when a day has
fewer than ``MIN_CURRENCIES`` currencies, misses one of ``REQUIRED``, or has
a non-positive rate. Day-over-day moves above ``MAX_MOVE`` are reported as
warnings only, since real devaluations happen in history.

Standard library only. Run with::

    python3 scripts/build_yearly.py public                    # whatever is missing
    python3 scripts/build_yearly.py public --from 2024 --to 2024 --rebuild
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from decimal import Decimal

from build_rates import BASE, MAX_MOVE, MIN_CURRENCIES, REQUIRED, SOURCE, BuildError, fetch

FIRST_YEAR = 2010

# How far before a period to look for the rates to carry into its first days
LOOKBACK_DAYS = 14


# MARK: - Building


def build_days(
    first: dt.date,
    last: dt.date,
    currency_rows: list[dict],
    rate_rows: list[dict],
) -> tuple[dict[str, dict[str, Decimal]], list[str]]:
    """The rates of every day from ``first`` to ``last``, and any warnings.

    ``rate_rows`` is Frankfurter's ``/rates?base=USD&from=...&to=...`` answer
    covering the period and a few days before it. Raises ``BuildError``.
    """
    currencies = {row["iso_code"] for row in currency_rows if row.get("type") == "currency"}

    published: dict[str, dict[str, Decimal]] = {}
    for row in rate_rows:
        if row.get("base") == BASE and row.get("quote") in currencies:
            published.setdefault(row["date"], {})[row["quote"]] = Decimal(row["rate"])

    current: dict[str, Decimal] = {}
    for date in sorted(d for d in published if d < first.isoformat()):
        current.update(published[date])

    days: dict[str, dict[str, Decimal]] = {}
    warnings: list[str] = []
    day = first
    while day <= last:
        key = day.isoformat()
        fresh = published.get(key, {})
        for code, rate in fresh.items():
            before = current.get(code)
            if before and abs(rate - before) / before > MAX_MOVE:
                warnings.append(f"{key}: {code} moved {before} -> {rate}")
        current.update(fresh)
        days[key] = dict(current)
        day += dt.timedelta(days=1)

    for key, rates in days.items():
        if len(rates) < MIN_CURRENCIES:
            raise BuildError(f"{key}: only {len(rates)} currencies, expected at least {MIN_CURRENCIES}")
        missing = REQUIRED - rates.keys()
        if missing:
            raise BuildError(f"{key}: required currencies missing: {', '.join(sorted(missing))}")
        bad = [code for code, rate in rates.items() if rate <= 0]
        if bad:
            raise BuildError(f"{key}: non-positive rates for: {', '.join(sorted(bad))}")

    return days, warnings


def build_year(year: int, currency_rows: list[dict], rate_rows: list[dict], now: dt.datetime) -> tuple[str, list[str]]:
    """The year's document and any warnings, or ``BuildError``."""
    days, warnings = build_days(dt.date(year, 1, 1), dt.date(year, 12, 31), currency_rows, rate_rows)
    return render(header("year", year, now), days), warnings


def build_month(
    year: int, month: int, currency_rows: list[dict], rate_rows: list[dict], now: dt.datetime
) -> tuple[str, list[str]]:
    """The month's document and any warnings, or ``BuildError``."""
    first, last = month_bounds(year, month)
    days, warnings = build_days(first, last, currency_rows, rate_rows)
    return render(header("month", f"{year}-{month:02d}", now), days), warnings


def split_year(text: str, now: dt.datetime) -> dict[str, str]:
    """A year document cut into month documents, keyed ``YYYY-MM``."""
    days = json.loads(text, parse_float=Decimal, parse_int=Decimal)["days"]
    months: dict[str, dict[str, dict[str, Decimal]]] = {}
    for date, rates in days.items():
        months.setdefault(date[:7], {})[date] = rates
    return {month: render(header("month", month, now), month_days) for month, month_days in months.items()}


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    first = dt.date(year, month, 1)
    after = dt.date(year + month // 12, month % 12 + 1, 1)
    return first, after - dt.timedelta(days=1)


def header(kind: str, period: int | str, now: dt.datetime) -> dict:
    return {
        "base": BASE,
        kind: period,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE,
    }


def render(document: dict, days: dict[str, dict[str, Decimal]]) -> str:
    """The document as JSON, one line per day, every rate a plain decimal literal."""
    head = ",\n  ".join(f"{json.dumps(key)}: {json.dumps(value)}" for key, value in document.items())
    lines = []
    for date, rates in days.items():
        body = ", ".join(f"{json.dumps(code)}: {format(rate, 'f')}" for code, rate in sorted(rates.items()))
        lines.append(f"{json.dumps(date)}: {{{body}}}")
    text = "{\n  " + head + ',\n  "days": {\n    ' + ",\n    ".join(lines) + "\n  }\n}\n"
    json.loads(text)  # the output must be valid JSON
    return text


# MARK: - Running


def fetch_period(first: dt.date, last: dt.date) -> list[dict]:
    start = (first - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    return fetch(f"/rates?base={BASE}&from={start}&to={last.isoformat()}")


def main() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", default="public", help="output directory (default: public)")
    parser.add_argument("--from", dest="start", type=int, default=FIRST_YEAR, help=f"first year (default: {FIRST_YEAR})")
    parser.add_argument("--to", dest="end", type=int, default=now.year, help="last year (default: the current year)")
    parser.add_argument("--rebuild", action="store_true", help="rebuild files in the range that already exist")
    args = parser.parse_args()
    if args.start > args.end or args.end > now.year:
        parser.error(f"years must run from earliest to latest and end by {now.year}, the current year")

    out = pathlib.Path(args.out)
    (out / "years").mkdir(parents=True, exist_ok=True)
    (out / "months").mkdir(parents=True, exist_ok=True)

    currencies: list[dict] = []
    written: list[str] = []
    failed: list[str] = []

    def needed(path: pathlib.Path) -> bool:
        return args.rebuild or not path.exists()

    def write(path: pathlib.Path, text: str, warnings: list[str], label: str) -> None:
        for warning in warnings:
            print(f"::warning::{label}: {warning}")
        path.write_text(text)
        written.append(label)
        print(f"Wrote {path} ({len(text) // 1024} KB)")

    def try_build(label: str, make) -> bool:
        if not currencies:
            currencies.extend(fetch("/currencies"))
        try:
            return make()
        except BuildError as error:
            print(f"::error::{label}: {error}")
            failed.append(label)
            return False

    # Finished years, and their months cut from the year file
    for year in range(args.start, min(args.end, now.year - 1) + 1):
        year_path = out / "years" / f"{year}.json"
        if needed(year_path):
            def make_year(year=year, year_path=year_path):
                rows = fetch_period(dt.date(year, 1, 1), dt.date(year, 12, 31))
                write(year_path, *build_year(year, currencies, rows, now), str(year))
                return True
            if not try_build(str(year), make_year):
                continue
        rebuilt_year = str(year) in written
        for month, text in split_year(year_path.read_text(), now).items():
            month_path = out / "months" / f"{month}.json"
            if rebuilt_year or needed(month_path):
                write(month_path, text, [], month)

    # Months of the current year that have ended, fetched one by one
    if args.end == now.year:
        for month in range(1, now.month):
            label = f"{now.year}-{month:02d}"
            month_path = out / "months" / f"{label}.json"
            if needed(month_path):
                def make_month(month=month, month_path=month_path, label=label):
                    rows = fetch_period(*month_bounds(now.year, month))
                    write(month_path, *build_month(now.year, month, currencies, rows, now), label)
                    return True
                try_build(label, make_month)

    if not written and not failed:
        print("Nothing to build: every file already exists")
    if failed:
        print(f"Not written: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
