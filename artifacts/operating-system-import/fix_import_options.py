#!/usr/bin/env python3
"""Post-process imported questions: fix two-column layout option issues and audit quality."""
import json, logging, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fix-options")

# Option regex patterns
_OPTION_RE = re.compile(r'^([A-Da-d])[.、．\s]\s*(.*?)$')
_RAW_OPTION_RE = re.compile(r'^([A-Da-d])[.、．]\s*(.*)')

def verify_question(raw_data: dict, parsed_options: dict) -> dict:
    """Verify and fix options by comparing with raw OCR text."""
    raw_text = raw_data.get("raw_text", "")
    if not raw_text:
        return {"status": "no_raw_text", "fixes": []}

    # Extract all option-like lines from raw text
    raw_option_lines = []
    for line in raw_text.split("\n"):
        m = _RAW_OPTION_RE.match(line.strip())
        if m:
            key = m.group(1).upper()
            val = m.group(2).strip()
            raw_option_lines.append((key, val))

    # Extract options currently in parsed_options
    current_options = {}
    if isinstance(parsed_options, dict):
        current_options = {k.upper(): v for k, v in parsed_options.items()}

    fixes = []
    status = "ok"

    if len(raw_option_lines) < 2:
        return {"status": "too_few_raw_options", "raw_count": len(raw_option_lines), "fixes": []}

    # Build correct options from raw text, handling two-column layout
    # In two-column layout, OCR reads in wrong order (A, C, B, D or similar)
    # We need to detect the layout and re-map

    # Strategy: re-extract from raw text with position awareness
    # For standard layout, scan the raw text and assign each detected option to its letter key
    raw_by_key = {}
    for k, v in raw_option_lines:
        if k not in raw_by_key:  # first occurrence wins
            raw_by_key[k] = v

    # Also detect options that follow the pattern "A.xxx B.xxx" (inline)
    inline_options = {}
    for line in raw_text.split("\n"):
        # Match "A.xxx  B.yyy  C.zzz  D.www" inline pattern
        parts = re.findall(r'([A-Da-d])[.、．\s]\s*([^\d][^A-D\n]{1,60}?)(?=\s+[A-Da-d][.、．\s]|\s*$)', line)
        if parts and len(parts) >= 2:
            for k, v in parts:
                if k.upper() not in inline_options:
                    inline_options[k.upper()] = v.strip()

    # Determine best option mapping
    if inline_options and len(inline_options) >= 4:
        best_options = inline_options
    elif raw_by_key and len(raw_by_key) >= 4:
        best_options = raw_by_key
    elif raw_by_key:
        best_options = raw_by_key
    else:
        best_options = {}

    # Compare with current options
    if best_options:
        for key in sorted(best_options.keys()):
            current_val = current_options.get(key, "")
            raw_val = best_options.get(key, "")
            if current_val != raw_val:
                fixes.append({
                    "key": key,
                    "before": current_val,
                    "after": raw_val,
                    "reason": "Option value mismatch with raw OCR text",
                })

    # Check for missing options
    for key in "ABCD":
        if key not in current_options:
            if key in best_options:
                fixes.append({
                    "key": key,
                    "before": "(missing)",
                    "after": best_options[key],
                    "reason": f"Missing option {key}, recovered from raw text",
                })
            else:
                status = f"missing_option_{key}"

    if fixes:
        status = "fixed"
    elif len(current_options) < 2:
        status = "no_options_found"

    return {
        "status": status,
        "raw_options_found": len(raw_option_lines),
        "raw_by_key": raw_by_key,
        "inline_options": inline_options,
        "current_options": current_options,
        "best_options": best_options,
        "fixes": fixes,
    }
