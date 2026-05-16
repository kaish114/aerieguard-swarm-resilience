import json
import os
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../../.."))
from consensus.raft import RaftNode, Role
from consensus.heartbeat_monitor import HeartbeatMonitor
from mission.progress_tracker import ProgressTracker
from swarm_resilience.mission_loader import load_mission, get_timeout_ms, get_min_quorum


class DroneAgent(Node):
    """
    Per-drone ROS2 node.

    Subscribes to:
      /{drone_id}/mavros/local_position/pose
      /{drone_id}/mavros/battery
      /swarm/operator_heartbeat

    Publishes to:
      /{drone_id}/progress        (std_msgs/String, JSON)
      /{drone_id}/election/result (std_msgs/String, JSON)
      /swarm/leader               (std_msgs/String)
    """

    def __init__(self):
        super().__init__("drone_agent")

        self.declare_parameter("drone_id", "drone_1")
        self.declare_parameter("peer_ids", ["drone_2", "drone_3"])
        self.declare_parameter("mission_path", "mission/mission_state.json")
        self.declare_parameter("progress_path", "/tmp/progress.json")

        self._drone_id: str = self.get_parameter("drone_id").value
        peer_ids: list = self.get_parameter("peer_ids").value
        mission_path: str = self.get_parameter("mission_path").value
        progress_path: str = self.get_parameter("progress_path").value

        mission = load_mission(mission_path)
        timeout_ms = get_timeout_ms(mission)
        min_quorum = get_min_quorum(mission)

        self._state = {
            "last_confirmed_waypoint": 0,
            "current_position": {"lat": 0.0, "lon": 0.0, "alt_m": 0.0},
            "battery_pct": 100.0,
            "role": "follower",
        }
        self._state_lock = threading.Lock()

        self._raft = RaftNode(
            drone_id=self._drone_id,
            peer_ids=peer_ids,
            battery_provider=self._get_battery,
            min_quorum=min_quorum,
            on_leader_change=self._on_leader_change,
        )

        self._hb_monitor = HeartbeatMonitor(
            timeout_ms=timeout_ms,
            on_timeout=self._on_heartbeat_timeout,
            on_restore=self._on_heartbeat_restore,
        )

        self._progress = ProgressTracker(
            drone_id=self._drone_id,
            mission_id=mission["mission_id"],
            output_path=progress_path,
            state_callback=self._get_state,
        )

        self._pub_progress = self.create_publisher(String, f"/{self._drone_id}/progress", 10)
        self._pub_result = self.create_publisher(String, f"/{self._drone_id}/election/result", 10)
        self._pub_leader = self.create_publisher(String, "/swarm/leader", 10)

        self.create_subscription(PoseStamped, f"/{self._drone_id}/mavros/local_position/pose",
                                 self._on_pose, 10)
        self.create_subscription(BatteryState, f"/{self._drone_id}/mavros/battery",
                                 self._on_battery, 10)
        self.create_subscription(String, "/swarm/operator_heartbeat",
                                 self._on_operator_heartbeat, 10)

        self.create_timer(0.5, self._publish_progress)

        self._hb_monitor.start()
        self._progress.start()
        self.get_logger().info(f"[{self._drone_id}] DroneAgent started")

    def _get_battery(self) -> float:
        with self._state_lock:
            return self._state["battery_pct"]

    def _get_state(self):
        with self._state_lock:
            return dict(self._state)

    def _on_pose(self, msg: PoseStamped) -> None:
        with self._state_lock:
            self._state["current_position"] = {
                "lat": msg.pose.position.x,
                "lon": msg.pose.position.y,
                "alt_m": msg.pose.position.z,
            }

    def _on_battery(self, msg: BatteryState) -> None:
        with self._state_lock:
            self._state["battery_pct"] = msg.percentage * 100.0

    def _on_operator_heartbeat(self, _msg: String) -> None:
        self._hb_monitor.record_heartbeat()

    def _on_heartbeat_timeout(self) -> None:
        self.get_logger().warn(f"[{self._drone_id}] Heartbeat timeout — starting election")
        threading.Thread(target=self._run_election, daemon=True).start()

    def _on_heartbeat_restore(self) -> None:
        self.get_logger().info(f"[{self._drone_id}] Operator heartbeat restored")
        self._raft.handle_operator_restore()
        with self._state_lock:
            self._state["role"] = "follower"

    def _run_election(self) -> None:
        leader = self._raft.start_election()
        if leader:
            self.get_logger().info(f"[{self._drone_id}] Election complete → leader: {leader}")
        else:
            self.get_logger().error(f"[{self._drone_id}] Election failed — no quorum")

    def _on_leader_change(self, term: int, leader_id: str) -> None:
        with self._state_lock:
            self._state["role"] = "leader" if leader_id == self._drone_id else "follower"

        msg = String()
        msg.data = json.dumps({"term": term, "leader_id": leader_id})
        self._pub_result.publish(msg)
        self._pub_leader.publish(String(data=leader_id))

    def _publish_progress(self) -> None:
        state = self._get_state()
        msg = String()
        msg.data = json.dumps(state)
        self._pub_progress.publish(msg)

    def update_waypoint(self, waypoint_index: int) -> None:
        with self._state_lock:
            self._state["last_confirmed_waypoint"] = waypoint_index

    def destroy_node(self) -> None:
        self._hb_monitor.stop()
        self._progress.stop()
        self._raft.stop()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DroneAgent()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
