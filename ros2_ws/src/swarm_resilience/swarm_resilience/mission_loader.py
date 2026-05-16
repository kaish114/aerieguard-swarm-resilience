import json
from pathlib import Path
from typing import Any, Dict, List


REQUIRED_KEYS = {"mission_id", "version", "waypoints", "heartbeat_timeout_ms", "coordination_rules"}


class MissionLoadError(Exception):
    pass


def load_mission(path: str) -> Dict[str, Any]:
    """Load and validate mission_state.json. Raises MissionLoadError on failure."""
    p = Path(path)
    if not p.exists():
        raise MissionLoadError(f"Mission file not found: {path}")

    with p.open() as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise MissionLoadError(f"Invalid JSON in {path}: {exc}") from exc

    missing = REQUIRED_KEYS - set(data.keys())
    if missing:
        raise MissionLoadError(f"Mission file missing keys: {missing}")

    if not isinstance(data["waypoints"], list) or len(data["waypoints"]) == 0:
        raise MissionLoadError("Mission must have at least one waypoint")

    for wp in data["waypoints"]:
        for field in ("index", "lat", "lon", "alt_m"):
            if field not in wp:
                raise MissionLoadError(f"Waypoint missing field '{field}': {wp}")

    return data


def get_waypoints(mission: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted(mission["waypoints"], key=lambda w: w["index"])


def get_timeout_ms(mission: Dict[str, Any]) -> int:
    return int(mission["heartbeat_timeout_ms"])


def get_min_quorum(mission: Dict[str, Any]) -> int:
    return int(mission["coordination_rules"]["min_election_quorum"])
