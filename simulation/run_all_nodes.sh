#!/usr/bin/env bash
# run_all_nodes.sh — starts operator + 3 drone agents in ONE Docker container.
# All nodes share the same DDS domain → heartbeats reach every drone.
# Use the dashboard UI at http://localhost:8080 to inject EW jamming and trigger elections.
# Usage: ./simulation/run_all_nodes.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Allow X11 forwarding from Docker to XQuartz
/opt/X11/bin/xhost +localhost 2>/dev/null || true

docker run -it --rm \
  --network host \
  -e PYTHONPATH=/ws \
  -e DISPLAY=host.docker.internal:0 \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v "$REPO_ROOT":/ws \
  -v /tmp:/tmp \
  osrf/ros:humble-desktop \
  bash -c "
    set -e
    apt-get update -q 2>/dev/null
    apt-get install -y -q python3-zmq ros-humble-foxglove-bridge 2>/dev/null
    source /opt/ros/humble/setup.bash

    # Clean any stale election/jam state
    rm -f /tmp/swarm_leader.txt /tmp/progress_drone_*.json /tmp/swarm_jam_flag

    echo '[swarm] Building swarm_resilience package...'
    cd /ws/ros2_ws && colcon build --packages-select swarm_resilience --symlink-install \
      --cmake-args -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -5
    source /ws/ros2_ws/install/setup.bash
    cd /ws

    echo '[swarm] Starting operator_node...'
    ros2 run swarm_resilience operator_node \
      --ros-args -p mission_path:=mission/mission_state.json &
    sleep 3

    echo '[swarm] Starting drone_1...'
    ros2 run swarm_resilience drone_agent \
      --ros-args -p drone_id:=drone_1 -p mission_path:=mission/mission_state.json &
    sleep 1

    echo '[swarm] Starting drone_2...'
    ros2 run swarm_resilience drone_agent \
      --ros-args -p drone_id:=drone_2 -p mission_path:=mission/mission_state.json &
    sleep 1

    echo '[swarm] Starting drone_3...'
    ros2 run swarm_resilience drone_agent \
      --ros-args -p drone_id:=drone_3 -p mission_path:=mission/mission_state.json &
    sleep 2

    echo ''
    echo '[swarm] ✓ All 4 nodes running.'
    echo '[swarm]   Dashboard → http://localhost:8080'
    echo '[swarm]   Click  ⚡ INJECT EW JAMMING  to trigger a leader election.'
    echo '[swarm]   Click  ↩ RESTORE OPERATOR LINK  to hand back to the operator.'
    echo '[swarm]   Press Ctrl-C here to stop all nodes.'
    echo ''

    # Monitor election results and print convergence time as they happen
    LAST_LEADER=''
    while true; do
      if [ -f /tmp/swarm_leader.txt ]; then
        LEADER=\$(cat /tmp/swarm_leader.txt)
        if [ \"\$LEADER\" != \"\$LAST_LEADER\" ]; then
          echo \"[swarm] ★ Leader elected: \$LEADER\"
          LAST_LEADER=\$LEADER
        fi
      else
        if [ -n \"\$LAST_LEADER\" ]; then
          echo '[swarm] ↩ Leader stepped down — operator resumed'
          LAST_LEADER=''
        fi
      fi
      sleep 0.5
    done &

    wait
  "
