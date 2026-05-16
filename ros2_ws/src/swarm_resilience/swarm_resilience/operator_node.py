import json
import os
import sys
import threading

import rclpy  # type: ignore[import-untyped]
from rclpy.node import Node  # type: ignore[import-untyped]
from std_msgs.msg import String  # type: ignore[import-untyped]

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../../.."))
from mission.broadcaster import broadcast_mission  # type: ignore[import-untyped]
from swarm_resilience.mission_loader import load_mission  # type: ignore[import-untyped]


class OperatorNode(Node):
    """
    Operator ROS2 node.

    Publishes:
      /swarm/operator_heartbeat  (std_msgs/String, "hb") at 2Hz
      /swarm/mission_state       (std_msgs/String, JSON) once at startup
      /swarm/election_status     (std_msgs/String) on election events

    On startup: broadcasts mission_state.json via ZMQ so each drone caches it.
    Sending SIGTERM to this process simulates EW link loss (heartbeat stops).
    """

    HEARTBEAT_HZ = 2.0

    def __init__(self):
        super().__init__("operator_node")

        self.declare_parameter("mission_path", "mission/mission_state.json")
        self.declare_parameter("operator_address", "*")

        mission_path: str = self.get_parameter("mission_path").value
        operator_address: str = self.get_parameter("operator_address").value

        self._mission = load_mission(mission_path)

        self._pub_heartbeat = self.create_publisher(String, "/swarm/operator_heartbeat", 10)
        self._pub_mission = self.create_publisher(String, "/swarm/mission_state", 10)
        self._pub_election = self.create_publisher(String, "/swarm/election_status", 10)

        threading.Thread(
            target=broadcast_mission,
            args=(mission_path, operator_address),
            daemon=True,
        ).start()

        mission_msg = String()
        mission_msg.data = json.dumps(self._mission)
        self._pub_mission.publish(mission_msg)

        self.create_timer(1.0 / self.HEARTBEAT_HZ, self._publish_heartbeat)
        self.get_logger().info("[operator] OperatorNode started — heartbeat at 2Hz")

    def _publish_heartbeat(self) -> None:
        self._pub_heartbeat.publish(String(data="hb"))

    def destroy_node(self) -> None:
        self.get_logger().info("[operator] OperatorNode shutting down — heartbeat stopped")
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = OperatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
