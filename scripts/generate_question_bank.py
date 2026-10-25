"""Generate a private, pending-review question bank. Makes live AI calls ONLY when run."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.ai_client import AIClientError, redact_secrets
from backend.question_bank import BANK_PATH, BankError, atomic_json, bank_errors, build_bank, read_bank, resources, review_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, default=BANK_PATH)
    parser.add_argument("--article", help="Article ID, e.g. ionizing-radiation; omit for all extracted topics and Survey & Materials PDFs")
    parser.add_argument("--objectives-per-article", type=int, default=3,
                        help="Scenario objectives per article, plus their prerequisites; all important concepts are mapped")
    args = parser.parse_args()
    if args.objectives_per_article < 1:
        parser.error("--objectives-per-article must be positive")
    try:
        source = resources()
        if args.article and args.article not in source:
            raise BankError("Unknown article ID")
        bank = read_bank(args.bank) if args.bank.exists() else None
        if bank:
            errors = bank_errors(bank, source)
            if errors:
                raise BankError("Existing bank is invalid: " + "; ".join(errors))
        bank = build_bank(source, bank, article_ids=[args.article] if args.article else None,
                          objectives_per_article=args.objectives_per_article,
                          checkpoint=lambda b: atomic_json(args.bank, b))
        errors = bank_errors(bank, source)
        if errors:
            raise BankError("Bank structural errors: " + "; ".join(errors))
        atomic_json(args.bank, bank)
        report = args.bank.with_suffix(".review.md")
        report.write_text(review_report(bank, source), encoding="utf-8")
        print(f"Saved {len(bank['concepts'])} concepts and {len(bank['questions'])} pending/reused scenarios: {args.bank}")
        print(f"Human review report (contains answer keys): {report}")
        print("Structural checks do not establish factual correctness. Only manually approved items can be assessed.")
        return int(bool(bank["generation_errors"]))
    except (AIClientError, BankError, OSError, ValueError, KeyError) as exc:
        print(redact_secrets(f"Bank generation failed: {exc}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
