"""Generate the synthetic Meridian Valley Health Plan data set.

Everything here is fictional:
  - SSNs use the 900-999 area range, which the US never issues.
  - NPIs start with 99, which real NPIs (starting with 1 or 2) never do.
  - Names, addresses, phone numbers and emails are random combinations.

Output (written next to this script):
  patients.csv (200), providers.csv (50), claims.csv (1,000), denials.csv (213)

Run:  python data/generate_data.py
The seed is fixed, so every run produces identical files.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 42
N_PATIENTS, N_PROVIDERS, N_CLAIMS, N_DENIALS = 200, 50, 1000, 213
OUT = Path(__file__).parent
TODAY = date(2026, 11, 1)
PAYER = "Meridian Valley Health Plan"

FIRST = ["Avery", "Jordan", "Riley", "Morgan", "Casey", "Quinn", "Taylor", "Jamie", "Rowan", "Skyler",
         "Elena", "Marcus", "Priya", "Daniel", "Grace", "Omar", "Lucia", "Henry", "Mei", "Samuel",
         "Nora", "Isaac", "Leah", "Mateo", "Hana", "Caleb", "Zoe", "Elijah", "Aisha", "Victor"]
LAST = ["Whitlock", "Okafor", "Brennan", "Castillo", "Lindqvist", "Harlow", "Nakamura", "Pruitt",
        "Delacroix", "Vance", "Moreau", "Abernathy", "Sorensen", "Kowalski", "Ibarra", "Fenwick",
        "Tran", "Galloway", "Rasmussen", "Achebe", "Montague", "Quill", "Esposito", "Blackwood"]
STREETS = ["Juniper Ln", "Copper Ridge Rd", "Willow Bend Dr", "Harbor View Ct", "Old Mill Rd",
           "Cedar Hollow Way", "Lantern St", "Bramble Ave", "Foxglove Pl", "Stonegate Blvd"]
CITIES = [("Meridian Falls", "OR", "97"), ("Clearwater Junction", "OR", "97"), ("Pine Hollow", "WA", "98"),
          ("Eastbrook", "WA", "98"), ("Silver Creek", "ID", "83")]
PLANS = ["HMO Silver", "PPO Gold", "HMO Bronze", "PPO Platinum"]

SPECIALTIES = ["Family Medicine", "Internal Medicine", "Cardiology", "Orthopedics", "Radiology",
               "Neurology", "Physical Therapy", "Endocrinology", "Pulmonology", "General Surgery"]
PRACTICE_SUFFIX = ["Medical Group", "Health Partners", "Clinic", "Associates", "Care Center"]

# CPT code, description, typical billed amount, specialty, needs prior auth
SERVICES = [
    ("99213", "Office visit, established patient, low complexity", 145, "Family Medicine", False),
    ("99214", "Office visit, established patient, moderate complexity", 210, "Internal Medicine", False),
    ("99204", "Office visit, new patient, moderate complexity", 285, "Internal Medicine", False),
    ("93000", "Electrocardiogram, complete", 95, "Cardiology", False),
    ("93306", "Echocardiogram, complete with Doppler", 1250, "Cardiology", True),
    ("72148", "MRI lumbar spine without contrast", 1850, "Radiology", True),
    ("70553", "MRI brain with and without contrast", 2900, "Radiology", True),
    ("71250", "CT chest without contrast", 980, "Radiology", True),
    ("73721", "MRI knee joint without contrast", 1650, "Radiology", True),
    ("97110", "Therapeutic exercise, each 15 minutes", 80, "Physical Therapy", False),
    ("27447", "Total knee arthroplasty", 32500, "Orthopedics", True),
    ("29881", "Knee arthroscopy with meniscectomy", 7800, "Orthopedics", True),
    ("95810", "Polysomnography (sleep study)", 2400, "Pulmonology", True),
    ("83036", "Hemoglobin A1c test", 45, "Endocrinology", False),
    ("80053", "Comprehensive metabolic panel", 60, "Internal Medicine", False),
    ("95910", "Nerve conduction studies, 7-8 studies", 1100, "Neurology", True),
]
ICD10 = {
    "72148": [("M54.50", "Low back pain, unspecified"), ("M51.26", "Lumbar disc displacement")],
    "70553": [("G43.909", "Migraine, unspecified"), ("R51.9", "Headache, unspecified")],
    "73721": [("M23.205", "Meniscus derangement, left knee"), ("M25.561", "Pain in right knee")],
    "27447": [("M17.11", "Primary osteoarthritis, right knee")],
    "29881": [("S83.241A", "Tear of medial meniscus, right knee, initial")],
    "93306": [("I50.9", "Heart failure, unspecified"), ("R01.1", "Cardiac murmur")],
    "93000": [("R00.2", "Palpitations"), ("I10", "Essential hypertension")],
    "71250": [("R91.1", "Solitary pulmonary nodule"), ("R05.9", "Cough, unspecified")],
    "95810": [("G47.33", "Obstructive sleep apnea")],
    "83036": [("E11.9", "Type 2 diabetes without complications")],
    "80053": [("E78.5", "Hyperlipidemia, unspecified"), ("I10", "Essential hypertension")],
    "95910": [("G56.01", "Carpal tunnel syndrome, right upper limb")],
    "97110": [("M54.50", "Low back pain, unspecified"), ("M25.561", "Pain in right knee")],
}
DEFAULT_DX = [("Z00.00", "General adult medical exam"), ("I10", "Essential hypertension"),
              ("E11.9", "Type 2 diabetes without complications")]

# CARC code, reason
CARC = {
    "CO-197": "Precertification/authorization/notification absent",
    "CO-50": "Not deemed a medical necessity by the payer",
    "CO-29": "The time limit for filing has expired",
    "CO-16": "Claim lacks information or has submission/billing errors",
    "CO-97": "Benefit included in payment for another service already adjudicated",
    "CO-18": "Exact duplicate claim/service",
    "CO-242": "Services not provided by network/primary care providers",
}


def rand_date(rng, start, end):
    return start + timedelta(days=rng.randint(0, (end - start).days))


def main():
    rng = random.Random(SEED)

    # ---------- patients ----------
    patients = []
    for i in range(1, N_PATIENTS + 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        city, state, zip_prefix = rng.choice(CITIES)
        dob = rand_date(rng, date(1940, 1, 1), date(2008, 12, 31))
        patients.append({
            "patient_id": f"M-{i:04d}",
            "member_id": f"MVH{rng.randint(1000000, 9999999)}",
            "first_name": first,
            "last_name": last,
            "date_of_birth": dob.isoformat(),
            "sex": rng.choice(["F", "M"]),
            "ssn": f"{rng.randint(900, 999)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}",
            "mrn": f"MRN{rng.randint(10000000, 99999999)}",
            "address": f"{rng.randint(100, 9899)} {rng.choice(STREETS)}",
            "city": city, "state": state,
            "zip": f"{zip_prefix}{rng.randint(100, 999)}",
            "phone": f"555-{rng.randint(200, 999)}-{rng.randint(1000, 9999)}",
            "email": f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@example.com",
            "payer": PAYER,
            "plan_type": rng.choice(PLANS),
        })

    # ---------- providers ----------
    providers = []
    for i in range(1, N_PROVIDERS + 1):
        spec = SPECIALTIES[(i - 1) % len(SPECIALTIES)]
        last = rng.choice(LAST)
        providers.append({
            "provider_id": f"PRV-{i:03d}",
            "npi": f"99{rng.randint(10000000, 99999999)}",
            "provider_name": f"Dr. {rng.choice(FIRST)} {last}",
            "specialty": spec,
            "practice_name": f"{last} {rng.choice(PRACTICE_SUFFIX)}",
            "city": rng.choice(CITIES)[0],
            "network_status": "out-of-network" if rng.random() < 0.2 else "in-network",
        })
    by_spec = {}
    for p in providers:
        by_spec.setdefault(p["specialty"], []).append(p)

    # ---------- claims ----------
    claims = []
    for i in range(N_CLAIMS):
        cpt, desc, base, spec, needs_pa = rng.choice(SERVICES)
        prov = rng.choice(by_spec[spec])
        pat = rng.choice(patients)
        svc = rand_date(rng, date(2025, 11, 1), date(2026, 9, 30))
        lag = rng.choice([3, 7, 14, 21, 30, 45, 60]) if rng.random() > 0.06 else rng.randint(95, 220)
        submitted = min(svc + timedelta(days=lag), TODAY)
        dx_code, dx_desc = rng.choice(ICD10.get(cpt, DEFAULT_DX))
        billed = round(base * rng.uniform(0.85, 1.25), 2)
        has_pa = needs_pa and rng.random() > 0.13
        claims.append({
            "claim_id": f"CLM-{100001 + i}",
            "patient_id": pat["patient_id"],
            "provider_id": prov["provider_id"],
            "payer": PAYER,
            "service_date": svc.isoformat(),
            "submitted_date": submitted.isoformat(),
            "cpt_code": cpt, "cpt_description": desc,
            "icd10_code": dx_code, "icd10_description": dx_desc,
            "billed_amount": billed,
            "allowed_amount": 0.0, "paid_amount": 0.0,
            "status": "",
            "prior_auth_number": f"PA-{rng.randint(100000, 999999)}" if has_pa else "",
            "_needs_pa": needs_pa, "_network": prov["network_status"], "_lag": (submitted - svc).days,
        })

    # Choose exactly N_DENIALS denied claims, preferring realistic reasons.
    def denial_reason(c):
        limit = 180 if c["_network"] == "in-network" else 90
        if c["_lag"] > limit:
            return "CO-29"
        if c["_needs_pa"] and not c["prior_auth_number"]:
            return "CO-197"
        if c["_network"] == "out-of-network" and rng.random() < 0.5:
            return "CO-242"
        return rng.choices(["CO-50", "CO-16", "CO-97", "CO-18"], weights=[45, 30, 15, 10])[0]

    strong = [c for c in claims if (c["_needs_pa"] and not c["prior_auth_number"])
              or c["_lag"] > (180 if c["_network"] == "in-network" else 90)]
    others = [c for c in claims if c not in strong]
    rng.shuffle(others)
    denied = (strong + others)[:N_DENIALS]
    denied_ids = {c["claim_id"] for c in denied}

    denials = []
    for c in claims:
        if c["claim_id"] in denied_ids:
            c["status"] = "denied"
            c["allowed_amount"] = 0.0
            c["paid_amount"] = 0.0
        else:
            c["status"] = "pending" if rng.random() < 0.07 else "paid"
            c["allowed_amount"] = round(c["billed_amount"] * rng.uniform(0.55, 0.85), 2)
            c["paid_amount"] = 0.0 if c["status"] == "pending" else round(c["allowed_amount"] * rng.uniform(0.8, 1.0), 2)

    for n, c in enumerate(sorted(denied, key=lambda x: x["claim_id"]), start=1):
        code = denial_reason(c)
        ddate = min(date.fromisoformat(c["submitted_date"]) + timedelta(days=rng.randint(10, 30)), TODAY)
        deadline = ddate + timedelta(days=180)
        appeal = rng.choices(["not appealed", "appeal filed", "overturned", "upheld"], weights=[50, 25, 15, 10])[0]
        denials.append({
            "denial_id": f"DEN-{n:04d}",
            "claim_id": c["claim_id"],
            "carc_code": code,
            "denial_reason": CARC[code],
            "denied_amount": c["billed_amount"],
            "denial_date": ddate.isoformat(),
            "appeal_status": appeal,
            "appeal_deadline": deadline.isoformat(),
        })

    def write(name, rows, drop_private=False):
        rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows] if drop_private else rows
        with open(OUT / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {name}: {len(rows)} rows")

    write("patients.csv", patients)
    write("providers.csv", providers)
    write("claims.csv", claims, drop_private=True)
    write("denials.csv", denials)


if __name__ == "__main__":
    main()
