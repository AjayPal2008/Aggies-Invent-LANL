"""Generate realistic SAMPLE data in backend/data/sample/.

Everything here is fictional: employees, emails, salaries, course codes and URLs
are made up. Directorate names follow LANL's public org chart so the demo feels
familiar. Dates are relative to today, so re-run this before a demo:

    python -m scripts.make_sample_data
"""
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "sample"
rng = random.Random(42)
TODAY = date.today()

DIRECTORATES = {
    "ALDSCT": "Simulation, Computing & Theory",
    "ALDPS": "Physical Sciences",
    "ALDCELS": "Chemical, Earth & Life Sciences",
    "ALDGS": "Global Security",
    "ALDPU": "Plutonium Infrastructure",
    "ALDWE": "Weapons Engineering",
    "ALDESHQ": "Environment, Safety, Health & Quality",
    "ALDFO": "Facilities & Operations",
}

DIVISIONS = [
    ("CCS", "Computer, Computational & Statistical Sciences", "ALDSCT"),
    ("HPC", "High Performance Computing", "ALDSCT"),
    ("XCP", "Computational Physics", "ALDSCT"),
    ("MST", "Materials Science & Technology", "ALDPS"),
    ("P", "Physics", "ALDPS"),
    ("C", "Chemistry", "ALDCELS"),
    ("EES", "Earth & Environmental Sciences", "ALDCELS"),
    ("NEN", "Nuclear Engineering & Nonproliferation", "ALDGS"),
    ("PF", "Plutonium Facility Operations", "ALDPU"),
    ("ESHQ-RP", "Radiation Protection", "ALDESHQ"),
    ("FO-UT", "Utilities & Maintenance", "ALDFO"),
]

# code, title, category, required, delivery, source, minutes, validity_months, skills, prereqs, roles, equipment, facilities, outline
TRAININGS = [
    ("GEN-100", "General Employee Training", "safety", True, "online", "UTrain", 90, 24,
     "hazard awareness;emergency response;stop work authority", "", "all", "", "",
     "Lab mission and safety culture;Stop work authority;Emergency alarms and evacuation;Reporting injuries and near misses;Who to call"),
    ("ORI-101", "New Employee Orientation: Working at LANL", "culture", True, "hybrid", "UTrain", 240, None,
     "lab culture;security basics", "", "all", "", "Otowi Building",
     "Mission and history;Directorates and divisions;Benefits and resources;Badging and site access;Mentoring and career paths"),
    ("CYB-110", "Cybersecurity Awareness", "compliance", True, "online", "Security Education Portal", 45, 12,
     "cybersecurity;phishing detection", "", "all", "", "",
     "Phishing and social engineering;Password and MFA rules;Removable media;Reporting incidents"),
    ("SEC-120", "Insider Threat Awareness", "compliance", True, "online", "Security Education Portal", 30, 12,
     "security basics;insider threat", "", "all", "", "", "Indicators of insider threat;Reporting obligations;Case studies"),
    ("SEC-210", "Classified Matter Protection & Control", "compliance", False, "in_person", "Security Education Portal", 180, 12,
     "classified handling;security basics", "SEC-120", "XCP-SCI2;XCP-SCI3;NEN-ENG2;PF-TECH2", "", "TA-3",
     "Classification levels;Marking and storage;Transmission rules;Incident response"),
    ("ETH-130", "Ethics & Conduct", "compliance", True, "online", "UTrain", 40, 24, "ethics", "", "all", "", "",
     "Conflicts of interest;Gifts and outside activity;Speaking up"),
    ("EXP-140", "Export Control Basics", "compliance", False, "online", "UTrain", 60, 24, "export control",
     "", "CCS-SCI1;CCS-SCI2;NEN-ENG2;MST-SCI2", "", "", "What is controlled;Deemed exports;Foreign national interactions;Getting a determination"),
    ("HAZ-150", "Hazard Communication (GHS)", "safety", True, "online", "ESH Training Portal", 45, 36, "chemical safety;hazard awareness",
     "GEN-100", "C-SCI1;C-SCI2;MST-SCI2;PF-TECH1;PF-TECH2;EES-SCI1;FO-TECH1", "", "",
     "Safety data sheets;GHS labels and pictograms;Chemical storage;Spill response"),
    ("CHM-220", "Chemical Hygiene & Fume Hood Use", "safety", False, "in_person", "ESH Training Portal", 120, 36,
     "chemical safety;fume hood operation", "HAZ-150", "C-SCI1;C-SCI2;MST-SCI2", "fume hood", "TA-46",
     "Chemical hygiene plan;Fume hood sash and airflow;Incompatible materials;Exposure response"),
    ("RAD-101", "Radiological Worker I", "safety", False, "hybrid", "ESH Training Portal", 240, 24,
     "radiation safety;dosimetry", "GEN-100", "PF-TECH1;PF-TECH2;ESHQ-RCT1;ESHQ-RCT2;NEN-ENG2;MST-SCI2", "dosimeter", "TA-55",
     "Types of radiation;ALARA principles;Dosimetry and dose limits;Posting and controlled areas;Contamination control"),
    ("RAD-201", "Radiological Worker II", "safety", False, "in_person", "ESH Training Portal", 480, 24,
     "radiation safety;contamination control;dosimetry", "RAD-101", "PF-TECH2;ESHQ-RCT1;ESHQ-RCT2", "frisker;dosimeter", "TA-55",
     "Donning and doffing PPE;Frisking and survey techniques;High contamination areas;Practical exercise"),
    ("GBX-310", "Glovebox Operations", "technical", False, "in_person", "Plutonium Facility Training", 480, 12,
     "glovebox operation;contamination control;criticality safety", "RAD-201;CRT-230", "PF-TECH1;PF-TECH2", "glovebox", "TA-55 PF-4",
     "Glovebox design and confinement;Glove change procedure;Breach response;Material transfer;Hands-on practical"),
    ("CRT-230", "Nuclear Criticality Safety for Operators", "safety", False, "hybrid", "Plutonium Facility Training", 240, 12,
     "criticality safety", "RAD-101", "PF-TECH1;PF-TECH2;NEN-ENG2", "", "TA-55 PF-4",
     "Criticality basics;Controlled parameters;Postings and limits;Criticality alarm response"),
    ("RCT-400", "Radiological Control Technician Qualification", "technical", False, "in_person", "ESH Training Portal", 960, 24,
     "radiation safety;survey instruments;dosimetry;contamination control", "RAD-201", "ESHQ-RCT1;ESHQ-RCT2", "survey meter;air sampler", "TA-55",
     "Survey instrument operation;Air sampling;Job coverage;Radiological work permits;Oral board preparation"),
    ("ELE-240", "Electrical Safety (NFPA 70E)", "safety", False, "hybrid", "ESH Training Portal", 240, 36,
     "electrical safety;lockout tagout", "GEN-100", "FO-TECH1;FO-TECH2;P-SCI2", "arc flash PPE", "",
     "Shock and arc flash hazards;Approach boundaries;Energized work permits;PPE selection"),
    ("LOT-250", "Lockout/Tagout", "safety", False, "in_person", "ESH Training Portal", 120, 12, "lockout tagout",
     "ELE-240", "FO-TECH1;FO-TECH2", "lockout devices", "TA-3",
     "Hazardous energy;Authorized vs affected workers;LOTO procedure steps;Verification of zero energy"),
    ("CRN-260", "Overhead Crane & Hoist Operation", "technical", False, "in_person", "ESH Training Portal", 240, 36,
     "rigging;crane operation", "GEN-100", "FO-TECH2;MST-SCI2", "overhead crane;hoist", "TA-3",
     "Pre-use inspection;Load charts;Hand signals;Rigging hardware;Practical lift"),
    ("LAS-270", "Laser Safety", "safety", False, "hybrid", "ESH Training Portal", 120, 24, "laser safety",
     "GEN-100", "P-SCI1;P-SCI2;MST-SCI2", "class 4 laser", "TA-53",
     "Laser classes;Eye and skin hazards;Controlled areas and interlocks;Alignment procedures"),
    ("PRS-280", "Pressure Safety", "safety", False, "online", "ESH Training Portal", 90, 36, "pressure safety",
     "GEN-100", "P-SCI2;MST-SCI2;FO-TECH2", "compressed gas", "",
     "Stored energy hazards;Pressure system design basics;Compressed gas cylinders;Inspection"),
    ("BER-290", "Beryllium Awareness", "safety", False, "online", "ESH Training Portal", 30, 12, "beryllium awareness;chemical safety",
     "", "MST-SCI1;MST-SCI2;PF-TECH2", "", "", "Beryllium health effects;Controlled areas;Medical surveillance"),
    ("WST-300", "Waste Generator Training", "safety", False, "online", "ESH Training Portal", 60, 24, "waste management",
     "HAZ-150", "C-SCI1;C-SCI2;PF-TECH1;PF-TECH2;EES-SCI1", "", "",
     "Waste types;Satellite accumulation areas;Labeling;Pickup requests"),
    ("COO-320", "Conduct of Operations Fundamentals", "technical", False, "online", "UTrain", 120, None,
     "conduct of operations;procedure use", "GEN-100", "PF-TECH1;PF-TECH2;FO-TECH1;FO-TECH2;ESHQ-RCT1;ESHQ-RCT2", "", "",
     "Procedure adherence;Pre-job briefs;Turnover;Human performance tools"),
    ("QA-330", "Quality Assurance for Researchers", "compliance", False, "online", "UTrain", 60, 36, "quality assurance",
     "", "MST-SCI2;C-SCI2;NEN-ENG2;XCP-SCI3", "", "", "QA program basics;Records;Software QA;Graded approach"),
    ("HPC-101", "HPC Cluster Onboarding", "technical", False, "online", "HPC Training Site", 90, None,
     "hpc systems;linux", "CYB-110", "HPC-ENG1;HPC-ENG2;CCS-SCI1;CCS-SCI2;XCP-SCI2;XCP-SCI3", "", "",
     "Accounts and tokens;Logging in and file systems;Modules;Batch jobs with Slurm;Getting help"),
    ("HPC-210", "Parallel Programming with MPI", "technical", False, "hybrid", "HPC Training Site", 480, None,
     "parallel programming;hpc systems", "HPC-101", "HPC-ENG2;CCS-SCI2;XCP-SCI2;XCP-SCI3", "", "",
     "MPI basics;Point-to-point communication;Collectives;Debugging and profiling"),
    ("HPC-220", "GPU Computing & Performance Tuning", "technical", False, "in_person", "HPC Training Site", 480, None,
     "gpu programming;performance tuning", "HPC-210", "HPC-ENG2;CCS-SCI2;XCP-SCI3", "GPU nodes", "TA-3 SCC",
     "GPU architecture;Kernels and memory;Profiling tools;Optimization case study"),
    ("PY-150", "Python for Scientific Computing", "technical", False, "online", "UTrain", 300, None,
     "python;data analysis", "", "CCS-SCI1;EES-SCI1;P-SCI1;C-SCI1;MST-SCI1;XCP-SCI2", "", "",
     "NumPy and arrays;Pandas;Plotting;Reproducible notebooks"),
    ("ML-250", "Machine Learning for Science", "technical", False, "hybrid", "UTrain", 600, None,
     "machine learning;python;data analysis", "PY-150", "CCS-SCI1;CCS-SCI2;EES-SCI1", "", "",
     "Supervised learning;Model validation;Uncertainty quantification;Applying ML to experiments"),
    ("NUC-260", "Nuclear Material Accountability", "compliance", False, "online", "Plutonium Facility Training", 120, 12,
     "material accountability", "", "PF-TECH2;NEN-ENG2", "", "TA-55", "MC&A basics;Inventory;Transfers;Discrepancy reporting"),
    ("SUP-500", "Leadership Essentials for New Supervisors", "culture", False, "in_person", "Leadership Development", 960, None,
     "leadership;coaching", "", "CCS-MGR;PF-MGR;FO-MGR;MST-MGR;ESHQ-MGR;HPC-MGR", "", "Otowi Building",
     "Your role as a supervisor;Coaching and feedback;Performance management;Safety leadership"),
    ("PM-200", "Project Management Fundamentals", "technical", False, "hybrid", "UTrain", 480, None,
     "project planning;risk management;budget management", "", "CCS-PL3", "", "",
     "Project lifecycle;Charters and scope;Work breakdown structures;Scheduling and critical path;Risk registers;Budgets and contingency"),
    ("PM-310", "Earned Value Management", "technical", False, "online", "UTrain", 240, None,
     "earned value;budget management;performance reporting", "PM-200", "CCS-PL3", "", "",
     "Planned value, earned value and actual cost;Cost and schedule variance;Indices and forecasts;Variance reporting"),
    ("COM-320", "Leading Difficult Conversations", "culture", False, "in_person", "Leadership Development", 240, None,
     "stakeholder communication;leadership;coaching", "", "CCS-PL3;CCS-MGR;PF-MGR;FO-MGR;MST-MGR;ESHQ-MGR;HPC-MGR", "", "Otowi Building",
     "Preparing for the conversation;Delivering bad news early;Feedback that lands;Handling conflict on a team"),
    ("MEN-140", "Mentoring at LANL", "culture", False, "online", "Leadership Development", 60, None, "coaching;lab culture",
     "", "all", "", "", "Being a mentee;Being a mentor;Setting goals"),
]

POSITIONS = [
    # code, title, division, level, min_years, skills, trainings, prereqs, open, fy, headcount
    ("CCS-SCI1", "Scientist 1, Data Science", "CCS", 1, 0, "python;data analysis;machine learning", "PY-150;CYB-110", "BS/MS in a quantitative field", False, None, 1),
    ("CCS-SCI2", "Scientist 2, Computational Science", "CCS", 2, 3, "python;machine learning;hpc systems;parallel programming", "PY-150;HPC-101;ML-250", "MS/PhD", True, 2027, 2),
    ("CCS-PL3", "Project Lead", "CCS", 3, 5, "project planning;risk management;budget management;stakeholder communication;leadership",
     "PM-200;QA-330;EXP-140", "BS technical field; Q clearance; PMP preferred", True, 2027, 2),
    ("CCS-MGR", "Group Leader, CCS", "CCS", 4, 10, "leadership;coaching;machine learning", "SUP-500", "PhD; supervisory experience", False, None, 1),
    ("HPC-ENG1", "HPC Systems Engineer 1", "HPC", 1, 0, "linux;hpc systems", "HPC-101;CYB-110", "BS in CS/CE", False, None, 1),
    ("HPC-ENG2", "HPC Systems Engineer 2", "HPC", 2, 3, "linux;hpc systems;parallel programming;performance tuning", "HPC-101;HPC-210", "BS + 3 yrs", True, 2027, 1),
    ("HPC-MGR", "Group Leader, HPC Platforms", "HPC", 4, 10, "leadership;hpc systems", "SUP-500", "Supervisory experience", False, None, 1),
    ("XCP-SCI2", "Computational Physicist 2", "XCP", 2, 3, "python;hpc systems;parallel programming", "HPC-101;HPC-210", "PhD Physics; Q clearance", False, None, 1),
    ("XCP-SCI3", "Computational Physicist 3", "XCP", 3, 6, "parallel programming;gpu programming;performance tuning;classified handling", "HPC-210;SEC-210;QA-330", "PhD Physics; Q clearance", True, 2027, 1),
    ("MST-SCI1", "Materials Scientist 1", "MST", 1, 0, "chemical safety;python", "HAZ-150", "BS/MS Materials", False, None, 1),
    ("MST-SCI2", "Materials Scientist 2", "MST", 2, 3, "chemical safety;radiation safety;quality assurance;beryllium awareness", "HAZ-150;RAD-101;QA-330;BER-290", "PhD Materials", True, 2027, 1),
    ("MST-MGR", "Group Leader, MST", "MST", 4, 10, "leadership;coaching", "SUP-500", "PhD; supervisory experience", False, None, 1),
    ("P-SCI1", "Physicist 1, Experimental", "P", 1, 0, "laser safety;python", "LAS-270", "BS/MS Physics", False, None, 1),
    ("P-SCI2", "Physicist 2, Experimental", "P", 2, 3, "laser safety;electrical safety;pressure safety", "LAS-270;ELE-240;PRS-280", "PhD Physics", True, 2027, 1),
    ("C-SCI1", "Chemist 1", "C", 1, 0, "chemical safety;fume hood operation", "HAZ-150;CHM-220", "BS Chemistry", False, None, 1),
    ("C-SCI2", "Chemist 2", "C", 2, 3, "chemical safety;fume hood operation;waste management;quality assurance", "HAZ-150;CHM-220;WST-300;QA-330", "PhD Chemistry", True, 2027, 1),
    ("EES-SCI1", "Earth Scientist 1", "EES", 1, 0, "python;data analysis;waste management", "PY-150", "BS/MS Geoscience", False, None, 1),
    ("NEN-ENG2", "Nuclear Engineer 2", "NEN", 2, 3, "criticality safety;radiation safety;material accountability;export control", "RAD-101;CRT-230;NUC-260;EXP-140", "MS Nuclear Eng; Q clearance", True, 2027, 1),
    ("PF-TECH1", "Plutonium Facility Technician 1", "PF", 1, 0, "radiation safety;conduct of operations;procedure use", "RAD-101;COO-320;HAZ-150", "HS diploma + training; Q clearance", False, None, 2),
    ("PF-TECH2", "Plutonium Facility Technician 2", "PF", 2, 2, "glovebox operation;criticality safety;contamination control;material accountability", "RAD-201;GBX-310;CRT-230;NUC-260", "PF-TECH1 + 2 yrs; Q clearance", True, 2027, 3),
    ("PF-MGR", "Operations Manager, PF-4", "PF", 4, 10, "leadership;conduct of operations;criticality safety", "SUP-500;COO-320", "Supervisory experience; Q clearance", False, None, 1),
    ("ESHQ-RCT1", "Radiological Control Technician 1", "ESHQ-RP", 1, 0, "radiation safety;dosimetry;procedure use", "RAD-201;COO-320", "HS + RCT program", False, None, 2),
    ("ESHQ-RCT2", "Radiological Control Technician 2", "ESHQ-RP", 2, 3, "radiation safety;survey instruments;contamination control;dosimetry", "RAD-201;RCT-400", "RCT qualification", True, 2027, 2),
    ("ESHQ-MGR", "Group Leader, Radiation Protection", "ESHQ-RP", 4, 10, "leadership;radiation safety", "SUP-500", "Supervisory experience", False, None, 1),
    ("FO-TECH1", "Maintenance Technician 1", "FO-UT", 1, 0, "electrical safety;procedure use", "ELE-240;COO-320", "Trade certificate", False, None, 2),
    ("FO-TECH2", "Maintenance Technician 2", "FO-UT", 2, 3, "electrical safety;lockout tagout;rigging;crane operation", "ELE-240;LOT-250;CRN-260", "Journeyman license", True, 2027, 2),
    ("FO-MGR", "Maintenance Superintendent", "FO-UT", 4, 10, "leadership;lockout tagout", "SUP-500", "Supervisory experience", False, None, 1),
]

FIRST = "Alex Jordan Taylor Morgan Casey Riley Jamie Avery Quinn Rowan Elena Mateo Sofia Diego Priya Arjun Mei Wei Fatima Omar Grace Noah Liam Emma Ava Lucas Isabel Carlos Hana Kenji Nia Malik Zoe Ethan Lena Marco Tara Ivan Aisha Ben".split()
LAST = "Garcia Martinez Lopez Chavez Romero Baca Trujillo Montoya Sandoval Vigil Nguyen Patel Kim Chen Johnson Smith Brown Davis Wilson Anderson Thomas Moore Clark Lewis Walker Young Allen Wright Scott Green".split()
STYLES = ["visual", "reading", "hands_on", "auditory", "visual", "hands_on"]

BACKGROUNDS = {
    "CCS": "Built machine learning models in python for sensor data; data analysis with pandas; some hpc systems use on university clusters.",
    "HPC": "Linux system administration, Slurm scheduler, hpc systems monitoring; wrote parallel programming code with MPI.",
    "XCP": "Physics PhD; parallel programming in C++ and MPI; gpu programming with CUDA; performance tuning of hydrodynamics codes.",
    "MST": "Materials characterization; chemical safety training from graduate lab; quality assurance documentation.",
    "P": "Optics lab experience with class 4 lasers; laser safety officer in grad school; python data analysis.",
    "C": "Synthetic chemistry; fume hood operation daily; waste management for satellite accumulation area.",
    "EES": "Hydrology field work; python and data analysis for groundwater models; machine learning basics.",
    "NEN": "Nuclear engineering MS; criticality safety calculations with MCNP; radiation safety coursework.",
    "PF": "Navy nuclear technician; radiation safety, contamination control and procedure use; conduct of operations.",
    "ESHQ-RP": "Health physics associate degree; survey instruments and dosimetry; radiation safety.",
    "FO-UT": "Licensed electrician; electrical safety and lockout tagout; rigging and crane operation certificate.",
}


def write(name, rows, fields):
    with (OUT / f"{name}.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main(staff: int = 54, big_team: int = 85, out: Path | None = None):
    """staff: people spread across the lab. big_team: extra people under manager@lanl.gov (via team leads)."""
    global OUT
    if out is not None:
        OUT = Path(out)
    OUT.mkdir(parents=True, exist_ok=True)
    # Divisions (directorates are parents)
    div_rows = [{"code": c, "name": n, "parent_code": "", "directorate": "", "leader_email": ""} for c, n in DIRECTORATES.items()]
    div_rows += [{"code": c, "name": n, "parent_code": p, "directorate": DIRECTORATES[p], "leader_email": ""} for c, n, p in DIVISIONS]

    used_names = set()

    def person():
        for _ in range(200):
            f, l = rng.choice(FIRST), rng.choice(LAST)
            if (f, l) not in used_names:
                used_names.add((f, l))
                return f, l
        # Name pool exhausted on big rosters: add a middle initial.
        f, l = rng.choice(FIRST), rng.choice(LAST)
        return f"{f} {chr(65 + len(used_names) % 26)}.", l

    emps = []
    n = 100001

    def add(f, l, pos_code, div, level, years, hire, manager, is_mgr=False, perf=None, style=None):
        nonlocal n
        pos = next((p for p in POSITIONS if p[0] == pos_code), None)
        emp = {
            "employee_id": f"Z{n}", "email": f"{f.lower().replace(' ', '').replace('.', '')}.{l.lower()}{n}@lanl.gov", "full_name": f"{f} {l}",
            "job_title": pos[1] if pos else pos_code, "position_code": pos_code, "division_code": div, "job_level": level,
            "hire_date": hire.isoformat(), "years_experience": years,
            "salary": int(70000 + level * 22000 + years * 1800 + rng.randint(-6000, 6000)),
            "performance_rating": perf if perf is not None else round(rng.choice([2.8, 3.0, 3.2, 3.5, 3.7, 4.0, 4.2, 4.5, 4.8]), 1),
            "manager_id": manager, "is_manager": "Y" if is_mgr else "N",
            "skills": "", "experience_summary": BACKGROUNDS.get(div, ""), "learning_style": style or rng.choice(STYLES),
        }
        n += 1
        emps.append(emp)
        return emp["employee_id"]

    # Admin + one demo manager and demo hire with fixed, easy emails
    admin = add("Dana", "Admin", "CCS-MGR", "CCS", 5, 20, TODAY - timedelta(days=3000), "", True, 4.5, "reading")
    emps[-1]["email"] = "admin@lanl.gov"
    emps[-1]["job_title"] = "Training Program Administrator"

    managers = {}
    for mgr_pos, div in [("CCS-MGR", "CCS"), ("PF-MGR", "PF"), ("ESHQ-MGR", "ESHQ-RP"), ("FO-MGR", "FO-UT"), ("MST-MGR", "MST"), ("HPC-MGR", "HPC")]:
        f, l = person()
        managers[div] = add(f, l, mgr_pos, div, 4, rng.randint(12, 25), TODAY - timedelta(days=rng.randint(2500, 6000)), admin, True, 4.2)
    emps[1]["email"] = "manager@lanl.gov"  # CCS group leader
    emps[1]["full_name"] = "Morgan Reyes"

    # Who reports to whom (divisions without their own manager roll up to a related one)
    reports_to = {"CCS": "CCS", "XCP": "HPC", "HPC": "HPC", "EES": "CCS", "PF": "PF", "NEN": "PF", "ESHQ-RP": "ESHQ-RP",
                  "FO-UT": "FO-UT", "MST": "MST", "P": "MST", "C": "MST"}
    staff_positions = [p for p in POSITIONS if not p[0].endswith("MGR")]
    for i in range(staff):
        pos = staff_positions[i % len(staff_positions)]
        code, _, div, level, min_years = pos[:5]
        new_hire = rng.random() < 0.5
        hire = TODAY - timedelta(days=rng.randint(10, 330) if new_hire else rng.randint(400, 4000))
        years = round(max(0, min_years + rng.uniform(-1.5, 4)) if not new_hire else rng.uniform(0, min_years + 2), 1)
        f, l = person()
        boss = reports_to[div]
        if big_team and boss == "CCS":
            boss = "HPC"  # keep the demo manager's group at exactly big_team people
        add(f, l, code, div, level, years, hire, managers[boss])
    # Demo hire: a brand new CCS data scientist
    emps[7]["email"] = "hire@lanl.gov"
    emps[7]["full_name"] = "Jordan Lee"
    emps[7]["position_code"], emps[7]["job_title"], emps[7]["division_code"] = "CCS-SCI1", "Scientist 1, Data Science", "CCS"
    emps[7]["job_level"], emps[7]["years_experience"], emps[7]["manager_id"] = 1, 0.5, managers["CCS"]
    emps[7]["hire_date"] = (TODAY - timedelta(days=21)).isoformat()
    emps[7]["learning_style"] = "visual"
    emps[7]["experience_summary"] = BACKGROUNDS["CCS"]

    # A large group under the demo manager: team leads, each with their own reports.
    if big_team:
        team_positions = [p for p in POSITIONS if p[2] in ("CCS", "EES", "HPC", "XCP") and not p[0].endswith("MGR")]
        leads = []
        for k in range(max(1, big_team // 20)):
            f, l = person()
            leads.append(add(f, l, "CCS-SCI2", "CCS", 3, rng.randint(8, 15), TODAY - timedelta(days=rng.randint(1500, 4000)),
                             managers["CCS"], True, 4.3))
            emps[-1]["job_title"] = f"Team Lead, Data Science Team {k + 1}"
        for i in range(big_team - len(leads)):
            pos = team_positions[i % len(team_positions)]
            code, _, div, level, min_years = pos[:5]
            new_hire = rng.random() < 0.35
            hire = TODAY - timedelta(days=rng.randint(10, 330) if new_hire else rng.randint(400, 4000))
            years = round(max(0, min_years + rng.uniform(-1.5, 4)) if not new_hire else rng.uniform(0, min_years + 2), 1)
            f, l = person()
            add(f, l, code, div, level, years, hire, leads[i % len(leads)])

    write("divisions", div_rows, ["code", "name", "parent_code", "directorate", "leader_email"])

    pos_rows = []
    for code, title, div, level, min_years, skills, trainings, prereqs, is_open, fy, hc in POSITIONS:
        pos_rows.append({"position_code": code, "job_title": title, "division": div, "job_level": level, "min_experience": min_years,
                         "required_skills": skills, "required_trainings": trainings, "prerequisites": prereqs,
                         "status": "Open" if is_open else "Filled", "fiscal_year": fy or "", "openings": hc,
                         "hiring_manager_email": "manager@lanl.gov" if div == "CCS" and is_open else ""})
    write("positions", pos_rows, list(pos_rows[0]))

    # Trainings split by site: UTrain in trainings.csv, others in trainings_<site>.csv
    by_site = {}
    for (code, title, cat, req, delivery, source, minutes, validity, skills, prereqs, roles, equip, fac, outline) in TRAININGS:
        row = {"course_code": code, "course_title": title, "description": f"{title}. {outline.split(';')[0]} and more.",
               "category": cat, "mandatory": "Y" if req else "N", "delivery_method": delivery, "system": source,
               "url": f"https://training.example/{source.lower().replace(' ', '-')}/{code}", "duration": minutes,
               "recert_months": validity or "", "skill_tags": skills, "prereqs": prereqs, "applicable_roles": roles,
               "equipment_tags": equip, "facility": fac, "topics": outline}
        key = "trainings" if source == "UTrain" else "trainings_" + source.lower().replace(" ", "_")
        by_site.setdefault(key, []).append(row)
    for old in OUT.glob("trainings_*.csv"):
        old.unlink()
    for key, rows in by_site.items():
        write(key, rows, list(rows[0]))

    # Sessions for in-person / hybrid courses over the next ~3 months
    locations = ["TA-3 Bldg 1690 Rm 120", "TA-55 Training Center", "TA-46 Lab 102", "Otowi Bldg Rm 210", "TA-53 Conf Rm B", "TA-3 SCC Rm 300"]
    sessions = []
    for t in TRAININGS:
        if t[4] in ("in_person", "hybrid"):
            for k in range(3):
                day = TODAY + timedelta(days=rng.randint(3, 85))
                while day.weekday() > 4:
                    day += timedelta(days=1)
                start = datetime.combine(day, datetime.min.time()) + timedelta(hours=rng.choice([8, 9, 13]))
                sessions.append({"course_code": t[0], "start": start.strftime("%Y-%m-%d %H:%M"),
                                 "end": (start + timedelta(minutes=min(t[6], 480))).strftime("%Y-%m-%d %H:%M"),
                                 "room": rng.choice(locations), "trainer": f"{rng.choice(FIRST)} {rng.choice(LAST)}", "seats": rng.choice([12, 16, 20, 24])})
    write("training_sessions", sessions, ["course_code", "start", "end", "room", "trainer", "seats"])

    # Completion history
    pos_by_code = {p[0]: p for p in POSITIONS}
    tr_by_code = {t[0]: t for t in TRAININGS}
    history = []
    for e in emps:
        hire = date.fromisoformat(e["hire_date"])
        tenure = (TODAY - hire).days
        pos = pos_by_code.get(e["position_code"])
        # Required trainings that apply to this person's role
        codes = {t[0] for t in TRAININGS if t[3] and (t[10] == "all" or e["position_code"] in t[10].split(";"))}
        if pos:
            codes |= set(pos[6].split(";"))
        for code in sorted(c for c in codes if c):
            t = tr_by_code[code]
            r = rng.random()
            if e["email"] == "hire@lanl.gov":  # demo hire: a realistic first month
                status = {"GEN-100": "completed", "ORI-101": "completed", "CYB-110": "in_progress"}.get(code, "not_started")
                score = {"GEN-100": 92, "ORI-101": 88}.get(code)
                done = TODAY - timedelta(days=10) if status == "completed" else None
                due = hire + timedelta(days=30) if t[3] else TODAY + timedelta(days=rng.randint(10, 45))
                if code == "SEC-120":
                    due = TODAY - timedelta(days=2)  # one overdue item
            elif tenure < 60 and r < 0.6:
                status, score, done = ("in_progress" if r < 0.3 else "not_started"), None, None
                due = hire + timedelta(days=30) if t[3] else hire + timedelta(days=60)
            else:
                status = "completed" if r < 0.8 else ("in_progress" if r < 0.9 else "not_started")
                score = round(rng.choice([62, 70, 76, 82, 85, 88, 91, 94, 97, 100]) if status == "completed" else 0) or None
                if status == "completed" and t[7]:
                    # spread completions so some certifications are close to expiring
                    done = TODAY - timedelta(days=rng.randint(30, max(31, min(tenure, t[7] * 30))))
                elif status == "completed":
                    done = TODAY - timedelta(days=rng.randint(5, max(6, tenure)))
                else:
                    done = None
                due = (done or TODAY) + timedelta(days=rng.randint(-20, 40)) if status != "completed" else (done - timedelta(days=5))
            history.append({"employee_id": e["employee_id"], "course_code": code, "completion_status": status,
                            "completion_date": done.isoformat() if done else "", "due": due.isoformat() if due else "",
                            "assessment_score": score if score is not None else "", "tries": 1 if status == "completed" else 0})
    write("training_history", history, ["employee_id", "course_code", "completion_status", "completion_date", "due", "assessment_score", "tries"])
    write("employees", emps, list(emps[0]))
    print(f"Wrote {len(emps)} employees, {len(TRAININGS)} trainings across {len(by_site)} sites, {len(POSITIONS)} positions, "
          f"{len(sessions)} sessions, {len(history)} history rows to {OUT}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--staff", type=int, default=54, help="people spread across the lab")
    ap.add_argument("--big-team", type=int, default=85, help="extra people under manager@lanl.gov, e.g. 85")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default data/sample)")
    a = ap.parse_args()
    main(a.staff, a.big_team, a.out)
