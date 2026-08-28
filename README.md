# UNPSYCHIC29

Historical intraday research engine for discovering a research-backed universe of 29 liquid NSE stocks with clean, repeatable intraday behaviour.

## Objective

Research approximately one year of 1-minute NSE equity data and rank stocks on:

- liquidity and tradability
- gap stability
- opening-range stability
- opening shock / first-10-minute behaviour
- sustainable expansion
- directional continuation
- reversal / whipsaw resistance
- intraday opportunity frequency
- consistency across market regimes

The final 29 are **discovered from data**. They are not hard-coded in advance.

## Architecture

```text
Dhan Historical Data API
        |
        v
GitHub Actions
        |
        v
1-minute OHLCV downloader
        |
        v
Parquet research dataset
        |
        v
Feature + scoring engine
        |
        v
Top candidates -> final 29
        |
        v
GitHub Actions artifact
```

No Render service and no Postgres database are required for the batch research workflow.

## Secrets

GitHub repository secrets used by the workflow:

- `DHAN_ACCESS_TOKEN` — required for Dhan Historical Data API calls.
- `DHAN_CLIENT_ID` — stored for future Dhan integrations; historical candle calls currently authenticate with the access token.
- `DHAN_PIN` — stored only because it already exists in the repository; the research downloader does not use or print it.

**Never commit secret values to the repository.**

## Current phase

Phase 1 is deliberately small: validate Dhan access, retrieve the instrument master, select a tiny test universe, download 1-minute historical candles in manageable date chunks, validate the data, and publish a downloadable artifact.

Only after this passes will the workflow be expanded to the full NSE candidate universe and one-year research run.

## Data source

DhanHQ v2 Intraday Historical Data provides 1, 5, 15, 25 and 60 minute OHLC/OI/volume data, with intraday history currently available for up to five years. The project uses the 1-minute interval for the research dataset.

## Repository layout

```text
.github/workflows/       GitHub Actions workflows
config/                  Research configuration
src/                     Downloader and validation code
artifacts/               Local output location (ignored by Git)
```

## Important research principle

The engine is designed to avoid selecting stocks merely because they move a lot. The target behaviour is controlled, liquid, repeatable expansion with relatively low opening chaos and lower immediate-reversal frequency.
