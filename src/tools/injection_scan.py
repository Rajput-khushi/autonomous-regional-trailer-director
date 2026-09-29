"""
tools/injection_scan.py — Prompt injection detection for scene source text.
Authority: AI_SYSTEM_SPEC.md §2, SUMMARY.md §20, ARCHITECTURE.md §14.

Scene descriptions, subtitles and other episode-derived text are DATA,
not system instructions.  This scanner detects instruction-like patterns
and flags them so they are redacted from the LLM view.

The original text is retained in the evidence index for audit.

Phase 0: stub only.
"""

from __future__ import annotations

import re

# Patterns that suggest the text contains instruction-like content.
# Deliberately conservative (may over-flag; humans review flagged scenes).
_INSTRUCTION_PATTERNS = [
    re.compile(r"\bignore\b.*\b(contract|rule|policy|constraint)\b", re.IGNORECASE),
    re.compile(r"\boverride\b.*\b(system|instruction|constraint)\b", re.IGNORECASE),
    re.compile(r"\byou (are|must|should|will)\b", re.IGNORECASE),
    re.compile(r"\b(disregard|forget|bypass|skip)\b.*\b(rule|check|validator)\b", re.IGNORECASE),
]

REDACTED_PLACEHOLDER = "[REDACTED_INSTRUCTION_LIKE_TEXT]"


from src.evidence import scan_for_injection, redact_injection


def scan_text(text: str) -> tuple[bool, str]:
    """
    Scan a piece of source-derived text for instruction-like patterns.
    Returns (flagged: bool, redacted_text: str).
    """
    detected, _ = scan_for_injection(text)
    if detected:
        return True, redact_injection(text)
    return False, text


def scan_scene(scene: dict) -> dict:
    """
    Scan all text fields in a scene record and return a copy with:
      - injection_scan_flag set to True if any match was found.
      - A redacted copy of the description/dialogue for the LLM view.
    """
    result = dict(scene)
    desc = scene.get("description", "")
    flagged, redacted = scan_text(desc)
    result["injection_scan_flag"] = flagged
    if flagged:
        result["description"] = redacted
    return result
