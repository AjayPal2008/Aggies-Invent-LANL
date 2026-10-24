"""Generate a long, FICTIONAL internal handbook PDF for demos (about 140 pages).

    python -m scripts.make_sample_handbook

It stands in for the 100-200 page internal documents a new project lead would
otherwise have to read. Content is invented for the prototype and is not LANL policy.
"""
import random
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

OUT = Path(__file__).resolve().parent.parent / "data" / "sample" / "documents" / "project_management_handbook.pdf"
rng = random.Random(7)

CHAPTERS = [
    ("Purpose and Scope", ["How to use this handbook", "Which projects it applies to", "Graded approach"], [
        "Every project with a total estimated cost over $500,000 must follow this handbook in full.",
        "Smaller projects shall apply a graded approach and document which sections they tailor and why.",
        "The project lead is responsible for knowing which requirements apply before work is authorized.",
        "Deviations from this handbook require written approval from the program manager before work starts."]),
    ("Roles and Responsibilities", ["Project lead", "Program manager and sponsor", "Project team and line management",
                                    "Safety and quality partners"], [
        "The project lead is accountable for scope, schedule, cost, safety and quality of the project.",
        "The project lead must not delegate accountability for safety, even when tasks are delegated.",
        "Line managers remain responsible for the people assigned to the project and their training.",
        "The project lead shall hold a weekly meeting with the team and keep a written action log.",
        "Conflicts between project needs and line management direction must be escalated to the program manager within two working days."]),
    ("Initiation and the Project Charter", ["Writing the charter", "Defining success", "Approval"], [
        "A signed project charter is required before any funds are committed.",
        "The charter must state objectives, scope boundaries, key deliverables, budget authority and the sponsor.",
        "Success criteria shall be measurable and agreed with the sponsor in writing.",
        "The project lead must confirm that required safety and security reviews are identified in the charter."]),
    ("Planning: Scope, Work Breakdown and Schedule", ["Scope statement", "Work breakdown structure", "Building the schedule",
                                                     "Critical path and float", "Baselines"], [
        "Every deliverable shall appear in the work breakdown structure with a single owner.",
        "The schedule must be resource-loaded and logically linked; hard-coded dates are not permitted without justification.",
        "The baseline schedule shall be approved before the first progress report is issued.",
        "The project lead must review the critical path with the team at least every two weeks.",
        "Work that is not in the approved scope must not be started without a change request."]),
    ("Cost Estimating and Budget Management", ["Estimating methods", "Contingency and management reserve", "Tracking actuals"], [
        "Estimates shall state their basis, assumptions and confidence level.",
        "Contingency must be held by the project lead and released only through documented change control.",
        "Charging time or materials to the wrong project is prohibited and must be corrected and reported immediately.",
        "The project lead shall reconcile actual costs against the budget every month."]),
    ("Earned Value and Performance Reporting", ["Planned value, earned value and actual cost", "Variance thresholds", "Monthly reports"], [
        "Projects over $2 million must report earned value monthly.",
        "A cost or schedule variance greater than 10 percent requires a written variance explanation and corrective action plan.",
        "Reports shall be honest about problems; optimistic forecasts without a basis are not acceptable.",
        "The project lead must brief the sponsor before a threshold breach appears in a formal report."]),
    ("Risk and Opportunity Management", ["Identifying risks", "Scoring and ranking", "Mitigation plans", "Risk reviews"], [
        "Every project shall maintain a risk register with an owner, likelihood, impact and response for each risk.",
        "High risks must have a mitigation plan with dates and must be reviewed every month.",
        "New risks identified by any team member shall be added to the register within one week.",
        "The project lead must never remove a risk from the register without recording why it was closed."]),
    ("Safety and Conduct of Operations in Projects", ["Integrating safety into planning", "Pre-job briefs", "Stop work authority",
                                                      "Incidents and near misses"], [
        "Safety requirements shall be planned into the schedule, not added after the fact.",
        "A pre-job brief is required before any field or laboratory work that involves hazards.",
        "Any worker may stop work they believe is unsafe; the project lead must support that decision and never retaliate.",
        "Schedule pressure is never a reason to skip a required safety step.",
        "Incidents and near misses must be reported to line management the same day."]),
    ("Quality Assurance and Configuration Management", ["Quality planning", "Reviews and inspections", "Configuration control",
                                                         "Records"], [
        "A quality plan shall be approved before design work begins.",
        "Design changes must be reviewed and approved through configuration control before they are implemented.",
        "Quality records shall be complete, legible and retrievable for the life of the project plus seven years.",
        "Nonconforming items must be identified, segregated and dispositioned before use."]),
    ("Stakeholder Communication", ["Mapping stakeholders", "Communication plans", "Difficult conversations", "Customer updates"], [
        "The project lead shall maintain a stakeholder list with what each person needs to know and how often.",
        "Bad news must be communicated early and in person or by phone, followed by a written summary.",
        "Customer commitments shall not be made without checking scope, schedule and budget impact first.",
        "Meeting decisions and actions must be recorded and sent to attendees within two working days."]),
    ("Procurement and Subcontracts", ["Planning procurements", "Working with Procurement", "Subcontractor oversight"], [
        "Project staff must not direct subcontractors outside the terms of their contract.",
        "Procurement lead times shall be built into the schedule before the baseline is approved.",
        "Gifts or favors from vendors are prohibited regardless of value.",
        "Subcontractor safety performance must be reviewed at least quarterly."]),
    ("Export Control, Security and Information Handling", ["Export-controlled information", "Foreign national interactions",
                                                           "Classified and controlled unclassified information"], [
        "The project lead must obtain an export control determination before sharing technical data outside the Laboratory.",
        "Foreign national visits and collaborations shall be approved in advance.",
        "Controlled information must be marked, stored and transmitted according to its category.",
        "Suspected security incidents must be reported immediately; do not investigate on your own."]),
    ("Change Control", ["What counts as a change", "Change requests", "Change board"], [
        "Any change to approved scope, schedule baseline or budget requires a documented change request.",
        "Change requests shall describe the reason, impacts and alternatives considered.",
        "The project lead must not implement a change before it is approved, even if the customer asks.",
        "Approved changes must be reflected in the baseline within one reporting period."]),
    ("Leading the Project Team", ["Setting expectations", "Feedback and coaching", "Conflict on the team", "Workload and burnout",
                                  "Recognizing good work"], [
        "The project lead shall set clear expectations for each team member's role and deliverables.",
        "Performance concerns must be raised privately and early, and shared with the employee's line manager.",
        "Conflicts between team members should be addressed directly by the project lead before they affect the work.",
        "The project lead must watch for sustained overtime and rebalance work rather than accept burnout.",
        "Retaliation against anyone who raises a concern is prohibited."]),
    ("Closeout and Lessons Learned", ["Completing deliverables", "Financial closeout", "Lessons learned"], [
        "A project shall not be closed until all deliverables are accepted in writing.",
        "Open purchase orders and charge codes must be closed within 60 days of completion.",
        "A lessons-learned session is required for every project, and results shall be shared with the program office."]),
]

EXPLAIN = [
    "In practice, this means the {role} plans for it from the start rather than reacting later.",
    "Experience across the Laboratory shows that projects that skip this step spend more time recovering than they saved.",
    "When in doubt, the {role} should ask the program office or the subject matter expert before proceeding.",
    "This requirement exists because problems found late are far more expensive and can put people at risk.",
    "Teams that do this well usually keep a short checklist and review it in their weekly meeting.",
    "The intent is not paperwork for its own sake; it is to make sure decisions are visible and can be reviewed.",
    "New project leads often underestimate how long this takes, so build time for it into the schedule.",
    "A common failure mode is treating this as a one-time task instead of something revisited as the project changes.",
    "Where this section conflicts with a facility-specific procedure, the more restrictive requirement applies.",
    "Examples from recent projects show that early, honest communication avoided most escalations.",
]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10.5, leading=15, spaceAfter=8)
    h1, h2 = styles["Heading1"], styles["Heading2"]
    doc = SimpleDocTemplate(str(OUT), pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch,
                            title="Project Management Handbook (SAMPLE)")
    story = [Paragraph("Project Management Handbook", styles["Title"]),
             Paragraph("SAMPLE DOCUMENT FOR THE AGGIES INVENT PROTOTYPE. Fictional content, not LANL policy.", body),
             Spacer(1, 12)]
    for i, (title, _, _) in enumerate(CHAPTERS, 1):
        story.append(Paragraph(f"Chapter {i}  {title}", body))
    story.append(PageBreak())
    for ci, (title, sections, rules) in enumerate(CHAPTERS, 1):
        story.append(Paragraph(f"{ci} {title}", h1))
        story.append(Paragraph(f"This chapter covers {title.lower()} for project leads and project managers. "
                               "Read it with the requirements in your project's charter and the facility procedures that apply to your work.", body))
        for si, sec in enumerate(sections, 1):
            story.append(Paragraph(f"{ci}.{si} {sec}", h2))
            for _ in range(rng.randint(20, 30)):
                rule = rng.choice(rules)
                extra = " ".join(rng.sample(EXPLAIN, 3)).format(role="project lead")
                story.append(Paragraph(f"{rule} {extra}", body))
        story.append(PageBreak())
    doc.build(story)
    from pypdf import PdfReader

    print(f"Wrote {OUT} ({len(PdfReader(str(OUT)).pages)} pages)")


if __name__ == "__main__":
    main()
