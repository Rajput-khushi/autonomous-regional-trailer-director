"""
src/validators/__init__.py
Exports the nine primary validators and the aggregate runner.
"""

from src.validators.scene_existence import SceneExistenceValidator
from src.validators.timecode import TimecodeValidator
from src.validators.rights import RightsValidator
from src.validators.spoiler import SpoilerValidator
from src.validators.story_truth import StoryTruthValidator
from src.validators.audience_safety import AudienceSafetyValidator
from src.validators.dialect import DialectConsistencyValidator
from src.validators.accessibility import AccessibilityValidator
from src.validators.budget import BudgetValidator
from src.validators.aggregate import run_validators, aggregate_trailer_status

__all__ = [
    "SceneExistenceValidator",
    "TimecodeValidator",
    "RightsValidator",
    "SpoilerValidator",
    "StoryTruthValidator",
    "AudienceSafetyValidator",
    "DialectConsistencyValidator",
    "AccessibilityValidator",
    "BudgetValidator",
    "run_validators",
    "aggregate_trailer_status",
]
