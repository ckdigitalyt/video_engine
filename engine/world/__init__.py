"""engine.world — the semantic planning layer (v0.3, no Manim imports).

WorldState (entities/relationships/forces/signals/paths/states/measurements/
labels/facts) -> representation selection -> semantic actions -> story
templates + hero mechanism -> per-beat visual explanation scoring.
"""

from engine.world.actions import (
    ACTION_REGISTRY, ALL_ACTIONS, Action, ActionSpec, resolve,
    unknown_actions,
)
from engine.world.knowledge import (
    ResearchResult, build_world, known_topic, research,
)
from engine.world.representations import (
    MANIM_REPS, RepType, Representation, is_kinetic_text_only,
    select_representation,
)
from engine.world.scoring import (
    ExplanationReport, score_beat, score_beatsheet,
)
from engine.world.story_templates import (
    ROLE_INTENTS, TEMPLATES, StoryPlan, StoryTemplate, hero_for,
    select_template,
)
from engine.world.world_model import (
    ENTITY_TYPES, REL_KINDS, SIGNAL_KINDS, CameraFocus, Entity, EntityType,
    Fact, Force, HeroMechanism, Label, Measurement, Path, Relationship,
    Signal, State, WorldState,
)

__all__ = [
    "ACTION_REGISTRY", "ALL_ACTIONS", "Action", "ActionSpec",
    "CameraFocus", "Entity", "EntityType", "Fact", "Force",
    "HeroMechanism", "Label", "Measurement", "Path", "Relationship",
    "RepType", "Representation", "ResearchResult", "Signal", "State",
    "StoryPlan", "StoryTemplate", "WorldState",
    "build_world", "hero_for", "is_kinetic_text_only", "known_topic",
    "resolve", "research", "score_beat", "score_beatsheet",
    "select_representation", "select_template", "unknown_actions",
]
