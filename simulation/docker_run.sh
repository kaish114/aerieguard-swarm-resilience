#!/usr/bin/env bash
# docker_run.sh — run a command inside the ROS2 Humble container with workspace mounted
# Usage: ./simulation/docker_run.sh "ros2 run swarm_resilience operator_node"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
CMD="${1:-bash}"

docker run -it --rm \
  --network host \
  -e DISPLAY=:0 \
  -e PYTHONPATH=/ws \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v "$REPO_ROOT":/ws \
  -v /tmp:/tmp \
  osrf/ros:humble-desktop \
  bash -c "
    apt-get update -q 2>/dev/null &&
    apt-get install -y -q python3-zmq 2>/dev/null &&
    source /opt/ros/humble/setup.bash &&
    source /ws/ros2_ws/install/setup.bash &&
    cd /ws &&
    $CMD
  "
