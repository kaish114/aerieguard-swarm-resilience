#!/usr/bin/env python3
"""
AerieGuard full mission simulation dashboard backend.
Run: python3 dashboard/server.py  →  open http://localhost:8080
"""
import asyncio
import json
import math
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ── Constants (change these to move the base) ──────────────────────────────────
BASE_LAT, BASE_LON         = 51.490, -0.135
DEFAULT_TGT_LAT, DEFAULT_TGT_LON = 51.520, -0.090

DRONE_OFFSETS = {
    "drone_1": ( 0.000,   0.000),   # lead / tip of triangle
    "drone_2": (-0.003,   0.004),   # back-right wing  ≈ 500 m offset
    "drone_3": (-0.003,  -0.004),   # back-left wing   ≈ 500 m offset
}
BATTERY_INIT = {"drone_1": 91.0, "drone_2": 78.0, "drone_3": 85.0}  # mirrors drone_agent init

SPEED      = 0.001    # deg/s ≈ 111 m/s
DRAIN      = 0.002    # battery % / s
ORBIT_R    = 0.0003   # deg ≈ 33m orbit at target
ORBIT_W    = 0.15     # rad/s

JAM_FLAG    = Path("/tmp/swarm_jam_flag")
LEADER_FILE = Path("/tmp/swarm_leader.txt")
PATH_SAMPLES = 30     # bezier curve sample points sent to frontend


# ── Mission state machine ──────────────────────────────────────────────────────
class Phase(str, Enum):
    DOCKED    = "DOCKED"
    DEPLOYING = "DEPLOYING"
    ON_TARGET = "ON_TARGET"
    RETURNING = "RETURNING"
    LANDED    = "LANDED"


def _bezier(t: float, p0: tuple, ctrl: tuple, p2: tuple) -> tuple[float, float]:
    mt = 1 - t
    return (
        mt * mt * p0[0] + 2 * mt * t * ctrl[0] + t * t * p2[0],
        mt * mt * p0[1] + 2 * mt * t * ctrl[1] + t * t * p2[1],
    )


def _ctrl_point(lat0: float, lon0: float, lat1: float, lon1: float,
                side: float = 1.0) -> tuple[float, float]:
    """Perpendicular offset from midpoint — creates the arc shape."""
    dlat, dlon = lat1 - lat0, lon1 - lon0
    dist = math.hypot(dlat, dlon)
    if dist == 0:
        return ((lat0 + lat1) / 2, (lon0 + lon1) / 2)
    offset = dist * 0.35
    return (
        (lat0 + lat1) / 2 + (-dlon / dist) * offset * side,
        (lon0 + lon1) / 2 + (dlat / dist) * offset * side,
    )


@dataclass
class MissionCtrl:
    phase:         Phase = Phase.DOCKED
    phase_start:   float = field(default_factory=time.time)
    target_lat:    float = DEFAULT_TGT_LAT
    target_lon:    float = DEFAULT_TGT_LON
    on_target_s:   int   = 30
    flight_s:      float = 0.0
    _ret_lat:      float = DEFAULT_TGT_LAT
    _ret_lon:      float = DEFAULT_TGT_LON
    _ret_flight_s: float = 0.0

    def __post_init__(self) -> None:
        self._recalc()

    def _recalc(self) -> None:
        d = math.hypot(self.target_lat - BASE_LAT, self.target_lon - BASE_LON)
        self.flight_s  = max(1.0, d / SPEED)
        # Outbound arcs left, return arcs right — forms a loop
        self._ctrl_out = _ctrl_point(BASE_LAT, BASE_LON, self.target_lat, self.target_lon,  1.0)
        self._ctrl_ret = _ctrl_point(self._ret_lat, self._ret_lon, BASE_LAT, BASE_LON, -1.0)

    def _elapsed(self) -> float:
        return time.time() - self.phase_start

    def flight_progress(self) -> float:
        e = self._elapsed()
        if self.phase == Phase.DEPLOYING:
            return min(1.0, e / self.flight_s)
        if self.phase == Phase.RETURNING:
            return min(1.0, e / max(1.0, self._ret_flight_s))
        return 0.0

    def sample_path(self, n: int = PATH_SAMPLES) -> list[dict]:
        """Return n bezier sample points for the outbound arc (frontend draws curve)."""
        p0 = (BASE_LAT, BASE_LON)
        p2 = (self.target_lat, self.target_lon)
        pts = []
        for i in range(n):
            t = i / (n - 1)
            lat, lon = _bezier(t, p0, self._ctrl_out, p2)
            pts.append({"lat": round(lat, 6), "lon": round(lon, 6)})
        return pts

    def sample_return_path(self, n: int = PATH_SAMPLES) -> list[dict]:
        """Return n bezier sample points for the return arc."""
        p0 = (self._ret_lat, self._ret_lon)
        p2 = (BASE_LAT, BASE_LON)
        pts = []
        for i in range(n):
            t = i / (n - 1)
            lat, lon = _bezier(t, p0, self._ctrl_ret, p2)
            pts.append({"lat": round(lat, 6), "lon": round(lon, 6)})
        return pts

    def launch(self, lat: float, lon: float, on_target_s: int) -> None:
        self.target_lat  = lat
        self.target_lon  = lon
        self.on_target_s = on_target_s
        self._ret_lat    = lat
        self._ret_lon    = lon
        self._recalc()
        self.phase       = Phase.DEPLOYING
        self.phase_start = time.time()

    def return_to_base(self) -> None:
        e = self._elapsed()
        if self.phase == Phase.DEPLOYING:
            t = min(1.0, e / self.flight_s)
            p0 = (BASE_LAT, BASE_LON)
            ctrl = self._ctrl_out
            p2 = (self.target_lat, self.target_lon)
            lat, lon = _bezier(t, p0, ctrl, p2)
            self._ret_lat = lat
            self._ret_lon = lon
        else:
            self._ret_lat = self.target_lat
            self._ret_lon = self.target_lon
        d = math.hypot(self._ret_lat - BASE_LAT, self._ret_lon - BASE_LON)
        self._ret_flight_s = max(1.0, d / SPEED)
        self._ctrl_ret     = _ctrl_point(self._ret_lat, self._ret_lon, BASE_LAT, BASE_LON, -1.0)
        self.phase         = Phase.RETURNING
        self.phase_start   = time.time()

    def tick(self) -> None:
        e = self._elapsed()
        if self.phase == Phase.DEPLOYING and e >= self.flight_s:
            self._ret_lat      = self.target_lat
            self._ret_lon      = self.target_lon
            self._ret_flight_s = self.flight_s
            self._ctrl_ret     = _ctrl_point(self._ret_lat, self._ret_lon, BASE_LAT, BASE_LON, -1.0)
            self.phase         = Phase.ON_TARGET
            self.phase_start   = time.time()
        elif self.phase == Phase.ON_TARGET and e >= self.on_target_s:
            self.phase       = Phase.RETURNING
            self.phase_start = time.time()
        elif self.phase == Phase.RETURNING and e >= self._ret_flight_s:
            self.phase       = Phase.LANDED
            self.phase_start = time.time()

    def position(self, drone_id: str) -> tuple[float, float]:
        dlat, dlon = DRONE_OFFSETS[drone_id]
        e = self._elapsed()

        if self.phase in (Phase.DOCKED, Phase.LANDED):
            return round(BASE_LAT + dlat, 7), round(BASE_LON + dlon, 7)

        if self.phase == Phase.DEPLOYING:
            t   = min(1.0, e / self.flight_s)
            lat, lon = _bezier(t, (BASE_LAT, BASE_LON), self._ctrl_out,
                               (self.target_lat, self.target_lon))
            return round(lat + dlat, 7), round(lon + dlon, 7)

        if self.phase == Phase.ON_TARGET:
            a   = e * ORBIT_W
            lat = self.target_lat + ORBIT_R * math.sin(a)
            lon = self.target_lon + ORBIT_R * math.cos(a)
            return round(lat + dlat, 7), round(lon + dlon, 7)

        if self.phase == Phase.RETURNING:
            t   = min(1.0, e / max(1.0, self._ret_flight_s))
            lat, lon = _bezier(t, (self._ret_lat, self._ret_lon), self._ctrl_ret,
                               (BASE_LAT, BASE_LON))
            return round(lat + dlat, 7), round(lon + dlon, 7)

        return round(BASE_LAT + dlat, 7), round(BASE_LON + dlon, 7)


# ── App state ──────────────────────────────────────────────────────────────────
mission  = MissionCtrl()
_start   = time.time()
_jammed  = False
_jam_at: Optional[float] = None


def _is_jammed() -> bool:
    return _jammed or JAM_FLAG.exists()


def _read_leader() -> Optional[str]:
    try:
        t = LEADER_FILE.read_text().strip() if LEADER_FILE.exists() else ""
        return t or None
    except OSError:
        return None


def _read_progress(drone_id: str) -> dict:
    """Read role and battery from the drone_agent's live progress file."""
    p = Path(f"/tmp/progress_{drone_id}.json")
    try:
        if p.exists():
            return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _signal_pct() -> float:
    if not _is_jammed():
        return 100.0
    return max(0.0, 100.0 - (time.time() - (_jam_at or time.time())) * 60.0)


def _build_state() -> dict:
    elapsed = time.time() - _start
    jammed  = _is_jammed()
    leader  = _read_leader()
    at_base = mission.phase in (Phase.DOCKED, Phase.LANDED)
    # Operator is offline when jammed OR when drones autonomously elected a leader
    link_lost = jammed or (leader is not None)

    drones = {}
    for did in DRONE_OFFSETS:
        lat, lon = mission.position(did)
        progress = _read_progress(did)

        # Battery: use live drone_agent value when ROS2 nodes are running,
        # fall back to dashboard's own simulation otherwise.
        if "battery_pct" in progress:
            battery = progress["battery_pct"]
        else:
            battery = max(0.0, BATTERY_INIT[did] - elapsed * DRAIN)

        role = progress.get("role", "follower")
        if leader == did:
            role = "leader"
        elif leader is None and role == "leader":
            role = "follower"  # RAFT leader file gone; ignore stale progress file

        drones[did] = {
            "lat": lat, "lon": lon,
            "battery_pct": round(battery, 1),
            "role": role,
        }

    return {
        "drones":          drones,
        "operator_online": not link_lost,
        "leader":          leader,
        "election_active": link_lost and leader is None,
        "signal_pct":      round(_signal_pct(), 1),
        "phase":           mission.phase,
        "flight_progress": round(mission.flight_progress(), 3),
        "firing":          mission.phase == Phase.ON_TARGET,
        "drones_at_base":  at_base,
        "base":            {"lat": BASE_LAT,           "lon": BASE_LON},
        "target":          {"lat": mission.target_lat, "lon": mission.target_lon},
        "flight_path":     mission.sample_path(),
        "return_path":     mission.sample_return_path(),
        "elapsed_s":       round(elapsed, 1),
        # Config values so UI doesn't need hardcoding
        "config": {
            "timeout_ms":    2000,
            "quorum":        "2 / 3",
            "orbit_r_m":     round(ORBIT_R * 111000),
            "speed_ms":      round(SPEED * 111000),
            "drain_pct_min": round(DRAIN * 60, 1),
        },
    }


# ── Lifecycle ──────────────────────────────────────────────────────────────────
async def _ticker() -> None:
    while True:
        mission.tick()
        await asyncio.sleep(0.5)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    # Clear stale jam/leader state left by previous server session
    JAM_FLAG.unlink(missing_ok=True)
    LEADER_FILE.unlink(missing_ok=True)
    asyncio.create_task(_ticker())
    yield


# ── Routes ─────────────────────────────────────────────────────────────────────
app = FastAPI(lifespan=_lifespan)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (Path(__file__).parent / "index.html").read_text()


@app.websocket("/ws")
async def ws_endpoint(sock: WebSocket) -> None:
    await sock.accept()
    try:
        while True:
            await sock.send_json(_build_state())
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, Exception):
        pass


class LaunchReq(BaseModel):
    target_lat:  float
    target_lon:  float
    on_target_s: int = 30


@app.post("/api/launch")
async def api_launch(req: LaunchReq) -> dict:
    mission.launch(req.target_lat, req.target_lon, req.on_target_s)
    return {"status": "deploying", "flight_s": round(mission.flight_s)}


@app.post("/api/return")
async def api_return() -> dict:
    mission.return_to_base()
    return {"status": "returning"}


@app.post("/api/jam")
async def api_jam() -> dict:
    global _jammed, _jam_at
    _jammed = True
    _jam_at = time.time()
    JAM_FLAG.write_text("1")
    return {"status": "jammed"}


@app.post("/api/restore")
async def api_restore() -> dict:
    global _jammed, _jam_at
    _jammed = False
    _jam_at = None
    JAM_FLAG.unlink(missing_ok=True)
    LEADER_FILE.unlink(missing_ok=True)
    return {"status": "restored"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
