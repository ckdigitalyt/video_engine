"""
templates.py — Configurable story templates for the Story Planning Engine.

Each template defines a sequence of narrative roles (e.g. hook, context,
climax) that scenes should fulfill.  Templates are registered in YAML and
loaded at runtime via :func:`load_templates`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.utils.config import get_config


# ── Default templates (fallback when YAML is minimal or missing) ──────────

BUILTIN_TEMPLATES: dict[str, list[str]] = {
    "documentary": [
        "Hook — Open with a compelling question or startling fact",
        "Context — Provide background and set the stage",
        "Exploration — Dive deeper with evidence and examples",
        "Climax — Present the core revelation or key insight",
        "Conclusion — Summarise and leave the audience thinking",
    ],
    "problem_resolution": [
        "Problem — State the problem clearly",
        "Investigation — Explore causes and contributing factors",
        "Resolution — Present solutions or outcomes",
    ],
    "timeline": [
        "Opening — Set the scene and time period",
        "Event 1 — First major development",
        "Event 2 — Escalation or turning point",
        "Event 3 — Peak or resolution point",
        "Closing — Reflect on the story",
    ],
    "listicle": [
        "Intro — Hook the audience with a promise",
        "Point 1 — First key insight or example",
        "Point 2 — Second key insight or example",
        "Point 3 — Third key insight or example",
        "Outro — Recap and call to action",
    ],
}


# ── Template model ────────────────────────────────────────────────────────


@dataclass
class StoryTemplate:
    """A named story template with ordered scene roles.

    Attributes
    ----------
    name : str
        Template identifier (e.g. ``"documentary"``).
    roles : list[str]
        Role descriptions for each scene position.
    description : str
        Human-readable description of the template.
    """

    name: str
    roles: list[str]
    description: str = ""


TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "documentary": "Classic narrative arc: hook → context → exploration → climax → conclusion.",
    "problem_resolution": "Problem-solution structure: problem → investigation → resolution.",
    "timeline": "Chronological story: opening → escalating events → closing.",
    "listicle": "Enumeration format: intro → points → outro.",
}


# ── Public API ────────────────────────────────────────────────────────────


def load_templates() -> dict[str, StoryTemplate]:
    """Load story templates from YAML config, falling back to built-ins.

    Returns a dict mapping template name → ``StoryTemplate``.
    """
    yaml_templates: dict[str, Any] = get_config("planner.story_templates", {})

    if not yaml_templates:
        # Fall back to built-in defaults
        return {
            name: StoryTemplate(
                name=name,
                roles=roles,
                description=TEMPLATE_DESCRIPTIONS.get(name, ""),
            )
            for name, roles in BUILTIN_TEMPLATES.items()
        }

    result: dict[str, StoryTemplate] = {}
    for name, cfg in yaml_templates.items():
        if isinstance(cfg, dict):
            roles = cfg.get("roles", [])
            description = cfg.get("description", "")
        elif isinstance(cfg, list):
            roles = cfg
            description = TEMPLATE_DESCRIPTIONS.get(name, "")
        else:
            continue
        result[name] = StoryTemplate(name=name, roles=roles, description=description)
    return result


def get_template(name: Optional[str] = None) -> StoryTemplate:
    """Return the named template, or the configured default.

    Parameters
    ----------
    name : str, optional
        Template name.  If ``None``, uses ``planner.story_template`` from config.
    """
    if name is None:
        name = get_config("planner.story_template", "documentary")
    templates = load_templates()
    if name not in templates:
        name = "documentary"
    return templates[name]
