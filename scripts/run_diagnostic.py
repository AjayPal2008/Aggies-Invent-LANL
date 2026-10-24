"""Run the terminal-only diagnostic. All keys and grading remain in the backend."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.ai_client import redact_secrets
from backend.assessment import Diagnostic, render_report
from backend.question_bank import BANK_PATH, BankError, read_bank, resources


def choose(prompt, options):
    for index, option in enumerate(options, 1):
        print(f"  {index}. {option['text']}")
    while True:
        value = input(prompt + " (1-4; q to stop): ").strip()
        if value.lower() == "q":
            raise EOFError
        if value in ("1", "2", "3", "4"):
            return options[int(value) - 1]["id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, default=BANK_PATH)
    parser.add_argument("--initial-limit", type=int, default=8, help="At most 12; default 8 initial application scenarios")
    parser.add_argument("--budget", type=int, default=12, help="Total scenario budget including foundation/prerequisite probes; default 12")
    args = parser.parse_args()
    try:
        session = Diagnostic(read_bank(args.bank), resources(), initial_limit=args.initial_limit, budget=args.budget)
    except (BankError, OSError, ValueError, KeyError) as exc:
        print(redact_secrets(f"Cannot start diagnostic: {exc}"), file=sys.stderr)
        return 1
    print("Fictional learning diagnostic. No training completion or certified mastery is awarded.")
    print("Each scenario includes a separate reasoning choice and confidence rating; confidence adds no points.")
    print("Explanations appear only after the diagnostic branch ends. q stops and saves incomplete coverage.")
    try:
        while (q := session.next_question()) is not None:
            print(f"\n[{q['article_id']} / {q['level']}] {q['scenario']}\n{q['question']}")
            answer = choose("Answer", q["options"])
            print(q["why"]["question"])
            reason = choose("Reason", q["why"]["options"])
            while True:
                confidence = input("Confidence: 1 guessing / 2 somewhat sure / 3 very sure (q to stop): ").strip()
                if confidence.lower() == "q":
                    raise EOFError
                if confidence in ("1", "2", "3"):
                    break
            outcome = session.submit(q["id"], answer, reason, q["confidence_choices"][int(confidence) - 1])
            if outcome["branch_complete"]:
                print("\nDiagnostic branch finished. Feedback:")
                for feedback in outcome["feedback"]:
                    print(f"{feedback['question_id']}: answer correct={feedback['answer_correct']}; reasoning correct={feedback['reason_correct']}")
                    for key in ("answer_explanations", "reason_explanations"):
                        for option in feedback[key]:
                            print(f"  {option['text']} — {option['explanation']}")
            else:
                print("Continuing this concept with a foundation question; feedback is held until it is finished.")
            session.save()
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. Incomplete coverage remains explicit; unfinished branch explanations withheld.")
    path = session.save()
    print(render_report(session.report()))
    print(f"Saved results: {path}\nReadable report: {path.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
