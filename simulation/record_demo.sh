#!/usr/bin/env bash
# record_demo.sh — starts rosbag2 recording, then runs the scenario
# Usage: ./simulation/record_demo.sh [--inject-after 30]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
INJECT_AFTER="${1:-30}"
RUN_ID="demo_$(date +%Y%m%d_%H%M%S)"
BAG_DIR="$REPO_ROOT/results/demo_rosbag/$RUN_ID"

mkdir -p "$BAG_DIR"

# Require ROS2 environment
if ! command -v ros2 &>/dev/null; then
    echo "[record_demo] ERROR: ros2 not found. Source ROS2 Humble first:"
    echo "  source /opt/ros/humble/setup.bash"
    exit 1
fi

echo "[record_demo] Starting rosbag2 recording → $BAG_DIR"
ros2 bag record \
    -o "$BAG_DIR" \
    /swarm/operator_heartbeat \
    /swarm/leader \
    /swarm/mission_state \
    /swarm/election_status \
    /swarm/visualization \
    /drone_1/progress \
    /drone_2/progress \
    /drone_3/progress \
    /drone_1/election/result \
    /drone_2/election/result \
    /drone_3/election/result \
    /drone_1/mavros/local_position/pose \
    /drone_2/mavros/local_position/pose \
    /drone_3/mavros/local_position/pose \
    &
BAG_PID=$!
echo "[record_demo] rosbag2 PID: $BAG_PID"

# Give bag recording time to initialise
sleep 2

echo "[record_demo] Running scenario (inject link loss at T+${INJECT_AFTER}s)"
python3 "$REPO_ROOT/simulation/scenario.py" \
    --inject-after "$INJECT_AFTER" \
    --run-id "$RUN_ID"

# Let bag capture a few more seconds after scenario
sleep 5

echo "[record_demo] Stopping rosbag2 recording..."
kill "$BAG_PID" 2>/dev/null || true
wait "$BAG_PID" 2>/dev/null || true

echo "[record_demo] Done. Bag saved to: $BAG_DIR"
echo "[record_demo] To replay: ros2 bag play $BAG_DIR"
