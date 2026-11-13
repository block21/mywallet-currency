"""Tests for build_rates.py. Run with ``python3 -m unittest discover -s scripts``."""

from __future__ import annotations

import datetime as dt
import json
import unittest
from decimal import Decimal

import build_rates as br

NOW = dt.datetime(2026, 11, 13, 16, 30, tzinfo=dt.timezone.utc)

# 120 made-up currencies plus the required ones, so the count check passes;
# digits keep them clear of real codes such as XAU
FILLER = [f"F{i:03d}" for i in range(120)]
CODES = sorted(br.REQUIRED) + FILLER


def currency_rows(codes=CODES, extra=()):
    rows = [{"iso_code": code, "type": "currency"} for code in codes]
    return rows + list(extra)


def rate_rows(rates=None, date="2026-11-13", base="USD"):
    rates = rates if rates is not None else {code: Decimal("2") for code in CODES}
    return [{"date": date, "base": base, "quote": code, "rate": rate} for code, rate in rates.items()]


def default_rates(**overrides):
    rates = {code: Decimal("2") for code in CODES}
    rates.update({code: Decimal(value) for code, value in overrides.items()})
    return rates


class BuildTests(unittest.TestCase):

    def build(self, rates=None, previous=None, force=False, **kwargs):
        rows = rate_rows(rates, **kwargs)
        return br.build(currency_rows(), rows, previous or {}, NOW, force)

    # MARK: - Output

    def test_output_has_the_app_format(self):
        text, warnings = self.build()
        document = json.loads(text)

        self.assertEqual(document["base"], "USD")
        self.assertEqual(document["asOf"], "2026-11-13")
        self.assertEqual(document["generatedAt"], "2026-11-13T16:30:00Z")
        self.assertEqual(len(document["rates"]), len(CODES))
        self.assertEqual(warnings, [])

    def test_rates_are_written_exactly(self):
        rates = default_rates(SEK="9.9598", JPY="154.123456", EUR="0.000000123")
        text, _ = self.build(rates)

        self.assertIn('"SEK": 9.9598', text)
        self.assertIn('"JPY": 154.123456', text)
        self.assertIn('"EUR": 0.000000123', text)  # no exponent
        self.assertEqual(br.read_rates(text)["SEK"], Decimal("9.9598"))

    def test_crypto_metals_and_other_bases_are_left_out(self):
        rows = rate_rows() + [
            {"date": "2026-11-13", "base": "USD", "quote": "BTC", "rate": Decimal("0.00001")},
            {"date": "2026-11-13", "base": "USD", "quote": "XAU", "rate": Decimal("0.0003")},
            {"date": "2026-11-13", "base": "EUR", "quote": "SEK", "rate": Decimal("11")},
        ]
        extra = [{"iso_code": "BTC", "type": "crypto"}, {"iso_code": "XAU", "type": "metal"}]

        text, _ = br.build(currency_rows(extra=extra), rows, {}, NOW)
        rates = br.read_rates(text)

        self.assertNotIn("BTC", rates)
        self.assertNotIn("XAU", rates)
        self.assertEqual(rates["SEK"], Decimal("2"))

    def test_as_of_is_the_newest_date(self):
        rows = rate_rows() + [{"date": "2026-11-12", "base": "USD", "quote": "F000", "rate": Decimal("3")}]
        text, _ = br.build(currency_rows(), rows, {}, NOW)
        self.assertEqual(json.loads(text)["asOf"], "2026-11-13")

    # MARK: - Refusals

    def test_too_few_currencies_is_refused(self):
        rates = {code: Decimal("2") for code in sorted(br.REQUIRED)}
        with self.assertRaisesRegex(br.BuildError, "Only"):
            self.build(rates)

    def test_missing_required_currency_is_refused(self):
        rates = default_rates()
        del rates["SEK"]
        with self.assertRaisesRegex(br.BuildError, "SEK"):
            self.build(rates)

    def test_non_positive_rate_is_refused(self):
        with self.assertRaisesRegex(br.BuildError, "Non-positive"):
            self.build(default_rates(NOK="0"))

    def test_old_data_is_refused(self):
        with self.assertRaisesRegex(br.BuildError, "days old"):
            self.build(date="2026-11-07")

    def test_five_day_old_data_is_accepted(self):
        text, _ = self.build(date="2026-11-08")
        self.assertEqual(json.loads(text)["asOf"], "2026-11-08")

    # MARK: - Movement

    def test_large_move_is_refused(self):
        previous = default_rates()
        with self.assertRaisesRegex(br.BuildError, "SEK 2 -> 3.1"):
            self.build(default_rates(SEK="3.1"), previous)

    def test_move_within_limit_is_accepted(self):
        text, warnings = self.build(default_rates(SEK="2.9"), default_rates())
        self.assertEqual(br.read_rates(text)["SEK"], Decimal("2.9"))
        self.assertEqual(warnings, [])

    def test_force_publishes_a_large_move_with_a_warning(self):
        text, warnings = self.build(default_rates(SEK="3.1"), default_rates(), force=True)
        self.assertEqual(br.read_rates(text)["SEK"], Decimal("3.1"))
        self.assertTrue(any("SEK" in warning for warning in warnings))

    def test_dropped_currency_is_a_warning(self):
        previous = default_rates(OLD="5")
        _, warnings = self.build(default_rates(), previous)
        self.assertIn("No longer published: OLD", warnings)

    def test_first_run_has_no_previous_file(self):
        text, warnings = self.build(previous={})
        self.assertEqual(warnings, [])
        self.assertTrue(text)


if __name__ == "__main__":
    unittest.main()
