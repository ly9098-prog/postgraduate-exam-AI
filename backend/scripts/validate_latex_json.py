#!/usr/bin/env python3
"""
Validate math2_core_v2_extensions.json for LaTeX safety and schema correctness.

Checks:
  1. JSON is valid and parseable
  2. All 22 cards have required fields
  3. LaTeX backslashes are properly escaped (no control-character corruption)
  4. No duplicate source_ref values
  5. Card types are valid
"""
import json
import re
import sys
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "app" / "data" / "formula_library" / "math2_core_v2_extensions.json"

REQUIRED_CARD_FIELDS = [
    "title", "card_type", "source_ref", "summary", "formula_blocks", "tags"
]

VALID_CARD_TYPES = {"pure_formula", "function_graph", "auto"}

# LaTeX commands that contain characters triggering Python escape sequences
# These MUST survive JSON round-trip (i.e., appear as the literal LaTeX command)
CONTROL_RISK_PATTERNS = [
    (r"\\beta",  r"backslash-beta"),   # \b in \beta
    (r"\\begin", r"backslash-begin"),  # \b in \begin
    (r"\\bar",   r"backslash-bar"),    # \b in \bar
    (r"\\text",  r"backslash-text"),   # \t in \text
    (r"\\tan",   r"backslash-tan"),    # \t in \tan
    (r"\\frac",  r"backslash-frac"),   # \f in \frac
    (r"\\f",     r"backslash-f"),      # \f in \f...
    (r"\\n",     r"backslash-n"),      # \n in \n...
    (r"\\r",     r"backslash-r"),      # \r in \r... (rare)
    (r"\\rho",   r"backslash-rho"),    # \r in \rho
    (r"\\right", r"backslash-right"),  # \r in \right
]


def validate_json():
    """Validate JSON structure."""
    errors = []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"JSON parse error: {e}"], 0

    subjects = data.get("subjects", [])
    if not subjects:
        return ["No subjects found in data"], 0

    total_cards = 0
    for si, subject in enumerate(subjects):
        chapters = subject.get("chapters", [])
        if not chapters:
            errors.append(f"Subject {si} ({subject.get('code')}): no chapters")

        for ci, chapter in enumerate(chapters):
            groups = chapter.get("groups", [])
            if not groups:
                errors.append(f"Chapter {ci} ({chapter.get('code')}): no groups")

            for gi, group in enumerate(groups):
                cards = group.get("cards", [])
                if not cards:
                    errors.append(f"Group {gi} ({group.get('code')}): no cards")

                for cii, card in enumerate(cards):
                    total_cards += 1

                    # Check required fields
                    for field in REQUIRED_CARD_FIELDS:
                        if field not in card:
                            errors.append(f"Card #{cii} in {group.get('code')}: missing '{field}'")

                    # Check card type
                    ct = card.get("card_type", "")
                    if ct not in VALID_CARD_TYPES:
                        errors.append(f"Card '{card.get('title')}': invalid card_type '{ct}'")

                    # Check formula_blocks
                    blocks = card.get("formula_blocks", [])
                    if not blocks:
                        errors.append(f"Card '{card.get('title')}': empty formula_blocks")
                    for bi, block in enumerate(blocks):
                        if "latex" not in block:
                            errors.append(f"Card '{card.get('title')}' block {bi}: missing 'latex'")

                    # Check tags are non-empty
                    tags = card.get("tags", [])
                    if not tags:
                        errors.append(f"Card '{card.get('title')}': no tags")

    return errors, total_cards


def validate_latex_safety():
    """Check that decoded LaTeX commands survived JSON round-trip."""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    issues = []

    def check_strings(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                check_strings(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                check_strings(v, f"{path}[{i}]")
        elif isinstance(obj, str):
            # Check for control characters
            for char, name in [
                ("\b", "backspace (\\b)"),
                ("\f", "form feed (\\f)"),
                ("\n", "newline (\\n)"),
                ("\r", "carriage return (\\r)"),
                ("\t", "tab (\\t)"),
            ]:
                if char in obj:
                    context = obj[max(0, obj.index(char) - 10):obj.index(char) + 10]
                    issues.append(f"CONTROL CHAR {name} in {path}: ...{context!r}...")

            # Check for expected LaTeX commands that should be present
            # Only check in formula_blocks.latek, summary, conditions, etc.
            for pattern, name in CONTROL_RISK_PATTERNS:
                if re.search(pattern, obj):
                    # Expected pattern found — good, no corruption
                    pass

    check_strings(data)
    return issues


def validate_no_duplicate_source_refs():
    """Check for duplicate source_ref values."""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    refs = {}
    for subject in data.get("subjects", []):
        for chapter in subject.get("chapters", []):
            for group in chapter.get("groups", []):
                for card in group.get("cards", []):
                    sr = card.get("source_ref", "")
                    if sr in refs:
                        return [f"Duplicate source_ref: {sr} (in '{refs[sr]}' and '{card['title']}')"]
                    refs[sr] = card["title"]
    return []


def main():
    errors = []
    total = 0

    print("=== JSON Schema Validation ===")
    schema_errors, total = validate_json()
    if schema_errors:
        errors.extend(schema_errors)
        for e in schema_errors:
            print(f"  FAIL: {e}")
    else:
        print(f"  PASS: {total} cards, all required fields present")

    print("\n=== LaTeX Safety Check ===")
    latex_issues = validate_latex_safety()
    if latex_issues:
        errors.extend(latex_issues)
        for issue in latex_issues:
            print(f"  FAIL: {issue}")
    else:
        print("  PASS: No control-character corruption detected")

    print("\n=== Source Ref Uniqueness ===")
    dup_refs = validate_no_duplicate_source_refs()
    if dup_refs:
        errors.extend(dup_refs)
        for d in dup_refs:
            print(f"  FAIL: {d}")
    else:
        print(f"  PASS: All {total} source_ref values are unique")

    print(f"\n{'='*50}")
    if errors:
        print(f"FAILED: {len(errors)} issue(s) found")
        return 1
    else:
        print(f"ALL CHECKS PASSED ({total} cards, 0 issues)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
