"""RViz marker layout for /ash_e/priority/markers (pure Python). The node turns these dict specs into Marker messages.

Frame = status.frame_id (camera optical frame; x right, y down, z forward). Per ranked candidate with a distance a text
label sits at its position; the target gets a sphere; a ranking legend sits at the frame origin. No TF is needed.
"""
from __future__ import annotations

from typing import Dict, List

from ash_e_core.types import Ineligible, SmokerState, TargetEvent, TargetStatus

from .convert import bearing_distance_to_xyz

NS_LABEL, NS_TARGET, NS_LEGEND = "candidate", "target", "ranking"
_STATE = {int(SmokerState.NONE): "none", int(SmokerState.HOLDING): "holding", int(SmokerState.SMOKING): "smoking"}
_WHY = {int(Ineligible.OK): "", int(Ineligible.NOT_CONFIRMED): "not confirmed", int(Ineligible.LOW_CONFIDENCE): "low conf",
        int(Ineligible.OUT_OF_RANGE): "out of range", int(Ineligible.COOLDOWN): "cooldown"}


def marker_specs(st: TargetStatus, max_candidates: int = 5) -> List[Dict]:
    """First spec is always a delete_all (so vanished candidates disappear); the rest are 'text' or 'sphere'."""
    specs: List[Dict] = [dict(kind="delete_all")]
    rows = []
    for i, c in enumerate(st.ranking[:max(0, int(max_candidates))]):
        is_target = st.has_target and c.track_id == st.target_id
        why = _WHY.get(int(c.ineligible_reason), "?")
        dist = "%.1fm" % c.distance_m if c.distance_m >= 0 else "no dist"
        row = "%s#%d %s %.2f %s%s" % (">" if is_target else " ", c.track_id, _STATE.get(int(c.state), "?"), c.score, dist,
                                       "" if c.eligible else " (%s)" % why)
        rows.append(row)
        xyz = bearing_distance_to_xyz(c.distance_m, c.bearing_rad)
        if xyz is not None:
            specs.append(dict(kind="text", ns=NS_LABEL, id=int(c.track_id), xyz=(xyz[0], xyz[1] - 0.5, xyz[2]),
                              text="%d. #%d %.2f" % (i + 1, c.track_id, c.score), scale=0.18,
                              rgba=(1.0, 1.0, 1.0, 1.0) if c.eligible else (0.6, 0.6, 0.6, 0.8)))
    if st.has_target:
        p = st.target_position
        specs.append(dict(kind="sphere", ns=NS_TARGET, id=0, xyz=(p.x, p.y, p.z), scale=0.35,
                          rgba=(1.0, 0.2, 0.2, 0.6) if st.target_visible else (1.0, 0.8, 0.0, 0.4)))
    head = "TARGET #%d" % st.target_id if st.has_target else "IDLE"
    if st.last_event != TargetEvent.NONE:
        head += "  [%s]" % TargetEvent(st.last_event).name
    if st.locked:
        head += "  LOCKED"
    specs.append(dict(kind="text", ns=NS_LEGEND, id=0, xyz=(0.0, -1.0, 0.0), scale=0.15, rgba=(0.9, 0.9, 0.2, 1.0),
                      text="\n".join([head] + rows)))
    return specs
