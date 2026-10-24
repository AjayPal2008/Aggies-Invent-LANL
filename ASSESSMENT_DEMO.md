# Terminal diagnostic demo

This is a learning diagnostic, not certification, a safety authorization, a
workplace procedure, or evidence that required training was completed. No
frontend or network server is implemented. All commands run from the project
root in PowerShell, using Python's standard library.

## 1. Generate a candidate bank

Use the `ANTHROPIC_API_KEY` already set in your terminal. No credential files are
read. This command makes live Claude calls **when you run it**:

```powershell
python scripts/generate_question_bank.py
```

To try just one article first:

```powershell
python scripts/generate_question_bank.py --article ionizing-radiation
```

The default then reusable bank is
`Resource_File/cache/assessment/bank.json`. Re-running the command reuses existing
concept maps and questions; failed objectives can be retried. Checkpoints are
saved after mapping and each scenario set. Questions remain pending until a human
approves them. Claude-only calls use 120 seconds and at most 8,000 output tokens.

Each article is mapped into **multiple concepts**, with specific learning
objectives, source point IDs, excerpts and proposed prerequisite links. The
generator requires mapping every extracted point (including lower-priority points):
**importance 3 = highest**, 2 = middle, 1 = lowest. Concept importance is the
highest importance of its supporting source points. Proposed prerequisite links
are checked for valid IDs, source excerpts, and cycles; their educational and
factual validity still needs human review. `[]` is allowed when the source does
not support a prerequisite link. Cross-article prerequisites are not inferred
automatically in this demo.

By default, generate scenario sets for the top three concepts per article plus
their prerequisites. Other mapped concepts remain explicitly untested. To build
more scenario sets:

```powershell
python scripts/generate_question_bank.py --objectives-per-article 6
```

Per objective, the bank stores three distinct fictional scenarios:

1. `diagnostic`: application question, plus a separate Why? reasoning choice.
2. `follow-up`: foundational principle question, plus reasoning, to distinguish
   a principle gap from an application/reasoning gap.
3. `post-training`: a new application/transfer scenario, plus reasoning, saved
   for later use. It is not included in this diagnostic.

This follows the updated foundation/application/reasoning flow. Reasoning is
measured through the Why? component, not a fourth scenario. The prompt prohibits
invented LANL policies and operational procedures. Cleaned article paragraphs are
supplied alongside extracted JSON for details omitted during extraction.

IDs are derived from persisted concept slugs, role and version, and option IDs
are derived from their question. Resume reuses IDs without regenerating content.
Changed sources require a new bank path (for example `--bank
Resource_File/cache/assessment/bank-v2.json`) and new review. No automated
equivalence between independently regenerated concept maps is claimed.

## 2. Review and manually approve

```powershell
python scripts/review_question_bank.py --list
```

Read `Resource_File/cache/assessment/bank.review.md`. It contains each concept,
objective, priority, prerequisite rationale/evidence, scenario, source excerpt,
every answer and reasoning explanation, answer keys, and attribution.

**Structural validation is not factual validation.** The validator checks shape,
IDs, option uniqueness, answer-key references, source-point existence, excerpt
occurrence, scenario duplication, prerequisite cycles, and source fingerprints.
An excerpt occurring in a source does not prove it entails an answer or justifies
a prerequisite. A human must verify the correct choice and distractors, assess
scenario distinctness and resource fidelity, and reject misleading or unsupported
content. Extracted summaries can themselves contain oversimplifications; consult
the cleaned article before approval. A rejected item is never used.

To review question-by-question without copying IDs:

```powershell
python scripts/review_question_bank.py --interactive
```

Enter your reviewer name, read the displayed item, then type `APPROVE`, `REJECT`,
`SKIP` or `QUIT`. Every approval is an explicit human decision. Approve the
diagnostic AND foundation questions for the objectives you intend to assess.
Post-training questions may stay pending until needed.

Alternatively, copy an exact objective ID from the report and replace
`OBJECTIVE_ID_FROM_REPORT` and the reviewer name below to approve its three
scenarios after reviewing them:

```powershell
python scripts/review_question_bank.py --objective OBJECTIVE_ID_FROM_REPORT --status approved --reviewer "Your name" --confirm-reviewed
```

Use `--question QUESTION_ID_FROM_REPORT` instead of `--objective` for one item,
or `--status rejected` to reject it. Editing question content, concept maps or
prerequisites invalidates prior approval digests; source changes block use until
regeneration/review. Generate the desired articles before approving, since adding
concepts changes the map digest. These are local demo review records, not an
authenticated enterprise approval service.

## 3. Run the terminal diagnostic

No AI calls occur during assessment:

```powershell
python scripts/run_diagnostic.py --initial-limit 8 --budget 12
```

For up to 12 initial scenarios with extra room for follow-ups:

```powershell
python scripts/run_diagnostic.py --initial-limit 12 --budget 20
```

One budget item is a scenario together with its answer, reasoning choice and
confidence rating. The initial limit is capped at 12; total budget is capped at
24. Initial selection round-robins available approved questions across articles,
then prioritizes importance within each article. If fewer than four slots or
fewer than four articles have approved scenarios, full topic coverage is not
possible and the result reports that explicitly. Reserved initial slots prevent
early follow-ups from consuming other topics' planned coverage.

Answers and reasoning are graded separately and deterministically. Confidence
(`guessing`, `somewhat sure`, `very sure`) is recorded but adds no points. A
correct pair is positive evidence, with foundational knowledge still untested.
If either choice is wrong, one different, approved foundation question is used
for that objective when budget allows. If no approved foundation question or no
budget is available, the gap remains inconclusive. Relevant prerequisite
foundations are probed with remaining budget after the initial plan, without
repeating already tested concepts or question IDs. There is at most one
foundation follow-up per initially tested concept.

No answer explanations are released before the diagnostic branch ends. Stopping
with `q` saves incomplete results and withholds feedback for an unfinished branch.
Question payloads contain no answer keys, source excerpts, or explanations.
Bank files, review reports, grading and result persistence belong to the private
backend/admin side; never expose them as frontend static assets.

## 4. Interpret the saved report

Results are saved after each submitted scenario and on exit:

- `Resource_File/cache/assessment/results/<session-id>.json`
- `Resource_File/cache/assessment/results/<session-id>.md`

The report gives article coverage and concept-by-concept foundation, application,
and reasoning evidence; observed gaps; priority-sorted targeted resource review;
and what remains untested. Statuses are `evidence of understanding`, `needs
review`, `insufficient evidence`, or `not assessed` for untouched objectives.
Foundation-only prerequisite probes do not establish application understanding.
An unfinished branch is explicitly uncertain. There is no certified mastery
claim or training-completion update. Resource `required` flags appear separately
as obligations whose completion is **not evaluated by the diagnostic**.

Persistence uses the project's existing local JSON/cache convention rather than
adding a database. Results survive process exit; resuming a stopped session is
not implemented. Starting again creates a new session; non-repetition is
guaranteed within each session, not across independent sessions.

## 5. Offline tests

```powershell
python -m unittest scripts.test_assessment scripts.test_ai_client_offline scripts.test_knowledge_pipeline -v
```

AI generation is mocked; synthetic scenarios are not approved real training
content. No credential files or live APIs are used. No actual bank has been
generated or manually approved as part of implementation.
