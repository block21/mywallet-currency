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

Standard library only.
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


def fail(message: str) -> None:
    print(f"::error::{message}")
    sys.exit(1)


def load_previous(path: pathlib.Path) -> dict[str, Decimal]:
    if not path.exists():
        return {}
    with path.open() as file:
        return json.load(file, parse_float=Decimal, parse_int=Decimal).get("rates", {})


def render(document: dict, rates: dict[str, Decimal]) -> str:
    """The document as JSON, with every rate written as a plain decimal literal."""
    header = ",\n  ".join(f"{json.dumps(key)}: {json.dumps(value)}" for key, value in document.items())
    body = ",\n    ".join(f"{json.dumps(code)}: {format(rate, 'f')}" for code, rate in sorted(rates.items()))
    return "{\n  " + header + ',\n  "rates": {\n    ' + body + "\n  }\n}\n"


def main() -> None:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "public")
    force = os.environ.get("FORCE", "").lower() == "true"
    today = dt.datetime.now(dt.timezone.utc).date()

    currencies = {row["iso_code"] for row in fetch("/currencies") if row.get("type") == "currency"}
    rows = fetch(f"/rates?base={BASE}")

    rates: dict[str, Decimal] = {}
    dates: set[str] = set()
    for row in rows:
        if row.get("base") == BASE and row.get("quote") in currencies:
            rates[row["quote"]] = row["rate"]
            dates.add(row["date"])

    # Validation
    if len(rates) < MIN_CURRENCIES:
        fail(f"Only {len(rates)} currencies, expected at least {MIN_CURRENCIES}")
    missing = REQUIRED - rates.keys()
    if missing:
        fail(f"Required currencies missing: {', '.join(sorted(missing))}")
    bad = [code for code, rate in rates.items() if rate <= 0]
    if bad:
        fail(f"Non-positive rates for: {', '.join(sorted(bad))}")

    as_of = max(dates)
    age = (today - dt.date.fromisoformat(as_of)).days
    if age > MAX_AGE_DAYS:
        fail(f"Newest rate is from {as_of}, {age} days old")

    previous = load_previous(out / "latest.json")
    moved = []
    for code, rate in rates.items():
        before = previous.get(code)
        if before and abs(rate - before) / before > MAX_MOVE:
            moved.append(f"{code} {before} -> {rate}")
    if moved and not force:
        fail("Rates moved more than 50% since the last file (rerun with force if genuine): " + "; ".join(moved))
    for line in moved:
        print(f"::warning::Forced past a large move: {line}")

    dropped = sorted(previous.keys() - rates.keys())
    if dropped:
        print(f"::warning::No longer published: {', '.join(dropped)}")

    document = {
        "base": BASE,
        "asOf": as_of,
        "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE,
    }
    text = render(document, rates)
    json.loads(text)  # the output must be valid JSON

    (out / "history").mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(text)
    (out / "history" / f"{today.isoformat()}.json").write_text(text)
    print(f"Wrote {len(rates)} rates as of {as_of} to {out}")


if __name__ == "__main__":
    main()
