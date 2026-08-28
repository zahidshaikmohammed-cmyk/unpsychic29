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
Access preflight + deterministic self-test
        |
        v
1-minute OHLCV downloader
        |
        v
Validation + Parquet dataset
        |
        v
Feature engine
        |
        v
Top candidates -> final 29
        |
        v
GitHub Actions artifact
```

No Render service and no Postgres database are required for the batch research workflow.

## Secrets

The workflow uses one repository secret:

- `DHAN_ACCESS_TOKEN` — required for Dhan profile and historical-data API calls.

`DHAN_CLIENT_ID` and `DHAN_PIN` may exist in the repository because they were previously added, but this historical downloader does not need or print them.

**Never commit secret values to the repository.**

Dhan documents access tokens as short-lived (24 hours for the current individual-token flow), so a fresh token may be required before a manual run.

## Zero-failure execution gate

Before any historical request is made, the workflow verifies:

1. required repository files exist
2. Python source compiles
3. downloader deterministic self-test passes
4. Dhan access token is present
5. Dhan profile accepts the token
6. Dhan Data API plan is active

The downloader then validates the returned datasets for duplicate timestamps, OHLC integrity, session boundaries, and volume completeness. Any failed validation stops the run; no partial research result is accepted as valid.

## Current phase

Phase 1 is deliberately small: validate Dhan access, retrieve the instrument master, select a tiny test universe, download 1-minute historical candles in manageable date chunks, validate the data, calculate descriptive behaviour metrics, and publish a downloadable artifact.

Only after this passes will the workflow be expanded to the broad NSE candidate universe and one-year research run.

## Data source

DhanHQ v2 Intraday Historical Data currently provides 1, 5, 15, 25 and 60 minute OHLC/volume data, with intraday history available for up to five years. The project uses the 1-minute interval for the research dataset.

## Repository layout

```text
.github/workflows/       GitHub Actions workflows
config/                  Research configuration
src/                     Downloader and research engine
artifacts/               Local output location (ignored by Git)
```

## Important research principle

The engine is designed to avoid selecting stocks merely because they move a lot. The target behaviour is controlled, liquid, repeatable expansion with relatively low opening chaos and lower immediate-reversal frequency.
