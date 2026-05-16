"""
Scenario runner: injects operator link loss at T+inject_after_s seconds.
Records election convergence time and writes to results/convergence_benchmarks.json.

Usage:
    python3 simulation/scenario.py --inject-after 30 --run-id run_001
"""
import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


RESULTS_PATH = Path("results/convergence_benchmarks.json")


def _load_results() -> list:
    if RESULTS_PATH.exists():
        with RESULTS_PATH.open() as f:
            return json.load(f)
    return []


def _save_result(run_id: str, inject_at: float, election_complete_at: float | None,
                 leader: str | None) -> None:
    results = _load_results()
    entry = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "link_loss_injected_at_s": inject_at,
        "election_complete_at_s": election_complete_at,
        "convergence_time_ms": round((election_complete_at - inject_at) * 1000, 1)
            if election_complete_at else None,
        "elected_leader": leader,
        "success": election_complete_at is not None and (election_complete_at - inject_at) < 3.0,
    }
    results.append(entry)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w") as f:
        json.dump(results, f, indent=2)
    print(f"[scenario] Result saved: convergence={entry['convergence_time_ms']}ms "
          f"leader={leader} success={entry['success']}")


def run_scenario(inject_after_s: float, run_id: str, operator_pid: int | None = None) -> None:
    """
    Main scenario logic.
    If operator_pid is None, looks up the operator_node process by name.
    """
    leader_file = Path("/tmp/swarm_leader.txt")
    if leader_file.exists():
        leader_file.unlink()
        print("[scenario] Cleared stale /tmp/swarm_leader.txt")

    print(f"[scenario] Waiting {inject_after_s}s before injecting link loss...")
    time.sleep(inject_after_s)

    inject_at = time.time()
    print(f"[scenario] T+{inject_after_s}s: Injecting link loss (SIGTERM → operator_node)")

    if operator_pid:
        try:
            os.kill(operator_pid, signal.SIGTERM)
        except ProcessLookupError:
            print(f"[scenario] operator_pid {operator_pid} not found — already dead?")
    else:
        result = subprocess.run(
            ["pgrep", "-f", "operator_node"],
            capture_output=True, text=True
        )
        pids = result.stdout.strip().split()
        if not pids:
            print("[scenario] No operator_node process found")
            _save_result(run_id, inject_at, None, None)
            return
        for pid in pids:
            os.kill(int(pid), signal.SIGTERM)
        print(f"[scenario] SIGTERM sent to operator_node pids: {pids}")

    election_complete_at = None
    leader = None

    deadline = time.time() + 6.0
    while time.time() < deadline:
        if leader_file.exists():
            content = leader_file.read_text().strip()
            if content:
                election_complete_at = time.time()
                leader = content
                print(f"[scenario] Leader elected: {leader} "
                      f"(convergence: {(election_complete_at - inject_at)*1000:.0f}ms)")
                break
        time.sleep(0.05)

    if not election_complete_at:
        print("[scenario] Election did not complete within 6 seconds")

    _save_result(run_id, inject_at, election_complete_at, leader)


def main() -> None:
    parser = argparse.ArgumentParser(description="Swarm link loss scenario runner")
    parser.add_argument("--inject-after", type=float, default=30.0,
                        help="Seconds after start to inject link loss")
    parser.add_argument("--run-id", default=f"run_{int(time.time())}",
                        help="Unique identifier for this run")
    parser.add_argument("--operator-pid", type=int, default=None,
                        help="PID of operator_node process (optional)")
    args = parser.parse_args()

    run_scenario(args.inject_after, args.run_id, args.operator_pid)


if __name__ == "__main__":
    main()
