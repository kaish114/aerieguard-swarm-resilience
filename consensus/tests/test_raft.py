import threading
import time
from typing import List, Optional

import pytest

from consensus.raft import RaftNode, Role, _pick_leader


# ── Unit tests (no ZMQ) ────────────────────────────────────────────────────────

class TestPickLeader:
    def test_highest_battery_wins(self):
        candidates = [
            {"drone_id": "drone_1", "battery_pct": 60},
            {"drone_id": "drone_2", "battery_pct": 85},
            {"drone_id": "drone_3", "battery_pct": 72},
        ]
        assert _pick_leader(candidates) == "drone_2"

    def test_tie_broken_by_drone_id_descending(self):
        candidates = [
            {"drone_id": "drone_1", "battery_pct": 80},
            {"drone_id": "drone_3", "battery_pct": 80},
        ]
        assert _pick_leader(candidates) == "drone_3"

    def test_single_candidate(self):
        assert _pick_leader([{"drone_id": "drone_1", "battery_pct": 50}]) == "drone_1"


# ── Integration tests (3 real RaftNodes via ZMQ) ───────────────────────────────

DRONE_IDS = ["drone_4", "drone_5", "drone_6"]  # ports 5604-5606


def _make_nodes(batteries: List[float]):
    """Create 3 RaftNodes with given battery levels."""
    assert len(batteries) == 3
    nodes = []
    for i, did in enumerate(DRONE_IDS):
        peers = [d for d in DRONE_IDS if d != did]
        b = batteries[i]
        node = RaftNode(
            drone_id=did,
            peer_ids=peers,
            battery_provider=lambda b=b: b,
            min_quorum=2,
        )
        nodes.append(node)
    return nodes


def _run_elections_concurrently(nodes: List[RaftNode]):
    results: List[Optional[str]] = [None] * len(nodes)

    def elect(i, node):
        results[i] = node.start_election()

    threads = [threading.Thread(target=elect, args=(i, n)) for i, n in enumerate(nodes)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    return results


class TestRaftElection:
    def test_correct_leader_elected(self):
        # drone_5 has highest battery → should win
        nodes = _make_nodes([60.0, 85.0, 72.0])
        try:
            results = _run_elections_concurrently(nodes)
            for r in results:
                assert r is not None, f"Election returned None: {results}"
                assert r == "drone_5", f"Expected drone_5, got {r}"
        finally:
            for n in nodes:
                n.stop()

    def test_all_nodes_agree_on_leader(self):
        nodes = _make_nodes([50.0, 50.0, 99.0])  # drone_6 wins
        try:
            results = _run_elections_concurrently(nodes)
            unique = set(r for r in results if r is not None)
            assert unique == {"drone_6"}, f"Nodes disagree: {results}"
        finally:
            for n in nodes:
                n.stop()

    def test_quorum_required(self):
        # Single node: quorum = 2, only 1 candidate → should return None
        node = RaftNode(
            drone_id="drone_4",
            peer_ids=["drone_5", "drone_6"],
            battery_provider=lambda: 80.0,
            min_quorum=2,
        )
        # No peers running — node sees only itself (1 < quorum 2)
        result = node.start_election()
        assert result is None, f"Expected None without quorum, got {result}"
        node.stop()

    def test_election_convergence_under_3_seconds(self):
        nodes = _make_nodes([70.0, 90.0, 80.0])  # drone_5 wins
        try:
            t0 = time.time()
            results = _run_elections_concurrently(nodes)
            elapsed = time.time() - t0
            assert elapsed < 3.0, f"Election took {elapsed:.2f}s, limit is 3.0s"
            assert all(r == "drone_5" for r in results), f"Wrong leader: {results}"
        finally:
            for n in nodes:
                n.stop()

    def test_leader_role_set_correctly(self):
        nodes = _make_nodes([60.0, 85.0, 72.0])  # drone_5 wins
        try:
            _run_elections_concurrently(nodes)
            time.sleep(0.1)
            roles = {n.drone_id: n.role for n in nodes}
            assert roles["drone_5"] == Role.LEADER
            assert roles["drone_4"] == Role.FOLLOWER
            assert roles["drone_6"] == Role.FOLLOWER
        finally:
            for n in nodes:
                n.stop()

    def test_handback_steps_down_leader(self):
        nodes = _make_nodes([60.0, 85.0, 72.0])  # drone_5 wins
        try:
            _run_elections_concurrently(nodes)
            time.sleep(0.1)
            leader_node = next(n for n in nodes if n.drone_id == "drone_5")
            leader_node.handle_operator_restore()
            assert leader_node.role == Role.FOLLOWER
            assert leader_node.current_leader is None
        finally:
            for n in nodes:
                n.stop()
