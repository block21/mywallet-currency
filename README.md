# mywallet-currency

Daily fallback exchange rates for the MyWallet app, published with GitHub Pages.

The app gets its rates from [Frankfurter](https://frankfurter.dev) directly.
This repo is its fallback for when Frankfurter can't be reached. Once a day,
a GitHub Action takes Frankfurter's blended rates, writes them in the format
the app reads, commits them here and publishes them.

## Files

| URL | Contents |
|---|---|
| `https://currency.block21.com/latest.json` | The newest rates |
| `https://currency.block21.com/history/YYYY-MM-DD.json` | The rates published on that UTC day |
| `https://currency.block21.com/years/YYYY.json` | Daily rates for every day of a finished year (2010 onwards) |
| `https://currency.block21.com/months/YYYY-MM.json` | Daily rates for every day of a month (2010-01 onwards); the running month up to yesterday |

```json
{
  "base": "USD",
  "asOf": "2026-11-13",
  "generatedAt": "2026-11-13T16:31:02Z",
  "source": "Frankfurter (frankfurter.dev), blended central bank reference rates",
  "rates": { "EUR": 0.8626, "SEK": 9.9598, "...": 0 }
}
```

- `rates`: units of each currency per one `base`. Cross rates are derived
  through the base.
- `asOf`: the date of the newest rate in the file.
- Only ISO 4217 currencies are included; crypto and metals are left out.
- The format matches the app's bundled `DefaultExchangeRates.json`, so
  `latest.json` can also be copied over that file before each release.

## Yearly and monthly files

`years/YYYY.json` holds a whole year of daily rates, keyed by date, and
`months/YYYY-MM.json` holds one month of them:

```json
{
  "base": "USD",
  "year": 2010,
  "generatedAt": "2026-11-22T09:11:29Z",
  "source": "Frankfurter (frankfurter.dev), blended central bank reference rates",
  "days": {
    "2010-01-01": { "EUR": 0.69546, "SEK": 7.1646, "...": 0 },
    "...": {}
  }
}
```

A month file has `"month": "2010-01"` in place of `"year"`.

- Every calendar day is present. On weekends and holidays, a currency
  carries the last rate published before that day.
- A currency appears from its first published rate onwards (SLE from
  mid-2022, for example).
- The currencies are the same as in `latest.json`. Retired codes Frankfurter
  no longer lists (EEK, HRK, BGN, BYR...) are left out.
- Years up to last year have a file, and every month up to the running
  one.
- The running month's file holds the 1st up to yesterday and is built
  again every day, a day longer each time. A day is only written once it
  is over, so its rates are the same in every file that holds it. The file
  is complete when it reaches the month's last day, which the first run of
  the next month makes it. On the 1st the new month has no file yet.

`scripts/build_yearly.py` builds both, and only builds files that are
missing or not yet complete. A complete file is never written again, since
the app fetches a finished month or year once and keeps it:

- A month of the current year is fetched on its own, the running month
  every day.
- When a year ends, its year file is put together from the twelve month
  files published during the year, once December has been completed. The
  months are left as they are, and the year holds exactly their days.
- A year with no month files at all (the history before this repo) is
  fetched whole and its month files cut from it.
- `--rebuild` is the one way to write complete files again, by hand.

The daily workflow runs the script every day. Most days it only builds the
running month again. The first run of a month completes the month that just
ended, and the 1 January run also puts the year together from its months. If a run fails, the next day's run tries
again, and the day's rates are published either way.

To build or rebuild files by hand:

```sh
python3 scripts/build_yearly.py public                                # whatever is missing
python3 scripts/build_yearly.py public --from 2024 --to 2024 --rebuild # 2024 and its months again
```

A day with too few currencies, a required currency missing or a
non-positive rate stops that file from being written. Moves above 50% from
one day to the next are only warnings, because history has real ones
(Venezuela's redenominations, Egypt in 2016, Argentina in 2023).

## The workflow

`.github/workflows/publish-rates.yml` runs every day at 16:30 UTC, when you
start it by hand, and when the script or workflow changes on `main`. It runs
`scripts/build_rates.py` (Python standard library only), builds any finished
month or year that has no file yet (see
[Yearly and monthly files](#yearly-and-monthly-files)),
commits `public/`, and deploys `public/` to Pages.

If the data looks wrong, the script stops and nothing is published, so the
last good files stay online. It stops when:

- there are fewer than 100 currencies, or one of the app's main currencies is missing
- any rate is zero or negative
- the newest rate is more than 5 days old
- any currency moved more than 50% since the previous `latest.json`

If a large move is real (a devaluation, say), run the workflow by hand with
**force** checked.

Each run first tests the script (`scripts/test_build_rates.py`), and a
failing test stops the run before anything is published.

Run it locally with:

```sh
python3 -m unittest discover -s scripts
python3 scripts/build_rates.py public
```

## Setup

Under **Settings → Pages**, set **Source** to **GitHub Actions**.

The site is served at `currency.block21.com`:

- DNS (Loopia): a CNAME `currency.block21.com` → `block21.github.io`, and the
  TXT record `_github-pages-challenge-block21.currency.block21.com` that
  verifies the domain for the block21 organisation
- **Settings → Pages**: custom domain `currency.block21.com`, **Enforce HTTPS** on

The old `block21.github.io/mywallet-currency/` address redirects to it. Since the
workflow deploys an artifact, no `CNAME` file is needed in `public/`.

## Licence of the data

Frankfurter's blended rates are free for commercial use. See
[frankfurter.dev](https://frankfurter.dev).
