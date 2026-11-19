"""ICD-10-CM business rules: parsing, code updates, validity, billability, Excludes1.
No AI model here, so these rules can be tested on their own."""
import json
import re

import simple_icd_10_cm as cm

CODE_RE = re.compile(r"[A-Z]\d[0-9A-Z](?:\.[0-9A-Z]{1,4})?")

# CodiEsp labels are from 2018; these codes were split or changed since then
CODE_UPDATES = {
    "M54.5":  ("M54.50", "Updated from M54.5 (split in newer ICD-10-CM): confirm type of low back pain"),
    "R05":    ("R05.9",  "Updated from R05 (split): confirm acute/subacute/chronic cough if documented"),
    "R51":    ("R51.9",  "Updated from R51 (split): confirm headache type if documented"),
    "T14.8":  (None,     "T14.8 needs a 7th character: choose A (initial), D (follow-up) or S (late effect)"),
    "T14.90": (None,     "T14.90 needs a 7th character: choose A (initial), D (follow-up) or S (late effect)"),
}


def parse_codes(raw):
    """Model text -> list of code strings. Handles ```json fences and non-JSON answers."""
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    try:
        out = json.loads(raw.strip())
        if isinstance(out, list):
            codes = [c.get("code", "") if isinstance(c, dict) else str(c) for c in out]
            return [c.strip().upper() for c in codes if c]
    except json.JSONDecodeError:
        pass
    return CODE_RE.findall(raw.upper())


def describe(code):
    try:
        return cm.get_description(code)
    except Exception:
        return "(description not found)"


def _excludes1_prefixes(code):
    notes = list(cm.get_excludes1(code))
    for parent in cm.get_ancestors(code):
        notes += cm.get_excludes1(parent)
    found = []
    for note in notes:
        for group in re.findall(r"\(([^)]*)\)", note):
            found += CODE_RE.findall(group)
    return found


def check_codes(codes):
    """Apply code updates, then validity / billability / Excludes1 checks.
    Returns {"accepted": [...], "flagged": [...], "rejected": [...]} with descriptions and reasons."""
    updated, flagged, rejected, accepted, seen = [], [], [], [], set()

    for c in codes:
        c = c.strip().upper()
        if c in CODE_UPDATES:
            new, note = CODE_UPDATES[c]
            flagged.append({"item": c, "reason": note})
            if new is None:
                continue
            c = new
        if c not in seen:
            seen.add(c)
            updated.append(c)

    for c in updated:
        if not cm.is_valid_item(c):
            rejected.append({"code": c, "reason": "Not a real ICD-10-CM code"})
        elif not cm.is_leaf(c):
            rejected.append({"code": c, "reason": "Too vague to bill: needs a more specific code"})
        else:
            accepted.append({"code": c, "description": describe(c)})

    codes_ok = [a["code"] for a in accepted]
    done = set()
    for a in codes_ok:
        for b in codes_ok:
            pair = tuple(sorted((a, b)))
            if a != b and pair not in done and any(b.startswith(p) for p in _excludes1_prefixes(a)):
                done.add(pair)
                flagged.append({"item": f"{pair[0]} + {pair[1]}",
                                "reason": "Excludes1: should not be coded together"})

    return {"accepted": accepted, "flagged": flagged, "rejected": rejected}


if __name__ == "__main__":
    tests = [
        ["E11.9", "I10", "R05", "R51"],
        ["E11.22", "I12.7", "N18.3", "E11.22"],
        ["E11.9", "E10.9", "T14.90"],
    ]
    for t in tests:
        print(t)
        print(json.dumps(check_codes(t), indent=1))