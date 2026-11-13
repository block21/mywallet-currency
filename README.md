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

## The workflow

`.github/workflows/publish-rates.yml` runs every day at 16:30 UTC, when you
start it by hand, and when the script or workflow changes on `main`. It runs
`scripts/build_rates.py` (Python standard library only), commits `public/`,
and deploys `public/` to Pages.

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
