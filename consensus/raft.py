import json
import queue
import threading
import time
from enum import Enum
from typing import Callable, Dict, List, Optional
import zmq

BASE_PORT = 5600
COLLECTION_WINDOW_S = 0.5
ELECTION_TIMEOUT_S = 3.0
SOCKET_WARMUP_S = 0.3


class Role(Enum):
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


def _drone_port(drone_id: str) -> int:
    return BASE_PORT + int(drone_id.split("_")[1])


def _pick_leader(candidates: List[dict]) -> str:
    """Module-level alias used by tests. Highest battery wins; ties broken by drone_id descending."""
    best = max(candidates, key=lambda c: (c["battery_pct"], c["drone_id"]))
    return best["drone_id"]


class RaftNode:
    """
    Modified RAFT with deterministic battery-based leader election.

    Election criterion: highest battery_pct wins; ties broken by drone_id
    (lexicographic descending — "drone_3" > "drone_2" > "drone_1").
    Min quorum = 2. Election must complete in ELECTION_TIMEOUT_S seconds.
    """

    def __init__(
        self,
        drone_id: str,
        peer_ids: List[str],
        battery_provider: Callable[[], float],
        min_quorum: int = 2,
        on_leader_change: Optional[Callable[[int, str], None]] = None,
    ):
        self.drone_id = drone_id
        self.peer_ids = peer_ids
        self.battery_provider = battery_provider
        self.min_quorum = min_quorum
        self.on_leader_change = on_leader_change

        self.role = Role.FOLLOWER
        self.current_term = 0
        self.current_leader: Optional[str] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._msg_queue: queue.Queue = queue.Queue()

        ctx = zmq.Context()
        self._ctx = ctx

        self._pub = ctx.socket(zmq.PUB)
        self._pub.bind(f"tcp://*:{_drone_port(drone_id)}")

        self._sub = ctx.socket(zmq.SUB)
        self._sub.setsockopt_string(zmq.SUBSCRIBE, "")
        for pid in peer_ids:
            self._sub.connect(f"tcp://localhost:{_drone_port(pid)}")

        time.sleep(SOCKET_WARMUP_S)

        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _recv_loop(self) -> None:
        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)
        while not self._stop.is_set():
            events = dict(poller.poll(timeout=100))
            if self._sub in events:
                raw = self._sub.recv_string()
                self._msg_queue.put(json.loads(raw))

    def _drain_queue(self) -> None:
        while not self._msg_queue.empty():
            try:
                self._msg_queue.get_nowait()
            except queue.Empty:
                break

    def _collect(self, msg_type: str, duration_s: float) -> List[dict]:
        msgs: List[dict] = []
        deadline = time.time() + duration_s
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                msg = self._msg_queue.get(timeout=min(0.05, remaining))
                if msg.get("type") == msg_type:
                    msgs.append(msg)
            except queue.Empty:
                pass
        return msgs

    @staticmethod
    def _pick_leader(candidates: List[dict]) -> str:
        """Highest battery wins; ties broken by drone_id descending."""
        return _pick_leader(candidates)

    def _publish(self, msg: dict) -> None:
        self._pub.send_string(json.dumps(msg))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_election(self) -> Optional[str]:
        """
        Trigger election. Returns elected leader_id on success, None if quorum
        not reached within ELECTION_TIMEOUT_S.
        """
        with self._lock:
            self.current_term += 1
            self.role = Role.CANDIDATE
            term = self.current_term

        battery = self.battery_provider()
        self._drain_queue()

        self._publish({
            "type": "candidate_announce",
            "term": term,
            "drone_id": self.drone_id,
            "battery_pct": battery,
        })

        peer_announces = self._collect("candidate_announce", COLLECTION_WINDOW_S)
        peer_announces = [m for m in peer_announces if m["term"] == term]

        all_candidates = [
            {"drone_id": self.drone_id, "battery_pct": battery}
        ] + [
            {"drone_id": m["drone_id"], "battery_pct": m["battery_pct"]}
            for m in peer_announces
        ]

        if len(all_candidates) < self.min_quorum:
            with self._lock:
                self.role = Role.FOLLOWER
            return None

        leader_id = self._pick_leader(all_candidates)

        self._publish({
            "type": "leader_announce",
            "term": term,
            "leader_id": leader_id,
        })

        with self._lock:
            self.current_leader = leader_id
            self.role = Role.LEADER if leader_id == self.drone_id else Role.FOLLOWER

        if self.on_leader_change:
            self.on_leader_change(term, leader_id)

        return leader_id

    def handle_operator_restore(self) -> None:
        """Called when operator heartbeat resumes. Leader steps down immediately."""
        with self._lock:
            was_leader = self.role == Role.LEADER
            self.role = Role.FOLLOWER
            self.current_leader = None

        if was_leader:
            self._publish({
                "type": "handback",
                "term": self.current_term,
                "former_leader": self.drone_id,
            })

    def stop(self) -> None:
        self._stop.set()
        self._pub.setsockopt(zmq.LINGER, 0)
        self._sub.setsockopt(zmq.LINGER, 0)
        self._pub.close()
        self._sub.close()
        self._ctx.term()
