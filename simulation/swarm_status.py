#!/usr/bin/env python3
"""
Terminal dashboard for swarm state.
Reads /tmp/progress_drone_*.json and /tmp/swarm_leader.txt written by the running nodes.
Usage: python3 simulation/swarm_status.py
"""
import json
import time
from pathlib import Path

DRONES = ["drone_1", "drone_2", "drone_3"]
CLEAR = "\033[2J\033[H"
BOLD = "\033[1m"
RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"


def read_progress(drone_id: str) -> dict | None:
    path = Path(f"/tmp/progress_{drone_id}.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def read_leader() -> str | None:
    path = Path("/tmp/swarm_leader.txt")
    if not path.exists():
        return None
    content = path.read_text().strip()
    return content if content else None


def read_jammed() -> bool:
    return Path("/tmp/swarm_jam_flag").exists()


def bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct:5.1f}%"


def render(leader: str | None, states: dict) -> str:
    lines = [
        f"{BOLD}{'─' * 60}{RESET}",
        f"{BOLD}  SWARM STATUS DASHBOARD{RESET}",
        f"{'─' * 60}",
        "",
    ]

    jammed = read_jammed()
    if leader:
        lines.append(f"  {YELLOW}★ Elected Leader:{RESET} {BOLD}{leader}{RESET}  (operator OFFLINE)")
    elif jammed:
        lines.append(f"  {RED}⚡ Operator:{RESET} {BOLD}JAMMED{RESET}  (election in progress...)")
    else:
        lines.append(f"  {GREEN}● Operator:{RESET} ONLINE  (heartbeat active)")
    lines.append("")

    for drone_id in DRONES:
        state = states.get(drone_id)
        if state is None:
            lines.append(f"  {drone_id:<10} {RED}OFFLINE{RESET}")
            continue

        role = state.get("role", "follower")
        battery = state.get("battery_pct", 0.0)
        wp = state.get("last_confirmed_waypoint", 0)
        pos = state.get("current_position", {})
        lat = pos.get("lat", 0.0)
        lon = pos.get("lon", 0.0)
        alt = pos.get("alt_m", 0.0)

        if role == "leader":
            role_str = f"{YELLOW}{BOLD}LEADER  {RESET}"
        elif role == "candidate":
            role_str = f"{CYAN}ELECTION{RESET}"
        else:
            role_str = f"{GREEN}follower{RESET}"

        lines.append(f"  {BOLD}{drone_id}{RESET}  {role_str}  WP:{wp}  {bar(battery)}")
        lines.append(f"             pos=({lat:.2f}, {lon:.2f}, {alt:.1f}m)")
        lines.append("")

    lines.append(f"{'─' * 60}")
    lines.append(f"  Updated: {time.strftime('%H:%M:%S')}   Ctrl-C to quit")
    return "\n".join(lines)


def main() -> None:
    print("Waiting for nodes to start (watching /tmp/progress_drone_*.json)...")
    try:
        while True:
            leader = read_leader()
            states = {d: read_progress(d) for d in DRONES}
            print(CLEAR + render(leader, states), flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()
