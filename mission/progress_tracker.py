import json
import threading
import time
from typing import Any, Callable, Dict


class ProgressTracker:
    """Writes progress.json to disk every interval_s seconds."""

    def __init__(
        self,
        drone_id: str,
        mission_id: str,
        output_path: str,
        state_callback: Callable[[], Dict[str, Any]],
        interval_s: float = 0.5,
    ):
        self.drone_id = drone_id
        self.mission_id = mission_id
        self.output_path = output_path
        self.state_callback = state_callback
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                state = self.state_callback()
                progress = {
                    "drone_id": self.drone_id,
                    "mission_id": self.mission_id,
                    "last_confirmed_waypoint": state.get("last_confirmed_waypoint", 0),
                    "current_position": state.get(
                        "current_position", {"lat": 0.0, "lon": 0.0, "alt_m": 0.0}
                    ),
                    "battery_pct": state.get("battery_pct", 100),
                    "role": state.get("role", "follower"),
                    "timestamp": int(time.time()),
                }
                with open(self.output_path, "w") as f:
                    json.dump(progress, f, indent=2)
            except Exception as exc:
                print(f"[progress_tracker] write error: {exc}")
            self._stop.wait(self.interval_s)
