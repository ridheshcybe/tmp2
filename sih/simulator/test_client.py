#!/usr/bin/env python3
"""
Telemetry Streamer — Test Client
---------------------------------
Connects to the WebSocket telemetry server, prints 20 streaming
frames, sends a fault-injection command, and verifies the fault
appeared in subsequent frames.

Usage
-----
    # Terminal 1: start the server
    python -m simulator.telemetry_streamer

    # Terminal 2: run this client
    python -m simulator.test_client
    python -m simulator.test_client --port 9000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

try:
    import websockets
    from websockets.asyncio.client import connect
except ImportError:
    print("  Install websockets:  pip install websockets>=12.0", file=sys.stderr)
    sys.exit(1)


DEFAULT_PORT = 8765
FRAMES_TO_PRINT = 20
VERIFY_FRAMES = 10


async def run_test(port: int) -> bool:
    uri = f"ws://localhost:{port}"
    print(f"\n  Connecting to {uri} …")

    try:
        async with connect(uri, open_timeout=5.0) as ws:
            print("  Connected.\n")

            # ── Phase 1: print 20 clean frames ──
            print("  ── Phase 1: Streaming nominal frames ──\n")
            print(
                f"  {'#':>4}  {'Time':>6}  {'RPM':>7}  {'CHT₁':>6}  "
                f"{'EGT₁':>6}  {'Oil P':>7}  {'Vib':>6}  {'Fault':<16}"
            )
            print("  " + "─" * 72)

            for i in range(FRAMES_TO_PRINT):
                raw = await ws.recv()
                pkt = json.loads(raw)
                print(
                    f"  {pkt['frame_id']:>4}  "
                    f"{pkt.get('frame_id', 0) * 0.1:>6.1f}  "
                    f"{pkt['rpm']:>7.0f}  "
                    f"{pkt['cht'][0]:>6.1f}  "
                    f"{pkt['egt'][0]:>6.0f}  "
                    f"{pkt['oil_pressure_kpa']:>7.1f}  "
                    f"{pkt['vibration_rms']:>6.3f}  "
                    f"{str(pkt.get('injected_fault')):<16}"
                )

            # ── Phase 2: send fault command ──
            print("\n  ── Phase 2: Injecting PISTON_RING_WEAR fault ──\n")

            cmd = {
                "command": "INJECT_FAULT",
                "type": "PISTON_RING_WEAR",
                "severity": 0.8,
                "rate_per_sec": 0.02,
            }
            await ws.send(json.dumps(cmd))

            # Read acknowledgement
            ack_raw = await ws.recv()
            ack = json.loads(ack_raw)
            print(f"  Server response: {json.dumps(ack, indent=4)}\n")

            if ack.get("status") != "ok":
                print("  ✗ Fault injection command failed!")
                return False

            # ── Phase 3: verify fault in streaming data ──
            print("  ── Phase 3: Verifying fault in live telemetry ──\n")
            print(
                f"  {'#':>4}  {'RPM':>7}  {'CHT₁':>6}  "
                f"{'Oil T':>6}  {'Vib':>6}  {'Fault':<24}"
            )
            print("  " + "─" * 68)

            fault_detected = False
            for i in range(VERIFY_FRAMES):
                raw = await ws.recv()
                pkt = json.loads(raw)
                ft = pkt.get("injected_fault")
                fault_detected = fault_detected or (ft is not None)

                print(
                    f"  {pkt['frame_id']:>4}  "
                    f"{pkt['rpm']:>7.0f}  "
                    f"{pkt['cht'][0]:>6.1f}  "
                    f"{pkt['oil_temp_c']:>6.1f}  "
                    f"{pkt['vibration_rms']:>6.3f}  "
                    f"{str(ft):<24}"
                )

            # ── Phase 4: clear faults and confirm ──
            print("\n  ── Phase 4: Clearing faults ──\n")
            await ws.send(json.dumps({"command": "CLEAR_FAULTS"}))
            ack_raw = await ws.recv()
            ack = json.loads(ack_raw)
            print(f"  Server response: {json.dumps(ack, indent=4)}\n")

            # ── Verdict ──
            print("  " + "═" * 50)
            if fault_detected:
                print("  ✓  FAULT DETECTED in live telemetry stream")
                print("  ✓  Test PASSED")
            else:
                print("  ✗  Fault NOT detected in streamed frames")
                print("  ✗  Test FAILED")
            print("  " + "═" * 50 + "\n")

            return fault_detected

    except (ConnectionRefusedError, OSError) as e:
        print(f"\n  ✗  Could not connect to {uri}: {e}")
        print("     Make sure the server is running:\n")
        print(f"       python -m simulator.telemetry_streamer --port {port}\n")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Telemetry test client")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Server port (default: {DEFAULT_PORT})",
    )
    args = parser.parse_args()

    success = asyncio.run(run_test(args.port))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
