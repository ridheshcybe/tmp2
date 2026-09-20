"""
CLI entry point: run a synthetic mission and export CSV (+ optional plots).
===========================================================================

Examples
--------
    # healthy mission at 1 Hz, default ~99-minute plan
    python -m simulator.telemetry_gen.run_simulation --out data/aerotwin_healthy_demo.csv

    # predefined demo fault sequence + validation plot
    python -m simulator.telemetry_gen.run_simulation --demo-faults --plot

    # custom faults:  TYPE@SEVERITY:ONSET_S:RAMPS
    python -m simulator.telemetry_gen.run_simulation \\
        --fault INJECTOR_DEGRADATION@0.6:1380:240 \\
        --fault MISFIRE@0.5:2280:0 \\
        --fault ALTERNATOR_DEGRADATION@0.45:2880:400

    # sensor drift / dropout target channel
    python -m simulator.telemetry_gen.run_simulation \\
        --fault SENSOR_DRIFT@0.4:4380:0 --fault-drift-channel egt_c3 \\
        --fault SENSOR_DROPOUT@0.7:5940:0 --fault-drop-channel egt_c1

    # compress the mission for a fast demo
    python -m simulator.telemetry_gen.run_simulation \\
        --phase-duration CRUISE=600,ENDURANCE=900
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np

from simulator.telemetry_gen.engine_model import EngineModel, isa_conditions
from simulator.telemetry_gen.fault_injection import FaultInjector, FaultSpec
from simulator.telemetry_gen.mission_profiles import (
    MissionPhase,
    MissionProfile,
    build_mission_plan,
)
from simulator.telemetry_gen.telemetry_schema import (
    CSV_COLUMNS,
    SENSOR_LIMITS,
    FaultType,
    validate_row,
)

MISSION_START = datetime(2026, 9, 3, 0, 0, 0, tzinfo=timezone.utc)

# ──────────────────────────────────────────────────────────────────────────
#  Core simulation
# ──────────────────────────────────────────────────────────────────────────


def simulate(
    hz: float = 1.0,
    seed: int = 42,
    phase_durations: Optional[Dict[str, float]] = None,
    faults: Optional[List[FaultSpec]] = None,
    ambient_offset_c: float = 0.0,
) -> List[Dict[str, object]]:
    """
    Run a full mission and return one flat dict per tick.

    Deterministic for a given (hz, seed, plan, faults, offset).
    """
    if hz <= 0:
        raise ValueError("hz must be > 0")
    dt = 1.0 / hz

    plan = build_mission_plan(phase_durations)
    profile = MissionProfile(plan)

    engine = EngineModel(seed=seed, ambient_offset_c=ambient_offset_c)
    injector = FaultInjector(faults or [], seed=seed + 1)

    rows: List[Dict[str, object]] = []
    t = 0.0
    n_ticks = int(round(profile.total_duration_s * hz))
    for _ in range(n_ticks):
        phase, throttle, altitude_ft = profile.at(t)
        isa = isa_conditions(altitude_ft)
        ambient = isa["ambient_temp_c"] + ambient_offset_c

        row = engine.step(throttle, altitude_ft, ambient)
        row["sim_time_s"] = round(t, 6)
        row["phase"] = phase.value
        row["timestamp"] = (MISSION_START + timedelta(seconds=t)).isoformat()

        injector.apply(row, t)
        rows.append(row)
        t += dt

    return rows


# ──────────────────────────────────────────────────────────────────────────
#  CSV + summary output
# ──────────────────────────────────────────────────────────────────────────


def write_csv(rows: List[Dict[str, object]], out_path: str) -> None:
    """Write rows to CSV using the canonical column order (stdlib only)."""
    import csv

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summarize(rows: List[Dict[str, object]]) -> Dict[str, object]:
    """Per-phase sensor statistics + envelope violation count."""
    import statistics

    phases: Dict[str, List[Dict[str, object]]] = {}
    for r in rows:
        phases.setdefault(str(r["phase"]), []).append(r)

    summary: Dict[str, object] = {
        "total_rows": len(rows),
        "duration_s": float(rows[-1]["sim_time_s"]) if rows else 0.0,
        "violations": 0,
        "faults_seen": set(),
        "phases": {},
    }
    for r in rows:
        if str(r["faults_active"]):
            summary["faults_seen"].update(
                str(r["faults_active"]).split(",")
            )
        summary["violations"] += len(validate_row(r))

    for phase, group in phases.items():
        col = "rpm"
        vals = [float(r[col]) for r in group]
        summary["phases"][phase] = {
            "n": len(group),
            "mean_rpm": round(statistics.fmean(vals), 1),
            "min_egt": round(min(float(r["egt_c1"]) for r in group), 1),
            "max_egt": round(max(float(r["egt_c1"]) for r in group), 1),
            "max_cht": round(max(float(r["cht_c1"]) for r in group), 1),
            "mean_oil_p": round(statistics.fmean(float(r["oil_pressure_kpa"]) for r in group), 1),
            "mean_oil_t": round(statistics.fmean(float(r["oil_temp_c"]) for r in group), 1),
        }
    return summary


def print_summary(summary: Dict[str, object]) -> None:
    print("=" * 64)
    print("  AeroTwin synthetic telemetry run — summary")
    print("=" * 64)
    print(f"  rows           : {summary['total_rows']}")
    print(f"  duration       : {summary['duration_s']:.0f} s "
          f"({summary['duration_s'] / 60:.1f} min)")
    print(f"  envelope viol. : {summary['violations']}")
    faults = summary["faults_seen"]
    print(f"  faults seen    : {', '.join(sorted(faults)) if faults else 'none (healthy)'}")
    print("-" * 64)
    print(f"  {'phase':<11}{'n':>7}{'rpm':>9}{'egt1 min/max':>18}{'cht1 max':>10}{'oilP':>9}{'oilT':>8}")
    for phase, st in summary["phases"].items():  # type: ignore[union-attr]
        print(
            f"  {phase:<11}{st['n']:>7}{st['mean_rpm']:>9.0f}"
            f"{st['min_egt']:>8.0f}/{st['max_egt']:<8.0f}"
            f"{st['max_cht']:>9.0f}{st['mean_oil_p']:>9.0f}{st['mean_oil_t']:>8.0f}"
        )
    print("=" * 64)


# ──────────────────────────────────────────────────────────────────────────
#  Validation plots (optional — needs matplotlib)
# ──────────────────────────────────────────────────────────────────────────


def plot_results(
    rows: List[Dict[str, object]], out_png: str
) -> bool:
    """Multi-panel validation plot; returns False if matplotlib is absent."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib not installed — skipping plot)")
        return False

    import pandas as pd

    df = pd.DataFrame(rows)
    t = df["sim_time_s"].values
    fig, axes = plt.subplots(3, 2, figsize=(15, 11), sharex=True)
    fig.suptitle("AeroTwin synthetic telemetry — validation plot", fontsize=13)

    def shade_phases(ax: "object") -> None:
        """Shade fault-active periods in translucent red."""
        active = df["faults_active"].astype(str).ne("")
        if not active.any():
            return
        boundaries = np.where(np.diff(active.to_numpy().astype(int)) != 0)[0]
        seg_starts = [0] + [b + 1 for b in boundaries]
        seg_ends = [b for b in boundaries] + [len(df) - 1]
        for s, e in zip(seg_starts, seg_ends):
            if active.iloc[s]:
                ax.axvspan(t[s], t[e], color="red", alpha=0.12, zorder=0)

    # (1) RPM / throttle / altitude
    ax = axes[0, 0]
    ax.plot(t, df["rpm"], lw=0.9, label="RPM")
    ax.set_ylabel("RPM"); ax.legend(loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(t, df["throttle"], lw=0.9, color="tab:green", alpha=0.6, label="throttle")
    ax2.plot(t, df["altitude_ft"] / 100.0, lw=0.6, color="tab:blue", alpha=0.35, ls="--", label="alt/100 ft")
    ax2.set_ylabel("throttle / alt/100"); ax2.set_ylim(0, 1.0)
    shade_phases(ax); ax.set_title("Engine speed & operating conditions")

    # (2) CHT per cylinder
    ax = axes[0, 1]
    for c in ["cht_c1", "cht_c2", "cht_c3", "cht_c4"]:
        ax.plot(t, df[c], lw=0.9, label=c.replace("cht_", "").upper())
    ax.set_ylabel("°C"); ax.legend(loc="upper left", ncol=2)
    shade_phases(ax); ax.set_title("Cylinder head temperature")

    # (3) EGT per cylinder
    ax = axes[1, 0]
    for c in ["egt_c1", "egt_c2", "egt_c3", "egt_c4"]:
        ax.plot(t, df[c], lw=0.9, label=c.replace("egt_", "").upper())
    ax.set_ylabel("°C"); ax.legend(loc="upper left", ncol=2)
    shade_phases(ax); ax.set_title("Exhaust gas temperature")

    # (4) Oil pressure + temperature
    ax = axes[1, 1]
    ax.plot(t, df["oil_pressure_kpa"], lw=0.9, color="tab:red", label="oil pressure")
    ax.set_ylabel("kPa"); ax.legend(loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(t, df["oil_temp_c"], lw=0.9, color="tab:orange", label="oil temp")
    ax2.set_ylabel("°C"); ax2.legend(loc="upper right")
    shade_phases(ax); ax.set_title("Lubrication system")

    # (5) Vibration + battery / alternator
    ax = axes[2, 0]
    ax.plot(t, df["vibration_rms_g"], lw=0.9, color="tab:purple", label="vibration RMS")
    ax.set_ylabel("g"); ax.legend(loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(t, df["battery_v"], lw=0.9, color="tab:green", label="battery V")
    ax2.plot(t, df["alternator_a"], lw=0.9, color="tab:cyan", ls="--", label="alternator A")
    ax2.set_ylabel("V / A"); ax2.legend(loc="upper right")
    shade_phases(ax); ax.set_title("Vibration & electrical system")

    # (6) Fuel + injection timing
    ax = axes[2, 1]
    ax.plot(t, df["fuel_flow_lph"], lw=0.9, color="tab:olive", label="fuel flow")
    ax.set_ylabel("l/h"); ax.legend(loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(t, df["injection_timing_deg"], lw=0.9, color="tab:gray", label="injection advance")
    ax2.set_ylabel("°BTDC"); ax2.legend(loc="upper right")
    shade_phases(ax); ax.set_title("Fuel & injection timing")

    axes[2, 1].set_xlabel("sim time (s)")
    axes[2, 0].set_xlabel("sim time (s)")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    print(f"  plot saved : {out_png}")
    return True


# ──────────────────────────────────────────────────────────────────────────
#  Demo fault preset
# ──────────────────────────────────────────────────────────────────────────


def demo_faults(profile: MissionProfile) -> List[FaultSpec]:
    """Predefined fault sequence for the dramatic demo run."""
    cruise = profile.phase_start_s(MissionPhase.CRUISE)
    endurance = profile.phase_start_s(MissionPhase.ENDURANCE)
    descent = profile.phase_start_s(MissionPhase.DESCENT)
    return [
        FaultSpec(
            FaultType.INJECTOR_DEGRADATION, severity=0.60,
            onset_s=cruise + 300.0, ramp_s=240.0,
        ),
        FaultSpec(
            FaultType.MISFIRE, severity=0.50,
            onset_s=cruise + 1200.0, ramp_s=0.0,
        ),
        FaultSpec(
            FaultType.ALTERNATOR_DEGRADATION, severity=0.45,
            onset_s=endurance, ramp_s=400.0,
        ),
        FaultSpec(
            FaultType.LUBRICATION_FAILURE, severity=0.55,
            onset_s=endurance + 900.0, ramp_s=600.0,
        ),
        FaultSpec(
            FaultType.SENSOR_DRIFT, severity=0.40,
            onset_s=endurance + 1500.0, ramp_s=0.0, channel="egt_c3",
        ),
        FaultSpec(
            FaultType.SENSOR_DROPOUT, severity=0.70,
            onset_s=descent + 60.0, ramp_s=0.0, channel="egt_c1",
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────────────────────


def _parse_fault(arg: str, defaults: Dict[str, str]) -> Optional[FaultSpec]:
    """
    Parse ``TYPE@SEVERITY:ONSET_S:RAMPS`` (ramps optional).
    Channel comes from ``--fault-drift-channel`` / ``--fault-drop-channel``.
    """
    type_str, _, rest = arg.partition("@")
    parts = [p for p in rest.split(":") if p != ""]
    try:
        ftype = FaultType(type_str.strip().upper())
    except ValueError:
        raise ValueError(f"unknown fault type '{type_str}'") from None

    severity = float(parts[0]) if parts else 0.5
    onset = float(parts[1]) if len(parts) > 1 else 0.0
    ramp = float(parts[2]) if len(parts) > 2 else 0.0

    channel = None
    if ftype == FaultType.SENSOR_DRIFT:
        channel = defaults.get("drift", "egt_c2")
    elif ftype == FaultType.SENSOR_DROPOUT:
        channel = defaults.get("drop", "egt_c1")
    return FaultSpec(ftype, severity=severity, onset_s=onset, ramp_s=ramp, channel=channel)


def _parse_phase_durations(raw: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for item in raw.split(","):
        name, _, val = item.strip().partition("=")
        if not name or not val:
            raise ValueError(f"bad phase duration '{item}' (want PHASE=SECONDS)")
        out[name.strip().upper()] = float(val)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simulator.telemetry_gen.run_simulation",
        description="AeroTwin synthetic aero piston engine telemetry generator",
    )
    parser.add_argument("--hz", type=float, default=1.0, help="sampling rate (default 1 Hz)")
    parser.add_argument("--seed", type=int, default=42, help="deterministic RNG seed")
    parser.add_argument("--out", default="data/aerotwin_telemetry.csv", help="CSV output path")
    parser.add_argument("--plot", action="store_true", help="also write validation plot PNG")
    parser.add_argument(
        "--phase-duration", default="",
        help="comma list PHASE=SECONDS overrides, e.g. CRUISE=600,ENDURANCE=900",
    )
    parser.add_argument(
        "--fault", action="append", default=[],
        help="TYPE@SEVERITY:ONSET_S:RAMPS (repeatable)",
    )
    parser.add_argument(
        "--fault-drift-channel", default="egt_c2", help="channel for SENSOR_DRIFT"
    )
    parser.add_argument(
        "--fault-drop-channel", default="egt_c1", help="channel for SENSOR_DROPOUT"
    )
    parser.add_argument(
        "--demo-faults", action="store_true",
        help="inject the predefined demo fault sequence (overrides --fault)",
    )
    parser.add_argument(
        "--ambient-offset", type=float, default=0.0,
        help="add to ISA ambient temperature (°C), e.g. +15 for hot weather",
    )
    args = parser.parse_args(argv)

    # ── resolve plan + faults ──
    phase_durations = _parse_phase_durations(args.phase_duration) if args.phase_duration else None
    plan = build_mission_plan(phase_durations)
    profile = MissionProfile(plan)

    if args.demo_faults:
        faults = demo_faults(profile)
        print(f"  demo faults  : {len(faults)} injected")
    else:
        defaults = {"drift": args.fault_drift_channel, "drop": args.fault_drop_channel}
        faults = []
        for arg in args.fault:
            try:
                faults.append(_parse_fault(arg, defaults))
            except ValueError as e:
                print(f"  ERROR: {e}")
                return 2

    for f in faults:
        print(
            f"  fault        : {f.fault_type.value:<24} severity={f.severity:.2f} "
            f"onset={f.onset_s:>7.0f}s ramp={f.ramp_s:>5.0f}s "
            f"{('channel=' + f.channel) if f.channel else ''}"
        )

    # ── run ──
    print(f"  plan         : {profile.total_duration_s:.0f} s "
          f"({profile.total_duration_s / 60:.1f} min) @ {args.hz} Hz, seed={args.seed}")
    rows = simulate(
        hz=args.hz,
        seed=args.seed,
        phase_durations=phase_durations,
        faults=faults,
        ambient_offset_c=args.ambient_offset,
    )

    write_csv(rows, args.out)
    print(f"  csv saved    : {args.out} ({len(rows)} rows)")
    print_summary(summarize(rows))

    if args.plot:
        png = args.out.rsplit(".", 1)[0] + "_plot.png"
        plot_results(rows, png)

    return 0


if __name__ == "__main__":
    sys.exit(main())