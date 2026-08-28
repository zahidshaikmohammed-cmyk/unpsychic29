# UNPSYCHIC29

Historical intraday research project for discovering a statistically repeatable universe of 29 liquid NSE equities.

## Execution model

- `main` contains stable dispatchers and project documentation.
- `data-acquisition` contains the acquisition and research implementation.
- Default-branch workflows explicitly check out `data-acquisition` for execution.
- Dhan credentials are stored only as GitHub Actions secrets.
- Historical 1-minute candles are processed in memory during Stage 3 and are never committed to Git.
- Compact research outputs are delivered as downloadable GitHub Actions artifacts.

## Research objective

Use approximately one year of validated 1-minute NSE equity data to identify stocks with liquid, controlled, sustainable intraday expansion and relatively low gap/opening-chaos and reversal behaviour. The final 29-stock universe is determined by evidence from the dataset rather than by preselecting names.

## Research stages

1. **Infrastructure validation** — completed. Dhan 1-minute acquisition, validation, research metrics and artifact generation passed on the controlled test.
2. **Candidate universe construction** — completed. The current NIFTY 500 NSE-equity universe was resolved one-to-one against Dhan `NSE_EQ` Security IDs.
3. **One-year 1-minute acquisition + compact feature extraction** — implemented. The 500-stock universe is processed in deterministic 50-stock batches. Each batch acquires approximately one year of 1-minute OHLCV, strictly validates it, extracts daily behavioural features, and retains only compact research outputs. Raw 1-minute candles are not uploaded because GitHub Free Actions artifact storage is limited to 500 MB; raw minute data can be reacquired for finalists in later stages.
4. **Behavioural fingerprinting**.
5. **Hard elimination filters**.
6. **Ranking and deep candidate pool**.
7. **Out-of-sample validation**.
8. **Final UNPSYCHIC29**.

## Stage 3 architecture

Stage 3 uses `UNPSYCHIC29 Stage 3 - One-Year 1-Min Acquisition` from `main`, while checking out the implementation from `data-acquisition`.

- Default batch size: 50 stocks
- Default number of batches for a 500-stock universe: 10
- Default lookback: 365 calendar days
- Default Dhan request chunk: 30 calendar days
- 1-minute OHLCV is acquired and validated before daily features are accepted
- Each symbol must have no duplicate timestamps, invalid OHLC relationships, null volume, or out-of-session candles
- A symbol with a shorter available history is retained with its measured trading-day count; later research stages decide whether it has enough history for statistical qualification
- No raw historical candles are committed to Git or retained as a large Actions artifact
- Each batch produces a compact artifact containing the batch universe, validation report, chunk log, daily features, and manifest

This batching separates acquisition from compact research retention so the project remains compatible with the free GitHub Actions storage allowance.

## Stage 2 principle

The candidate universe is deliberately broad. We use the current NSE NIFTY 500 constituent file as the reproducible starting universe. NIFTY 500 membership is **not** treated as a liquidity or predictability verdict. Those properties are measured from 1-minute history in later stages.

Stage 2 has a strict integrity gate:

- constituent file must parse correctly
- expected constituent count must be plausible
- only `EQ` series is accepted
- every constituent must resolve to exactly one Dhan NSE equity Security ID
- symbols and Security IDs must be unique
- output manifest counts must exactly match the resolved universe

## Zero-error gate

No production batch is accepted unless runner, dependency, deterministic-test, universe, Dhan-access, candle-integrity, timestamp/session, feature-coverage, and artifact-integrity gates pass. A failed validation is never silently converted into a usable research result.

## Secrets

Historical acquisition uses the repository secret `DHAN_ACCESS_TOKEN`. Stage 2 candidate-universe construction does not require the Dhan access token because it uses public NSE constituent data and Dhan's public instrument master.

Never commit secret values to the repository.
