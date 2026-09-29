"""
Adversarial test stubs — story truth (VALIDATION_AND_TESTING.md §7).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.models import ValidatorStatus
from src.validators.story_truth import StoryTruthValidator
from src.evidence import load_and_validate_fixtures, build_evidence_index
from src.story import analyze_story


@pytest.fixture
def story_context():
    data_dir = Path("data")
    fixtures = load_and_validate_fixtures(data_dir)
    ev_index = build_evidence_index(fixtures)
    raw_story = json.loads((data_dir / "story_facts.json").read_text(encoding="utf-8"))
    story_map = {
        "characters": raw_story.get("characters", []),
        "relationships": raw_story.get("relationships", []),
    }
    return {
        "fixtures": fixtures,
        "ev_index": ev_index,
        "story_map": story_map,
        "story_facts": raw_story,
    }


def test_clickbait_forbidden_claim(story_context):
    """Tagline 'A murder no one can forget' → STORY_FORBIDDEN_CLAIM."""
    validator = StoryTruthValidator()
    plan = {
        "tagline": "A murder no one can forget",
        "segments": [],
    }
    res_dict = validator.validate(
        plan,
        story_context["story_map"],
        story_context["story_facts"],
        story_context["ev_index"],
    )
    plan_res = res_dict["__plan__"]
    assert plan_res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in plan_res.errors]
    assert "STORY_FORBIDDEN_CLAIM" in error_codes


def test_clickbait_relation_mismatch(story_context):
    """Claim husband_wife between Dharam/Sunita → STORY_RELATION_MISMATCH."""
    validator = StoryTruthValidator()
    seg = {
        "segment_id": "seg_fake_rel",
        "video": "scene_02",
        "reason": "Dharam and Sunita married couple",
        "claims": [
            {
                "type": "relationship",
                "characters": ["char_dharam", "char_sunita"],
                "relation": "husband_wife",
                "supported_by": ["scene:scene_02"],
            }
        ],
    }
    res = validator.validate_segment(
        seg,
        story_context["story_map"],
        story_context["story_facts"],
        story_context["ev_index"],
    )
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "STORY_RELATION_MISMATCH" in error_codes


def test_unsupported_claim(story_context):
    """Claim with no supporting evidence ref → STORY_UNSUPPORTED_CLAIM."""
    validator = StoryTruthValidator()
    seg = {
        "segment_id": "seg_unsup",
        "video": "scene_02",
        "reason": "Dramatic claim",
        "claims": [
            {
                "type": "event",
                "value": "Sunita betrayed Dharam",
                "supported_by": [],  # Empty supported_by!
            }
        ],
    }
    res = validator.validate_segment(
        seg,
        story_context["story_map"],
        story_context["story_facts"],
        story_context["ev_index"],
    )
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "STORY_UNSUPPORTED_CLAIM" in error_codes
