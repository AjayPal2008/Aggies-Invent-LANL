"""Inspect a bank or explicitly record a human review decision. No AI calls."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.ai_client import redact_secrets
from backend.question_bank import BANK_PATH, BankError, approved, atomic_json, bank_errors, read_bank, resources, review_question, review_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, default=BANK_PATH)
    parser.add_argument("--list", action="store_true", help="List question IDs and review status")
    parser.add_argument("--interactive", action="store_true", help="Read each pending question and enter an explicit human decision")
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument("--question", help="Review one exact question ID")
    targets.add_argument("--objective", help="Review the three scenarios for one exact objective ID")
    parser.add_argument("--status", choices=("approved", "rejected"))
    parser.add_argument("--reviewer")
    parser.add_argument("--note", default="")
    parser.add_argument("--confirm-reviewed", action="store_true", help="Human confirms reviewing facts, keys, distractors, sources, prerequisites and scenario distinctness")
    args = parser.parse_args()
    try:
        bank, source = read_bank(args.bank), resources()
        errors = bank_errors(bank, source)
        if errors:
            raise BankError("Structural checks failed: " + "; ".join(errors))
        target = args.question or args.objective
        if args.interactive and (target or args.status or args.confirm_reviewed):
            parser.error("Use --interactive separately from explicit decision flags")
        if args.interactive:
            reviewer = args.reviewer or input("Human reviewer name: ").strip()
            if not reviewer.strip():
                raise BankError("A human reviewer name is required")
            print("Approval confirms source-supported facts, correct keys/distractors, fictional scenarios, distinct roles, and relevant prerequisites.")
            for q in bank["questions"]:
                if approved(bank, q) or q["review"]["status"] == "rejected":
                    continue
                print(review_report(bank, source, question_id=q["id"]))
                while True:
                    decision = input("Type APPROVE, REJECT, SKIP or QUIT: ").strip()
                    if decision in ("APPROVE", "REJECT", "SKIP", "QUIT"):
                        break
                if decision == "QUIT":
                    break
                if decision in ("APPROVE", "REJECT"):
                    note = input("Review note (optional): ").strip()
                    review_question(bank, q["id"], "approved" if decision == "APPROVE" else "rejected", reviewer, note)
                    atomic_json(args.bank, bank)
        elif args.status or target or args.reviewer or args.confirm_reviewed:
            if not (target and args.status and args.reviewer and args.confirm_reviewed):
                parser.error("Decisions require --question or --objective, --status, --reviewer and --confirm-reviewed")
            questions = [q for q in bank["questions"] if q["id"] == args.question or q["objective_id"] == args.objective]
            if not questions:
                raise BankError("No questions match the requested review target")
            for q in questions:
                review_question(bank, q["id"], args.status, args.reviewer, args.note)
            atomic_json(args.bank, bank)
            print(f"Recorded {args.status} for {len(questions)} question(s).")
        if args.list:
            for q in bank["questions"]:
                print(f"{q['id']} | {q['review']['status']} | usable approval={approved(bank, q)}")
        report = args.bank.with_suffix(".review.md")
        report.write_text(review_report(bank, source), encoding="utf-8")
        print(f"Review report (private, includes answer keys): {report}")
        print("Structural checks passed; factual correctness still requires human review.")
        return 0
    except (BankError, OSError, ValueError, KeyError, EOFError, KeyboardInterrupt) as exc:
        print(redact_secrets(f"Review failed: {exc}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
