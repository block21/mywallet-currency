#!/usr/bin/env python3
"""Build the MyWallet fallback exchange-rate files from Frankfurter.

Writes, under the output directory (default ``public``):

- ``latest.json``: today's rates
- ``history/YYYY-MM-DD.json``: the same document, kept for the day it was built

Both use the shape the app already reads for its bundled rates
(``BundledExchangeRates``)::

    {"base": "USD", "asOf": "2026-11-13", "generatedAt": "...",
     "source": "...", "rates": {"EUR": 0.86, "SEK": 9.96, ...}}

Rates are units of each currency per one ``base``. Numbers are written
exactly as Frankfurter sent them, never through a float.

The build refuses to write anything (and exits non-zero, so the last good
files stay published) when the data looks wrong: too few currencies, a
required currency missing, a non-positive rate, rates older than
``MAX_AGE_DAYS``, or a currency that moved more than ``MAX_MOVE`` since the
previous ``latest.json``. Set ``FORCE=true`` to skip the movement check after
checking a genuine large move, such as a devaluation.

Standard library only. Tests: ``python3 -m unittest discover -s scripts``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal

API = "https://api.frankfurter.dev/v2"
BASE = "USD"
SOURCE = "Frankfurter (frankfurter.dev), blended central bank reference rates"

# The app's quick-access currencies; a file without any of them is useless
REQUIRED = {"EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "SEK", "NOK", "DKK"}
MIN_CURRENCIES = 100
MAX_AGE_DAYS = 5
MAX_MOVE = Decimal("0.5")  # 50% against the previous file

USER_AGENT = "mywallet-currency/1.0 (+https://github.com/block21/mywallet-currency)"


class BuildError(Exception):
    """The data looks wrong; nothing should be published."""


# MARK: - Building


def build(
    currency_rows: list[dict],
    rate_rows: list[dict],
    previous: dict[str, Decimal],
    now: dt.datetime,
    force: bool = False,
) -> tuple[str, list[str]]:
    """The document to publish and any warnings, or ``BuildError``.

    ``currency_rows`` and ``rate_rows`` are Frankfurter's ``/currencies`` and
    ``/rates?base=USD`` answers; ``previous`` is the rates of the last
    published file, empty on the first run.
    """
    currencies = {row["iso_code"] for row in currency_rows if row.get("type") == "currency"}

    rates: dict[str, Decimal] = {}
    dates: set[str] = set()
    for row in rate_rows:
        if row.get("base") == BASE and row.get("quote") in currencies:
            rates[row["quote"]] = Decimal(row["rate"])
            dates.add(row["date"])

    if len(rates) < MIN_CURRENCIES:
        raise BuildError(f"Only {len(rates)} currencies, expected at least {MIN_CURRENCIES}")
    missing = REQUIRED - rates.keys()
    if missing:
        raise BuildError(f"Required currencies missing: {', '.join(sorted(missing))}")
    bad = [code for code, rate in rates.items() if rate <= 0]
    if bad:
        raise BuildError(f"Non-positive rates for: {', '.join(sorted(bad))}")

    as_of = max(dates)
    age = (now.date() - dt.date.fromisoformat(as_of)).days
    if age > MAX_AGE_DAYS:
        raise BuildError(f"Newest rate is from {as_of}, {age} days old")

    warnings = []
    moved = []
    for code, rate in rates.items():
        before = previous.get(code)
        if before and abs(rate - before) / before > MAX_MOVE:
            moved.append(f"{code} {before} -> {rate}")
    if moved and not force:
        raise BuildError(
            "Rates moved more than 50% since the last file (rerun with force if genuine): " + "; ".join(moved)
        )
    warnings += [f"Forced past a large move: {line}" for line in moved]

    dropped = sorted(previous.keys() - rates.keys())
    if dropped:
        warnings.append(f"No longer published: {', '.join(dropped)}")

    document = {
        "base": BASE,
        "asOf": as_of,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE,
    }
    text = render(document, rates)
    json.loads(text)  # the output must be valid JSON
    return text, warnings


def render(document: dict, rates: dict[str, Decimal]) -> str:
    """The document as JSON, with every rate written as a plain decimal literal."""
    header = ",\n  ".join(f"{json.dumps(key)}: {json.dumps(value)}" for key, value in document.items())
    body = ",\n    ".join(f"{json.dumps(code)}: {format(rate, 'f')}" for code, rate in sorted(rates.items()))
    return "{\n  " + header + ',\n  "rates": {\n    ' + body + "\n  }\n}\n"


def read_rates(text: str) -> dict[str, Decimal]:
    """The rates of a published document, exact."""
    return json.loads(text, parse_float=Decimal, parse_int=Decimal).get("rates", {})


# MARK: - Running


def fetch(path: str, attempts: int = 3):
    """GET ``API + path`` as JSON with decimals kept exact, retrying briefly."""
    request = urllib.request.Request(
        API + path, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response, parse_float=Decimal, parse_int=Decimal)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == attempts:
                raise
            print(f"Attempt {attempt} for {path} failed ({error}); retrying", file=sys.stderr)
            time.sleep(5 * attempt)


def main() -> None:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "public")
    force = os.environ.get("FORCE", "").lower() == "true"
    now = dt.datetime.now(dt.timezone.utc)

    latest = out / "latest.json"
    previous = read_rates(latest.read_text()) if latest.exists() else {}

    try:
        text, warnings = build(fetch("/currencies"), fetch(f"/rates?base={BASE}"), previous, now, force)
    except BuildError as error:
        print(f"::error::{error}")
        sys.exit(1)
    for warning in warnings:
        print(f"::warning::{warning}")

    (out / "history").mkdir(parents=True, exist_ok=True)
    latest.write_text(text)
    (out / "history" / f"{now.date().isoformat()}.json").write_text(text)
    print(f"Wrote {len(read_rates(text))} rates to {out}")


if __name__ == "__main__":
    main()
