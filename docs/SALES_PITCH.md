# LANL Learn: what we'd highlight in a pitch to Los Alamos

**One line:** LANL Learn turns every training LANL already requires, and the documents behind it, into a personal
learning path for each employee, and gives managers one place to assign, track and prove readiness, from a new
hire's first day to an internal promotion.

**Walkthrough video:** [docs/demo/LANL-Learn-demo.mp4](demo/LANL-Learn-demo.mp4) (sign-in through every page).

---

## 1. The right training for the right person, automatically

- **Three layers, the way UTrain already works.** Institutional training everyone completes, division training for
  Weapons, Science, Technology & Engineering, and Operations, and role training (technical and soft skills).
- **New hire vs. promotion vs. transfer.** A new hire to a Weapons Project Lead role gets 21 trainings; someone
  promoted within Weapons gets only the 6 role trainings; someone moving in from STE gets the division and role
  trainings. Institutional training never repeats; it continues on its annual cycle.
- **Role directory.** A manager opens the role they hired someone into and gets the job description, required
  skills, and a clean checklist of every training, grouped by layer with due dates. Assign it to one or many people
  in one click, copy it, or print it.
- **Annual refresher cycle.** Assigns yearly security, ethics and safety refreshers to everyone, staggered so
  20,000 people aren't all due the same week.

## 2. Lessons built from LANL's own documents

- **Every course has real source material.** 74 library courses backed by 84 documents: LANL White Rock Training
  Center manuals, the LANL Code of Conduct, DOE orders and handbooks, and the federal regulations behind them.
- **Long PDFs become short, interactive lessons.** A 200-page manual becomes modules with summaries, key points and
  page references, so nobody has to read the whole document.
- **Admin library.** Admins add, rename, replace, re-download or delete each PDF or slide deck; files shared by the
  team in one folder appear for everyone.
- **Review before publish.** AI-built lessons stay drafts until a training owner checks them against the source pages
  and publishes, so nothing reaches employees unreviewed.

## 3. A learning experience that adapts to each person

- **Adapts to what works, not to a label.** The platform tracks mastery of each skill (Bayesian knowledge tracing) and
  learns which formats (text, video-style lessons, mind maps, audio) actually work for each person, rather than
  relying on self-reported learning styles, which research doesn't support.
- **Video-style lessons with captions and transcripts**, an AI tutor to ask questions, practice questions, and
  lessons tailored to the person's role, experience and level.
- **Right assessment for the material.** Multiple-choice quizzes for policies and procedures; CASPer-style
  situational interviews (spoken or typed, timed or untimed) for leadership and judgment, scored 1–9 against a
  rubric, with readiness scored after each interview.
- **Personal plan and calendar.** Each employee sees their plan by phase (first 2 weeks, 30 days, 90 days), due
  dates, and in-person classes they can register for.

## 4. Visibility and compliance for managers

- **Team dashboard for 80–90 person organizations.** Sub-teams, filters, bulk assign, change due dates, email
  reminders and CSV export.
- **Compliance and knowledge gaps.** Required-training compliance by division and a knowledge-gap heatmap by role or
  equipment.
- **Expiring trainings and retakes.** Retraining cycles driven by scores: under 80 means a retake within 14 days.
- **Interview reviews.** Managers listen to or read answers and confirm the AI's score; the manager's score counts.
- **Open roles and promotion readiness.** Candidates ranked by skills, completed training, experience and performance,
  with clear pass/fail criteria for promotion.

## 5. Built for LANL's environment

- **Uses the systems LANL already has.** Connectors for the LANL directory, UTrain and Oracle HR (file exports today,
  live APIs when approved), with sync status on one page.
- **Accessible.** High-contrast and color-blind-safe themes, larger text, read-aloud, synced captions and transcripts,
  extra time on assessments; designed toward WCAG 2.2 AA and Section 508.
- **Scales to 20,000+ employees.** Rate limiting, request retries, caching, a circuit breaker on AI calls, separate
  workers for heavy reports, and PostgreSQL behind multiple app servers.
- **Secure by design.** Role-based access (employee, manager, admin), downloads only from approved official sources,
  no documents committed to source control, and works fully offline if AI is turned off.
- **Low cost to run.** AI is used only to build and personalize lessons; everything else runs on standard hosting.
  A FedRAMP-authorized cloud or LANL's own servers can host it.

## 6. Why it matters to LANL

- LANL employs about 16,500 people and expects to hire 800–1,000 a year (LANL FY2025 economic impact report).
  Every new hire and internal move needs a correct training plan quickly.
- Replacing an employee can cost one-half to two times their salary (Gallup); faster, more relevant onboarding
  shortens time to productivity and supports retention.
- Organizations spend about $1,254 per employee per year on formal learning (ATD 2025); turning existing documents
  into lessons reuses content LANL already owns instead of buying more.

Sources: [docs/RESEARCH_REFERENCES.md](RESEARCH_REFERENCES.md) and [docs/REFERENCES.md](REFERENCES.md).

## Suggested demo order (about 5 minutes)

1. Sign in, then the admin training library: three layers, real source documents, review and publish.
2. Manager: team dashboard, compliance, then the Role directory: new hire vs. promotion, assign in one click.
3. Employee: personal plan, calendar, a lesson built from a LANL document, practice and the AI tutor.
4. Accessibility settings, then open roles and promotion readiness.
