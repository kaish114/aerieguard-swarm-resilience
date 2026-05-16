import json
from typing import Dict, Tuple

import rclpy  # type: ignore[import-untyped]
from rclpy.node import Node  # type: ignore[import-untyped]
from std_msgs.msg import String  # type: ignore[import-untyped]
from visualization_msgs.msg import Marker, MarkerArray  # type: ignore[import-untyped]
from geometry_msgs.msg import Point  # type: ignore[import-untyped]


DRONE_IDS = ["drone_1", "drone_2", "drone_3"]

DRONE_OFFSETS: Dict[str, Tuple[float, float, float]] = {
    "drone_1": (0.0, 0.0, 10.0),
    "drone_2": (10.0, 0.0, 10.0),
    "drone_3": (5.0, 8.0, 10.0),
}


class SwarmMonitor(Node):
    """
    Publishes RViz MarkerArray showing:
    - Sphere per drone (blue=follower, red=leader, yellow=candidate)
    - Line list for mesh links between drones
    - Text marker for election status overlay
    """

    def __init__(self):
        super().__init__("swarm_monitor")

        self._roles: Dict[str, str] = {d: "follower" for d in DRONE_IDS}
        self._leader: str = ""
        self._election_status: str = "NOMINAL"

        self._pub_markers = self.create_publisher(MarkerArray, "/swarm/visualization", 10)

        for did in DRONE_IDS:
            self.create_subscription(String, f"/{did}/progress",
                                     lambda msg, d=did: self._on_progress(d, msg), 10)
            self.create_subscription(String, f"/{did}/election/result",
                                     lambda msg, d=did: self._on_election_result(d, msg), 10)

        self.create_subscription(String, "/swarm/leader", self._on_leader, 10)
        self.create_timer(0.2, self._publish_markers)

    def _on_progress(self, drone_id: str, msg: String) -> None:
        try:
            state = json.loads(msg.data)
            self._roles[drone_id] = state.get("role", "follower")
        except json.JSONDecodeError:
            pass

    def _on_election_result(self, _: str, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            leader = data.get("leader_id", "")
            self._election_status = f"LEADER: {leader.upper()}"
            self._leader = leader
        except json.JSONDecodeError:
            pass

    def _on_leader(self, msg: String) -> None:
        self._leader = msg.data
        self._election_status = f"LEADER: {msg.data.upper()}"

    def _publish_markers(self) -> None:
        array = MarkerArray()
        now = self.get_clock().now().to_msg()

        for i, did in enumerate(DRONE_IDS):
            x, y, z = DRONE_OFFSETS[did]
            role = self._roles.get(did, "follower")

            m = Marker()
            m.header.frame_id = "map"
            m.header.stamp = now
            m.ns = "drones"
            m.id = i
            m.type = Marker.SPHERE
            m.action = Marker.ADD
            m.pose.position.x = x
            m.pose.position.y = y
            m.pose.position.z = z
            m.pose.orientation.w = 1.0
            m.scale.x = m.scale.y = m.scale.z = 2.0

            if role == "leader":
                m.color.r, m.color.g, m.color.b, m.color.a = 1.0, 0.0, 0.0, 1.0
            elif role == "candidate":
                m.color.r, m.color.g, m.color.b, m.color.a = 1.0, 1.0, 0.0, 1.0
            else:
                m.color.r, m.color.g, m.color.b, m.color.a = 0.0, 0.5, 1.0, 1.0

            array.markers.append(m)

            t = Marker()
            t.header.frame_id = "map"
            t.header.stamp = now
            t.ns = "drone_labels"
            t.id = 100 + i
            t.type = Marker.TEXT_VIEW_FACING
            t.action = Marker.ADD
            t.pose.position.x = x
            t.pose.position.y = y
            t.pose.position.z = z + 2.5
            t.pose.orientation.w = 1.0
            t.scale.z = 1.5
            t.color.r = t.color.g = t.color.b = t.color.a = 1.0
            t.text = f"{did}\n[{role}]"
            array.markers.append(t)

        link_id = 200
        link_pairs = [("drone_1", "drone_2"), ("drone_2", "drone_3"), ("drone_1", "drone_3")]
        for d1, d2 in link_pairs:
            x1, y1, z1 = DRONE_OFFSETS[d1]
            x2, y2, z2 = DRONE_OFFSETS[d2]
            line = Marker()
            line.header.frame_id = "map"
            line.header.stamp = now
            line.ns = "mesh_links"
            line.id = link_id
            line.type = Marker.LINE_STRIP
            line.action = Marker.ADD
            line.scale.x = 0.3
            line.color.g = 1.0
            line.color.a = 0.8
            p1 = Point(x=x1, y=y1, z=z1)
            p2 = Point(x=x2, y=y2, z=z2)
            line.points = [p1, p2]
            array.markers.append(line)
            link_id += 1

        status = Marker()
        status.header.frame_id = "map"
        status.header.stamp = now
        status.ns = "election_status"
        status.id = 300
        status.type = Marker.TEXT_VIEW_FACING
        status.action = Marker.ADD
        status.pose.position.x = 5.0
        status.pose.position.y = -5.0
        status.pose.position.z = 20.0
        status.pose.orientation.w = 1.0
        status.scale.z = 2.0
        status.color.r = 1.0
        status.color.g = 1.0
        status.color.a = 1.0
        status.text = self._election_status
        array.markers.append(status)

        self._pub_markers.publish(array)


def main(args=None):
    rclpy.init(args=args)
    node = SwarmMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
