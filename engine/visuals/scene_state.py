"""SceneState — persistent semantic object/lifecycle model (directive §3–§5).

The core correctness fix: the renderer previously treated every beat as a
blank slate and simply "added" new objects, causing accumulation and
overlap.  This module gives every semantic object a lifecycle:

    created once  -> transformed repeatedly -> removed when its role ends

Each object knows:
    - its semantic id (e.g. number_main, digit_A, equation, attractor)
    - what Mobject represents it (the physical Manim object)
    - whether it is persistent or temporary
    - whether it is entering / updating / exiting this beat
    - the layout ZONE it occupies (Top/Center/Bottom/...)

Every beat produces an explicit ENTER / UPDATE / EXIT record so visual
continuity bugs are diagnosable from the emitted scene_state_log.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class Zone(str, Enum):
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    FOCUS = "focus"
    SUPPORT = "support"


class Lifecycle(str, Enum):
    ENTER = "enter"
    UPDATE = "update"
    EXIT = "exit"
    PERSIST = "persist"


@dataclass
class SemanticObject:
    """A persistent semantic object on stage with its physical Mobject."""
    id: str
    obj_type: str                # number_main | digit | equation | result | attractor | headline | ...
    value: str = ""
    zone: Zone = Zone.CENTER
    persistent: bool = True
    temporary: bool = False
    mobject: Any = None          # Manim Mobject (opaque handle)
    # enter/update/exit bookkeeping
    last_beat: Optional[str] = None
    entered_beat: Optional[str] = None
    exit_beat: Optional[str] = None
    update_ops: list[dict] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "type": self.obj_type,
            "value": self.value,
            "zone": self.zone.value,
            "persistent": self.persistent,
            "temporary": self.temporary,
            "entered_beat": self.entered_beat,
            "last_beat": self.last_beat,
            "exit_beat": self.exit_beat,
        }


@dataclass
class BeatLifecycleRecord:
    """One beat's explicit enter/update/exit record (for scene_state_log)."""
    beat_id: str
    entering: list[dict] = field(default_factory=list)
    updating: list[dict] = field(default_factory=list)
    exiting: list[dict] = field(default_factory=list)
    persisting: list[dict] = field(default_factory=list)


class SceneState:
    """Tracks every semantic object on stage across beats.

    The scene (a Manim Scene) owns the Mobjects; SceneState owns the
    semantics.  The compiler consults SceneState on every beat to decide
    which objects to ENTER (create), UPDATE (transform in place), or EXIT
    (fade/remove), so nothing ever piles up by accident.
    """

    def __init__(self) -> None:
        self.objects: dict[str, SemanticObject] = {}
        self.log: list[BeatLifecycleRecord] = []
        self._seq = 0

    # ── discovery ──────────────────────────────────────────────────────
    def get(self, oid: str) -> Optional[SemanticObject]:
        return self.objects.get(oid)

    def active(self) -> list[SemanticObject]:
        """Objects currently on stage (entered and not yet exited)."""
        return [o for o in self.objects.values() if o.exit_beat is None]

    def ids(self) -> list[str]:
        return [o.id for o in self.active()]

    def _current_beat_id(self) -> Optional[str]:
        """Beat id of the record currently being filled (None before any
        begin_beat).  Used so enter/exit attribute the RIGHT beat instead of
        the placeholder "now" (which begin_beat would otherwise resolve one
        beat late)."""
        rec = getattr(self, "_current", None)
        return rec.beat_id if rec is not None else None

    # ── lifecycle helpers ──────────────────────────────────────────────
    def enter(self, oid: str, obj_type: str, value: str = "",
              zone: Zone = Zone.CENTER, persistent: bool = True,
              mobject: Any = None) -> SemanticObject:
        """Declare an object entering the stage this beat."""
        self._seq += 1
        obj = SemanticObject(
            id=oid, obj_type=obj_type, value=value, zone=zone,
            persistent=persistent, temporary=not persistent,
            mobject=mobject, entered_beat=self._current_beat_id() or "now",
        )
        self.objects[oid] = obj
        return obj

    def update(self, oid: str, op: dict, value: Optional[str] = None,
               mobject: Any = None) -> Optional[SemanticObject]:
        """Declare an object updating in place this beat.  Returns None if
        the object does not exist (compiler must treat as a bug -> fail)."""
        obj = self.objects.get(oid)
        if obj is None:
            return None
        obj.update_ops.append(op)
        if value is not None:
            obj.value = value
        if mobject is not None:
            obj.mobject = mobject
        return obj

    def exit(self, oid: str) -> Optional[SemanticObject]:
        """Declare an object exiting the stage at this beat."""
        obj = self.objects.get(oid)
        if obj is not None:
            obj.exit_beat = self._current_beat_id() or "now"
        return obj

    def zone_for(self, oid: str) -> Zone:
        obj = self.objects.get(oid)
        return obj.zone if obj else Zone.CENTER

    # ── per-beat record ────────────────────────────────────────────────
    def begin_beat(self, beat_id: str) -> None:
        # move "now" bookkeeping into this beat
        for o in self.objects.values():
            if o.entered_beat == "now":
                o.entered_beat = beat_id
            if o.exit_beat == "now":
                o.exit_beat = beat_id
            if o.last_beat != beat_id:
                o.last_beat = beat_id
        self.log.append(BeatLifecycleRecord(beat_id=beat_id))
        self._current = self.log[-1]

    def _record(self, kind: str, obj: SemanticObject) -> None:
        rec = self._current
        if rec is None:
            return
        snap = obj.snapshot()
        snap["at_beat"] = len(self.log)
        if kind == "enter":
            rec.entering.append(snap)
        elif kind == "update":
            rec.updating.append(snap)
        elif kind == "exit":
            rec.exiting.append(snap)
        else:
            rec.persisting.append(snap)

    def record_enter(self, oid: str) -> None:
        obj = self.objects.get(oid)
        if obj:
            self._record("enter", obj)

    def record_update(self, oid: str) -> None:
        obj = self.objects.get(oid)
        if obj:
            self._record("update", obj)

    def record_exit(self, oid: str) -> None:
        obj = self.objects.get(oid)
        if obj:
            self._record("exit", obj)

    def record_persist(self) -> None:
        for obj in self.active():
            self._record("persist", obj)

    # ── diagnostics ────────────────────────────────────────────────────
    def to_log(self) -> list[dict]:
        return [
            {
                "beat_id": r.beat_id,
                "entering": r.entering,
                "updating": r.updating,
                "exiting": r.exiting,
                "persisting": r.persisting,
            }
            for r in self.log
        ]

    def write_log(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_log(), indent=2), encoding="utf-8")
        return out

    def object_counts(self) -> dict:
        return {
            "enters": sum(len(r.entering) for r in self.log),
            "updates": sum(len(r.updating) for r in self.log),
            "exits": sum(len(r.exiting) for r in self.log),
        }

    # ── conflict / overlap guard ───────────────────────────────────────
    def zone_conflicts(self) -> list[str]:
        """Detect two non-overlapping-legal objects claiming the same zone
        (a cheap semantic overlap check; the frame-level check is separate)."""
        from collections import defaultdict
        per_zone: dict[str, list[str]] = defaultdict(list)
        for o in self.active():
            per_zone[o.zone.value].append(o.id)
        conflicts: list[str] = []
        for zone, ids in per_zone.items():
            focal = [i for i in ids if i in ("number_main", "attractor", "result")]
            if len(ids) > 1 and len(focal) <= 1:
                # legal for a focal + support to share; flag 2+ non-support
                supports = {"headline", "subtitle", "equation", "descending",
                            "ascending"}
                non_support = [i for i in ids if i not in supports]
                if len(non_support) > 1:
                    conflicts.append(f"zone '{zone}' has multiple focal objects: {ids}")
        return conflicts
