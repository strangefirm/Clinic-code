"""Claim export: turns an approved review into a claim-style XML file, after a final "scrubber" check.

The layout is modelled on the general shape of UAE e-claim submissions (a header, then claims with
Principal/Secondary diagnoses). It is a SIMPLIFIED DEMO format: it has not been validated against
any official payer schema, and all IDs are placeholders."""
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from app.rules import check_codes


def scrub(review):
    """Last check before a claim leaves the building. Returns a list of problems (empty = clean)."""
    problems = []
    codes = [d["code"] for d in review["diagnoses"]]
    principals = [d for d in review["diagnoses"] if d["type"] == "Principal"]
    if len(principals) != 1:
        problems.append("Claim must have exactly one Principal diagnosis")
    if len(codes) != len(set(codes)):
        problems.append("Duplicate diagnosis codes")
    result = check_codes(codes)
    for r in result["rejected"]:
        problems.append(f"{r['code']}: {r['reason']}")
    for f in result["flagged"]:
        if "Excludes1" in f["reason"]:
            problems.append(f"{f['item']}: {f['reason']}")
    return problems


def build_claim_xml(review):
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
    root = ET.Element("Claim.Submission")

    header = ET.SubElement(root, "Header")
    for tag, value in [("SenderID", "DEMO-PROVIDER"), ("ReceiverID", "DEMO-PAYER"),
                       ("TransactionDate", now), ("RecordCount", "1"), ("DispositionFlag", "TEST")]:
        ET.SubElement(header, tag).text = value

    claim = ET.SubElement(root, "Claim")
    ET.SubElement(claim, "ID").text = review["case_id"]
    ET.SubElement(claim, "ProviderID").text = "DEMO-PROVIDER"
    ET.SubElement(claim, "PayerID").text = "DEMO-PAYER"

    principal = [d for d in review["diagnoses"] if d["type"] == "Principal"]
    secondary = [d for d in review["diagnoses"] if d["type"] != "Principal"]
    for d in principal + secondary:                      # Principal first, by convention
        diag = ET.SubElement(claim, "Diagnosis")
        ET.SubElement(diag, "Type").text = d["type"]
        ET.SubElement(diag, "Code").text = d["code"]

    # traceability back to the audit trail (would be internal-only in a real submission)
    audit = ET.SubElement(claim, "AuditReference")
    ET.SubElement(audit, "ReviewID").text = str(review["id"])
    ET.SubElement(audit, "Coder").text = review["coder"]
    ET.SubElement(audit, "ModelVersion").text = review["model_version"]
    ET.SubElement(audit, "ApprovedAt").text = review["approved_at"]

    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)