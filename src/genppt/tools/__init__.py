"""GenPPT tools package."""

from .validators import (
    validate_brief,
    check_narrative_arc,
    check_content_density,
    check_cross_page_duplication,
    check_cross_page_contradiction,
    check_terminology_consistency,
    check_layout_variety,
    check_dark_light_rhythm,
    quantify_data_presence,
    rule_check,
    resolve_structure,
)
from .scorers import score_slide_density, aggregate_scores
from .visual_review import run_visual_review, capture_slide_images, review_slide_visual

__all__ = [
    "validate_brief",
    "check_narrative_arc",
    "check_content_density",
    "check_cross_page_duplication",
    "check_terminology_consistency",
    "check_layout_variety",
    "check_dark_light_rhythm",
    "quantify_data_presence",
    "rule_check",
    "resolve_structure",
    "score_slide_density",
    "aggregate_scores",
    "run_visual_review",
    "capture_slide_images",
    "review_slide_visual",
]
