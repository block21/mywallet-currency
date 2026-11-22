"""Tests for build_yearly.py. Run with ``python3 -m unittest discover -s scripts``."""

from __future__ import annotations

import datetime as dt
import json
import unittest
from decimal import Decimal

import build_rates as br
import build_yearly as by

NOW = dt.datetime(2026, 11, 22, 10, 0, tzinfo=dt.timezone.utc)

FILLER = [f"F{i:03d}" for i in range(120)]
CODES = sorted(br.REQUIRED) + FILLER


def currency_rows(codes=CODES, extra=()):
    return [{"iso_code": code, "type": "currency"} for code in codes] + list(extra)


def rows_for(date, rates=None, codes=CODES):
    rates = rates if rates is not None else {code: Decimal("2") for code in codes}
    return [{"date": date, "base": "USD", "quote": code, "rate": rate} for code, rate in rates.items()]


def every_day(year, codes=CODES):
    """A full set of rates on every day of ``year``."""
    rows, day = [], dt.date(year, 1, 1)
    while day.year == year:
        rows += rows_for(day.isoformat(), codes=codes)
        day += dt.timedelta(days=1)
    return rows


class BuildYearTests(unittest.TestCase):

    def build(self, rows, year=2010, currencies=None):
        return by.build_year(year, currencies or currency_rows(), rows, NOW)

    def test_every_calendar_day_is_present(self):
        text, _ = self.build(every_day(2012), year=2012)
        days = json.loads(text)["days"]

        self.assertEqual(len(days), 366)  # leap year
        self.assertEqual(next(iter(days)), "2012-01-01")
        self.assertEqual(list(days)[-1], "2012-12-31")

    def test_header(self):
        text, warnings = self.build(every_day(2010))
        document = json.loads(text)

        self.assertEqual(document["base"], "USD")
        self.assertEqual(document["year"], 2010)
        self.assertEqual(document["generatedAt"], "2026-11-22T10:00:00Z")
        self.assertEqual(warnings, [])

    def test_weekends_carry_the_last_rate(self):
        # Friday 2010-01-08 published; the weekend only has some currencies
        rows = every_day(2010)
        rows = [r for r in rows if r["date"] not in ("2010-01-09", "2010-01-10")]
        rows += rows_for("2010-01-08", {"SEK": Decimal("7.1234")})
        rows += rows_for("2010-01-09", {"EUR": Decimal("0.7001")})
        days = json.loads(self.build(rows)[0], parse_float=Decimal)["days"]

        self.assertEqual(days["2010-01-09"]["SEK"], Decimal("7.1234"))
        self.assertEqual(days["2010-01-10"]["SEK"], Decimal("7.1234"))
        self.assertEqual(days["2010-01-10"]["EUR"], Decimal("0.7001"))
        self.assertEqual(len(days["2010-01-10"]), len(CODES))

    def test_first_days_carry_rates_from_before_the_year(self):
        rows = rows_for("2009-12-31", {"SEK": Decimal("7.5")}) + rows_for("2009-12-31")
        rows += [r for r in every_day(2010) if not r["date"].startswith("2010-01-0")]
        days = json.loads(self.build(rows)[0], parse_float=Decimal)["days"]

        self.assertNotIn("2009-12-31", days)
        self.assertEqual(len(days["2010-01-01"]), len(CODES))

    def test_new_currency_starts_on_its_first_rate(self):
        rows = every_day(2022) + rows_for("2022-07-01", {"SLE": Decimal("12.5")})
        currencies = currency_rows(CODES + ["SLE"])
        days = json.loads(self.build(rows, year=2022, currencies=currencies)[0])["days"]

        self.assertNotIn("SLE", days["2022-06-30"])
        self.assertIn("SLE", days["2022-07-01"])
        self.assertIn("SLE", days["2022-12-31"])

    def test_unlisted_crypto_and_metals_are_left_out(self):
        extra = [{"iso_code": "BTC", "type": "crypto"}, {"iso_code": "XAU", "type": "metal"}]
        rows = every_day(2010) + rows_for("2010-01-04", {"BTC": Decimal("1"), "XAU": Decimal("1"), "EEK": Decimal("11")})
        days = json.loads(self.build(rows, currencies=currency_rows(extra=extra))[0])["days"]

        self.assertFalse({"BTC", "XAU", "EEK"} & days["2010-01-04"].keys())

    def test_rates_are_written_exactly(self):
        rows = every_day(2010) + rows_for("2010-06-01", {"JPY": Decimal("0.000000123")})
        text, _ = self.build(rows)

        self.assertIn('"JPY": 0.000000123', text)

    def test_large_move_is_a_warning_not_an_error(self):
        rows = every_day(2010) + rows_for("2010-06-01", {"SEK": Decimal("5")})
        _, warnings = self.build(rows)

        self.assertEqual(len(warnings), 2)  # up on 1 June, back down on 2 June
        self.assertIn("2010-06-01: SEK", warnings[0])

    def test_missing_required_currency_is_refused(self):
        codes = [c for c in CODES if c != "SEK"]
        with self.assertRaisesRegex(br.BuildError, "SEK"):
            self.build(every_day(2010, codes=codes))

    def test_too_few_currencies_is_refused(self):
        with self.assertRaisesRegex(br.BuildError, "only"):
            self.build(every_day(2010, codes=sorted(br.REQUIRED)))

    def test_non_positive_rate_is_refused(self):
        rows = every_day(2010) + rows_for("2010-03-01", {"EUR": Decimal("0")})
        with self.assertRaisesRegex(br.BuildError, "EUR"):
            self.build(rows)


class MonthTests(unittest.TestCase):

    def test_month_has_every_day_and_its_header(self):
        text, _ = by.build_month(2024, 2, currency_rows(), every_day(2024), NOW)
        document = json.loads(text)

        self.assertEqual(document["month"], "2024-02")
        self.assertNotIn("year", document)
        self.assertEqual(list(document["days"])[0], "2024-02-01")
        self.assertEqual(list(document["days"])[-1], "2024-02-29")

    def test_december_ends_on_the_31st(self):
        self.assertEqual(by.month_bounds(2025, 12), (dt.date(2025, 12, 1), dt.date(2025, 12, 31)))

    def test_month_carries_rates_from_the_month_before(self):
        rows = rows_for("2026-01-30") + rows_for("2026-01-30", {"SEK": Decimal("9.5")})
        rows += [r for r in every_day(2026) if r["date"] >= "2026-02-03"]
        days = json.loads(by.build_month(2026, 2, currency_rows(), rows, NOW)[0], parse_float=Decimal)["days"]

        self.assertEqual(days["2026-02-01"]["SEK"], Decimal("9.5"))
        self.assertEqual(len(days["2026-02-01"]), len(CODES))

    def test_month_is_refused_like_a_year(self):
        codes = [c for c in CODES if c != "EUR"]
        with self.assertRaisesRegex(br.BuildError, "EUR"):
            by.build_month(2026, 3, currency_rows(), every_day(2026, codes=codes), NOW)

    def test_split_year_matches_building_the_month(self):
        rows = every_day(2023) + rows_for("2023-05-17", {"SEK": Decimal("10.123456")})
        year_text, _ = by.build_year(2023, currency_rows(), rows, NOW)
        months = by.split_year(year_text, NOW)

        self.assertEqual(list(months), [f"2023-{m:02d}" for m in range(1, 13)])
        self.assertEqual(months["2023-05"], by.build_month(2023, 5, currency_rows(), rows, NOW)[0])


if __name__ == "__main__":
    unittest.main()
