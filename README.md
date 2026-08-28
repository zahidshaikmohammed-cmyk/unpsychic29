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
NSE NIFTY 500 constituent universe
        |
        v
Dhan instrument master -> Security IDs
        |
        v
1-minute historical acquisition
        |
        v
Validation + Parquet dataset
        |
        v
Feature engine
        |
        v
Elimination -> ranking -> out-of-sample validation
        |
        v
Final UNPSYCHIC29
        |
        v
GitHub Actions artifact
```

No Render service and no Postgres database are required for the batch research workflow.

## Stages

1. Infrastructure validation — **PASS**
2. Candidate universe construction — **CURRENT**
3. One-year 1-minute acquisition
4. Behavioural fingerprinting
5. Hard elimination
6. Ranking/deep candidate pool
7. Out-of-sample validation
8. Final UNPSYCHIC29

## Stage 2

Stage 2 uses the current NSE NIFTY 500 constituent CSV as the broad candidate starting universe. It then resolves every constituent against Dhan's public instrument master and requires a one-to-one `NSE_EQ` / `EQUITY` Security ID mapping.

NIFTY 500 membership is **not** treated as proof of intraday liquidity or predictability. Stage 3 measures actual intraday behaviour from Dhan's 1-minute data.

The Stage 2 gate rejects the run if the source cannot be parsed, the constituent count is implausible, any symbol cannot be resolved, or symbols/security IDs are duplicated.

## Secrets

Historical acquisition uses `DHAN_ACCESS_TOKEN`. Stage 2 does not require a Dhan authentication secret.

Never commit secret values to the repository.
