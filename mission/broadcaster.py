import json
import time
import zmq

BROADCAST_PORT = 5555
SEND_REPEATS = 5
SEND_INTERVAL_S = 0.1
SUBSCRIBER_WARMUP_S = 0.5


def broadcast_mission(mission_state_path: str, bind_address: str = "*") -> None:
    """Operator-side: broadcast mission state to all subscribing drones."""
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    sock.bind(f"tcp://{bind_address}:{BROADCAST_PORT}")
    time.sleep(SUBSCRIBER_WARMUP_S)

    with open(mission_state_path) as f:
        payload = f.read()

    for i in range(SEND_REPEATS):
        sock.send_string(payload)
        time.sleep(SEND_INTERVAL_S)

    print(f"[broadcaster] Mission state broadcast complete from {mission_state_path}")
    sock.close()
    ctx.term()


def receive_mission(
    drone_id: str,
    operator_address: str,
    output_path: str,
    timeout_ms: int = 10_000,
) -> bool:
    """Drone-side: receive mission state and persist it locally."""
    ctx = zmq.Context()
    sock = ctx.socket(zmq.SUB)
    sock.connect(f"tcp://{operator_address}:{BROADCAST_PORT}")
    sock.setsockopt_string(zmq.SUBSCRIBE, "")
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)

    try:
        payload = sock.recv_string()
        mission = json.loads(payload)
        with open(output_path, "w") as f:
            json.dump(mission, f, indent=2)
        print(f"[{drone_id}] Mission state received → {output_path}")
        return True
    except zmq.error.Again:
        print(f"[{drone_id}] Timeout: no mission state received within {timeout_ms}ms")
        return False
    finally:
        sock.close()
        ctx.term()


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    bc = sub.add_parser("broadcast")
    bc.add_argument("--mission", default="mission/mission_state.json")

    rc = sub.add_parser("receive")
    rc.add_argument("--drone-id", required=True)
    rc.add_argument("--operator", default="localhost")
    rc.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.cmd == "broadcast":
        broadcast_mission(args.mission)
    elif args.cmd == "receive":
        ok = receive_mission(args.drone_id, args.operator, args.output)
        sys.exit(0 if ok else 1)
    else:
        parser.print_help()
