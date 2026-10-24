"""Smoke test: python scripts/test_ai_client.py [--provider auto|claude|local]."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.ai_client import AIClientError, generate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("auto", "claude", "local"))
    args = parser.parse_args()
    try:
        response = generate("Say hello in 5 words", provider=args.provider)
    except AIClientError as exc:
        # Successful stdout contains only the generated text; errors go to stderr.
        print(str(exc), file=sys.stderr)
        return 1
    print(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
