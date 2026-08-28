# UNPSYCHIC29

Historical intraday research project for discovering a statistically repeatable universe of liquid NSE equities.

## Execution model

- `main` contains the stable dispatcher and project documentation.
- `data-acquisition` contains the acquisition/research implementation.
- The default-branch workflow runs the code from `data-acquisition` explicitly.
- Dhan credentials are stored only as GitHub Actions secrets.
- Historical data is never committed to Git.
- Workflow output is delivered as a downloadable GitHub Actions artifact.

## Research objective

Use approximately one year of validated 1-minute NSE equity data to identify stocks with liquid, controlled, sustainable intraday expansion and relatively low gap/opening-chaos and reversal behaviour. The final 29-stock universe is determined by evidence from the dataset rather than by preselecting names.

## Zero-error gate

No full-universe acquisition is permitted until the controlled acquisition run passes runner, dependency, unit-test, Dhan authentication, instrument resolution, candle integrity, timestamp/session, and artifact-integrity checks.
