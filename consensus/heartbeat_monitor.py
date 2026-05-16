import threading
import time
from typing import Callable, Optional


class HeartbeatMonitor:
    """
    Monitors operator heartbeat liveness.

    Call record_heartbeat() each time a heartbeat arrives.
    Fires on_timeout() once when elapsed >= timeout_s.
    Fires on_restore() once when heartbeat resumes after a timeout.
    """

    POLL_INTERVAL_S = 0.1

    def __init__(
        self,
        timeout_ms: int,
        on_timeout: Callable[[], None],
        on_restore: Callable[[], None],
    ):
        self.timeout_s = timeout_ms / 1000.0
        self.on_timeout = on_timeout
        self.on_restore = on_restore

        self._last_heartbeat = time.monotonic()
        self._timed_out = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def record_heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat = time.monotonic()
            if self._timed_out:
                self._timed_out = False
                restore = True
            else:
                restore = False
        if restore:
            self.on_restore()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.POLL_INTERVAL_S)
            with self._lock:
                elapsed = time.monotonic() - self._last_heartbeat
                should_fire = elapsed >= self.timeout_s and not self._timed_out
                if should_fire:
                    self._timed_out = True
            if should_fire:
                self.on_timeout()
