# UNPSYCHIC29

Historical intraday research project for discovering a statistically repeatable universe of 29 liquid NSE equities.

## Execution model

- `main` contains the stable dispatcher and project documentation.
- `data-acquisition` contains the acquisition and research implementation.
- Default-branch workflows explicitly check out `data-acquisition` for execution.
- Dhan credentials are stored only as GitHub Actions secrets.
- Historical data is never committed to Git.
- Workflow output is delivered as downloadable GitHub Actions artifacts.

## Research objective

Use approximately one year of validated 1-minute NSE equity data to identify stocks with liquid, controlled, sustainable intraday expansion and relatively low gap/opening-chaos and reversal behaviour. The final 29-stock universe is determined by evidence from the dataset rather than by preselecting names.

## Research stages

1. **Infrastructure validation** — completed. Dhan 1-minute acquisition, validation, research metrics and artifact generation passed on the controlled test.
2. **Candidate universe construction** — current stage. Build a broad NIFTY 500 NSE-equity candidate universe and resolve every constituent to a Dhan `NSE_EQ` security ID. NIFTY 500 is a starting universe, not a liquidity verdict; Stage 3 will measure actual intraday liquidity and tradability from the Dhan data.
3. **One-year 1-minute acquisition** — pending Stage 2 gate.
4. **Behavioural fingerprinting**.
5. **Hard elimination filters**.
6. **Ranking and deep candidate pool**.
7. **Out-of-sample validation**.
8. **Final UNPSYCHIC29**.

## Stage 2 principle

The candidate universe is deliberately broad. We use the current NSE NIFTY 500 constituent file as the reproducible starting universe because NIFTY 500 is a broad large/mid/small-cap NSE universe with substantial market representation. We do **not** assume that membership means an intraday stock is liquid or predictable. Those properties must be measured from the 1-minute history.

Stage 2 has a strict integrity gate:

- constituent file must parse correctly
- expected constituent count must be plausible
- only `EQ` series is accepted
- every constituent must resolve to exactly one Dhan NSE equity security ID
- symbols and security IDs must be unique
- output manifest counts must exactly match the resolved universe

## Zero-error gate

No one-year/full-universe acquisition is permitted until the controlled acquisition and candidate-universe gates pass. Any failed validation stops the workflow; no partial result is accepted as a valid research artifact.

## Secrets

Historical acquisition uses the repository secret `DHAN_ACCESS_TOKEN`. Stage 2 candidate-universe construction does not require the Dhan access token because it uses public NSE index constituent data and Dhan's public instrument master.

Never commit secret values to the repository.
