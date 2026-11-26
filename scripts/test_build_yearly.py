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


class RunningMonthTests(unittest.TestCase):

    def test_running_month_stops_at_the_day_given(self):
        text, _ = by.build_month(2026, 11, currency_rows(), every_day(2026), NOW, dt.date(2026, 11, 21))
        document = json.loads(text)

        self.assertEqual(document["month"], "2026-11")
        self.assertEqual(list(document["days"])[0], "2026-11-01")
        self.assertEqual(list(document["days"])[-1], "2026-11-21")
        self.assertEqual(len(document["days"]), 21)

    def test_a_day_past_the_month_ends_it_on_its_last_day(self):
        text, _ = by.build_month(2026, 10, currency_rows(), every_day(2026), NOW, dt.date(2026, 11, 21))

        self.assertEqual(list(json.loads(text)["days"])[-1], "2026-10-31")

    def test_running_month_has_the_same_days_as_the_finished_one(self):
        rows = every_day(2026) + rows_for("2026-11-10", {"SEK": Decimal("9.8765")})
        running = json.loads(by.build_month(2026, 11, currency_rows(), rows, NOW, dt.date(2026, 11, 21))[0])["days"]
        finished = json.loads(by.build_month(2026, 11, currency_rows(), rows, NOW)[0])["days"]

        self.assertEqual(running, {day: finished[day] for day in running})

    def test_months_of_the_year_up_to_yesterday(self):
        months = by.current_year_months(dt.date(2026, 11, 22))

        self.assertEqual(len(months), 11)
        self.assertEqual(months[0], (1, dt.date(2026, 1, 31)))
        self.assertEqual(months[9], (10, dt.date(2026, 10, 31)))
        self.assertEqual(months[10], (11, dt.date(2026, 11, 21)))

    def test_the_first_of_a_month_has_no_running_month(self):
        months = by.current_year_months(dt.date(2026, 12, 1))

        self.assertEqual([month for month, _ in months], list(range(1, 12)))
        self.assertEqual(months[-1], (11, dt.date(2026, 11, 30)))

    def test_the_last_day_of_a_month_leaves_it_running(self):
        self.assertEqual(by.current_year_months(dt.date(2026, 11, 30))[-1], (11, dt.date(2026, 11, 29)))

    def test_new_years_day_has_no_month_of_the_new_year(self):
        self.assertEqual(by.current_year_months(dt.date(2027, 1, 1)), [])

    def test_reaches_tells_a_running_month_from_a_finished_one(self):
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "2026-11.json"
            self.assertFalse(by.reaches(path, dt.date(2026, 11, 21)))

            path.write_text(by.build_month(2026, 11, currency_rows(), every_day(2026), NOW, dt.date(2026, 11, 21))[0])

            self.assertTrue(by.reaches(path, dt.date(2026, 11, 21)))
            self.assertFalse(by.reaches(path, dt.date(2026, 11, 22)))
            self.assertFalse(by.reaches(path, dt.date(2026, 11, 30)))


class YearFromMonthsTests(unittest.TestCase):

    def months_of(self, year, rows):
        return [by.build_month(year, month, currency_rows(), rows, NOW)[0] for month in range(1, 13)]

    def test_year_joined_from_its_months_matches_building_the_year(self):
        rows = every_day(2023) + rows_for("2023-05-17", {"SEK": Decimal("10.123456")})

        joined = by.join_months(2023, self.months_of(2023, rows), NOW)

        self.assertEqual(joined, by.build_year(2023, currency_rows(), rows, NOW)[0])

    def test_joined_year_holds_the_months_days_exactly(self):
        months = self.months_of(2024, every_day(2024))
        months[4] = months[4].replace('"SEK": 2', '"SEK": 9.87654321', 1)

        days = json.loads(by.join_months(2024, months, NOW), parse_float=Decimal)["days"]

        self.assertEqual(len(days), 366)
        self.assertEqual(days["2024-05-01"]["SEK"], Decimal("9.87654321"))

    def test_a_year_missing_days_is_refused(self):
        months = self.months_of(2023, every_day(2023))
        cut_short = by.build_month(2023, 12, currency_rows(), every_day(2023), NOW, dt.date(2023, 12, 30))[0]

        with self.assertRaisesRegex(br.BuildError, "2023-12-31"):
            by.join_months(2023, months[:11] + [cut_short], NOW)
        with self.assertRaisesRegex(br.BuildError, "2023-06-01"):
            by.join_months(2023, months[:5] + months[6:], NOW)


class RunTests(unittest.TestCase):
    """The whole run on a folder, with Frankfurter answered from memory."""

    def setUp(self):
        import pathlib
        import tempfile

        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.out = pathlib.Path(self.folder.name)
        self.requests = []
        self.rates = {}  # date -> SEK rate, where it is not 2
        self.real_fetch = by.fetch
        by.fetch = self.fetch
        self.addCleanup(lambda: setattr(by, "fetch", self.real_fetch))

    def fetch(self, path):
        self.requests.append(path)
        if path == "/currencies":
            return currency_rows()
        start, end = path.split("from=")[1].split("&to=")
        rows, day = [], dt.date.fromisoformat(start)
        while day <= dt.date.fromisoformat(end):
            rows += rows_for(day.isoformat())
            if day.isoformat() in self.rates:
                rows += rows_for(day.isoformat(), {"SEK": self.rates[day.isoformat()]})
            day += dt.timedelta(days=1)
        return rows

    def run_on(self, day, hour=17):
        import contextlib
        import io

        now = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(hour), dt.timezone.utc)
        with contextlib.redirect_stdout(io.StringIO()):
            by.main([str(self.out), "--from", str(now.year - 1)], now)

    def files(self):
        return {path.relative_to(self.out).as_posix(): path.read_text() for path in sorted(self.out.rglob("*.json"))}

    def last_day(self, name):
        return list(json.loads((self.out / name).read_text())["days"])[-1]

    def test_running_month_grows_by_a_day_and_is_completed_after_it_ends(self):
        self.run_on("2026-01-01")  # builds 2025 whole, the history before these runs
        self.run_on("2026-03-30")
        self.assertEqual(self.last_day("months/2026-03.json"), "2026-03-29")
        self.assertEqual(self.last_day("months/2026-02.json"), "2026-02-28")

        self.run_on("2026-03-31")
        self.assertEqual(self.last_day("months/2026-03.json"), "2026-03-30")

        self.run_on("2026-04-01")
        self.assertEqual(self.last_day("months/2026-03.json"), "2026-03-31")
        self.assertNotIn("months/2026-04.json", self.files())

        self.run_on("2026-04-02")
        self.assertEqual(self.last_day("months/2026-04.json"), "2026-04-01")

    def test_a_completed_month_is_never_written_again(self):
        self.run_on("2026-01-01")
        self.run_on("2026-04-02")
        march = self.files()["months/2026-03.json"]

        # Frankfurter now answers another rate for a day in March
        self.rates["2026-03-10"] = Decimal("9.99")
        self.run_on("2026-04-03")
        self.run_on("2026-05-02")

        self.assertEqual(self.files()["months/2026-03.json"], march)

    def test_new_year_joins_the_year_from_its_months_and_leaves_them_alone(self):
        self.run_on("2026-01-01")
        for month in range(2, 13):
            self.run_on(f"2026-{month:02d}-01")
        self.run_on("2026-12-31")
        before = self.files()
        self.assertEqual(self.last_day("months/2026-12.json"), "2026-12-30")

        # Frankfurter now answers another rate for a day in June
        self.rates["2026-06-10"] = Decimal("9.99")
        self.requests.clear()
        self.run_on("2027-01-01")
        after = self.files()

        # January to November are untouched; December is completed
        for month in range(1, 12):
            name = f"months/2026-{month:02d}.json"
            self.assertEqual(after[name], before[name])
        self.assertEqual(self.last_day("months/2026-12.json"), "2026-12-31")
        # The year holds exactly its months' days, not what is fetched now
        year = json.loads(after["years/2026.json"], parse_float=Decimal)["days"]
        self.assertEqual(len(year), 365)
        self.assertEqual(year["2026-06-10"]["SEK"], Decimal("2"))
        for month in range(1, 13):
            days = json.loads(after[f"months/2026-{month:02d}.json"], parse_float=Decimal)["days"]
            self.assertEqual({day: year[day] for day in days}, days)
        # Only December was asked of Frankfurter
        self.assertEqual([r for r in self.requests if "from=" in r], ["/rates?base=USD&from=2026-11-17&to=2026-12-31"])
        self.assertNotIn("months/2027-01.json", after)

    def test_a_year_with_no_month_files_is_fetched_whole_and_cut_into_months(self):
        self.run_on("2026-01-01")
        files = self.files()

        self.assertEqual(self.last_day("years/2025.json"), "2025-12-31")
        self.assertEqual(len([name for name in files if name.startswith("months/2025-")]), 12)
        self.assertEqual(len([r for r in self.requests if "from=" in r]), 1)

    def test_running_again_the_same_day_writes_nothing(self):
        self.run_on("2026-01-01")
        self.run_on("2026-03-30")
        before = self.files()
        self.requests.clear()

        self.run_on("2026-03-30")

        self.assertEqual(self.files(), before)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
