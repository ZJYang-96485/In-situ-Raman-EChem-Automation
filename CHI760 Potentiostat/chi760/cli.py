"""Mac-safe command line helpers for mapping, preflight, and dry-run checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .controller import CHI760Controller
from .dry_run_backend import DryRunCHI760E
from .ir_compensation import IRCompensationPlan
from .models import (
    CAParameters,
    CVParameters,
    CurrentStep,
    EISParameters,
    IMPEParameters,
    ISTEPParameters,
    ITParameters,
    OCPParameters,
    PotentialStep,
    STEPParameters,
    SWVParameters,
)
from .preflight import run_connection_preflight
from .sdk_mapping import sdk_mapping_manifest
from .trace import TraceReplayBackend, load_trace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m chi760",
        description="Connection-free CHI 760E development utilities.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("mapping", help="Print the unresolved SDK mapping manifest.")

    preflight = commands.add_parser(
        "preflight",
        help="Inspect SDK files without loading them or contacting a device.",
    )
    preflight.add_argument("sdk_files", nargs="*", help="Candidate DLL files to inspect.")
    preflight.add_argument(
        "--required-export",
        action="append",
        default=[],
        help="Exported symbol to require; repeat for multiple symbols.",
    )

    dry_run = commands.add_parser(
        "dry-run-smoke",
        help="Run all profiled 760E technique paths with zero hardware calls.",
    )
    dry_run.add_argument("--output", help="Optional path for the JSON trace.")

    replay = commands.add_parser(
        "replay",
        help="Validate and exactly replay a connection-free JSON trace.",
    )
    replay.add_argument("trace_file", help="Dry-run JSON trace to replay.")
    return parser


def run_dry_run_smoke() -> dict[str, object]:
    backend = DryRunCHI760E()
    controller = CHI760Controller(backend, model="760E")
    controller.connect()
    controller.run_ocp(OCPParameters(duration=5.0, sample_interval=0.5))
    controller.run_eis(
        EISParameters(
            dc_potential=0.0,
            ac_amplitude=0.01,
            start_frequency=100000.0,
            end_frequency=0.1,
            points_per_decade=10,
        )
    )
    backend.prepare_ir_compensation(
        IRCompensationPlan(),
        trial_ru_attempts_ohm=(
            (10.0, 10.1, 10.05),
            (10.1, 10.0, 10.05),
            (10.0, 10.05, 10.02),
        ),
        observed_fractions=(0.70, 0.90, 0.95),
    )
    controller.run_cv(
        CVParameters(
            initial_potential=0.0,
            high_potential=0.2,
            low_potential=-0.2,
            scan_rate=0.05,
            cycles=1,
        )
    )
    controller.run_it(
        ITParameters(potential=0.05, duration=2.0, sample_interval=0.5)
    )
    controller.run_ca(
        CAParameters(
            steps=(PotentialStep(potential_V=0.1, duration_s=2.0),),
            sample_interval_s=0.5,
        )
    )
    controller.run_swv(
        SWVParameters(
            initial_potential_V=0.2,
            final_potential_V=-0.2,
            increment_V=0.004,
            amplitude_V=0.025,
            frequency_Hz=15.0,
        )
    )
    controller.run_impe(
        IMPEParameters(
            initial_potential_V=-0.2,
            final_potential_V=0.2,
            potential_step_V=0.05,
            ac_amplitude_V_rms=0.01,
            frequency_Hz=1000.0,
        )
    )
    controller.run_step(
        STEPParameters(
            steps=(PotentialStep(potential_V=0.1, duration_s=2.0),),
            sample_interval_s=0.5,
        )
    )
    controller.run_istep(
        ISTEPParameters(
            steps=(CurrentStep(current_A=0.001, duration_s=2.0),),
            sample_interval_s=0.5,
        )
    )
    backend.disable_ir_compensation()
    backend.cell_off()
    controller.disconnect()
    return backend.trace_payload()


def replay_trace_file(path: str | Path) -> dict[str, object]:
    payload = load_trace(path)
    backend = TraceReplayBackend(payload)
    operations: list[str] = []
    for event in payload["events"]:
        operation = event["operation"]
        event_payload = event["payload"]
        if operation == "connect":
            backend.connect()
        elif operation == "disconnect":
            backend.disconnect()
        elif operation in {
            "run_cv",
            "run_it",
            "run_lsv",
            "run_eis",
            "run_ocp",
            "run_ca",
            "run_swv",
            "run_impe",
            "run_step",
            "run_istep",
        }:
            parameters = event_payload.get("parameters")
            if not isinstance(parameters, dict):
                raise ValueError(f"{operation} trace payload has no parameter object")
            getattr(backend, operation)(**parameters)
        elif operation == "prepare_ir_compensation":
            backend.prepare_ir_compensation(
                event_payload.get("plan"),
                trial_ru_attempts_ohm=event_payload.get("trial_ru_attempts_ohm", ()),
                observed_fractions=event_payload.get("observed_fractions", ()),
            )
        elif operation == "disable_ir_compensation":
            backend.disable_ir_compensation()
        elif operation == "cell_off":
            backend.cell_off()
        else:
            raise ValueError(f"unsupported trace operation {operation!r}")
        operations.append(operation)
    if backend.remaining_events:
        raise RuntimeError(f"trace replay left {backend.remaining_events} events")
    return {
        "trace_file": str(Path(path)),
        "replay_valid": True,
        "events_replayed": len(operations),
        "operations": operations,
        "hardware_connected": backend.hardware_connected,
        "hardware_calls": backend.hardware_calls,
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "mapping":
        payload = sdk_mapping_manifest()
    elif arguments.command == "preflight":
        payload = run_connection_preflight(
            arguments.sdk_files,
            required_exports=arguments.required_export,
        ).as_dict()
    elif arguments.command == "replay":
        payload = replay_trace_file(arguments.trace_file)
    else:
        payload = run_dry_run_smoke()

    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    output = getattr(arguments, "output", None)
    if output:
        Path(output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0
