from __future__ import annotations

import os
import sys

import requests

PROFILE_URL = "https://api.dhan.co/v2/profile"


def main() -> None:
    token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DHAN_ACCESS_TOKEN secret is missing.")

    response = requests.get(
        PROFILE_URL,
        headers={"Accept": "application/json", "access-token": token},
        timeout=30,
    )

    if response.status_code != 200:
        try:
            body = response.json()
        except ValueError:
            body = response.text[:500]
        raise RuntimeError(
            f"Dhan authentication/profile check failed: HTTP {response.status_code}. "
            f"Response: {body}"
        )

    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Dhan profile returned an unexpected response shape.")

    token_validity = body.get("tokenValidity", "unknown")
    data_plan = body.get("dataPlan", "unknown")
    data_validity = body.get("dataValidity", "unknown")

    print("Dhan preflight: PASS")
    print(f"Token validity: {token_validity}")
    print(f"Data API plan: {data_plan}")
    print(f"Data validity: {data_validity}")

    if str(data_plan).lower() not in {"active", "true", "1"}:
        raise RuntimeError(
            "Dhan profile is reachable, but Data API access is not reported as active. "
            "Historical candle calls require Data API access."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Dhan preflight: FAIL — {exc}", file=sys.stderr)
        raise
