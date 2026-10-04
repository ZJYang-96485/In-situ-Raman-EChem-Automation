import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import struct
import tempfile
import unittest

from chi760 import (
    BackendStateError,
    CAParameters,
    CHI760Controller,
    CHI760E_IR_MAPPING,
    CHI760E_TECHNIQUE_MAPPINGS,
    CHI760E_UNVERIFIED_TECHNIQUE_MAPPINGS,
    CVParameters,
    DryRunCHI760E,
    IRSDKMapping,
    IRCompensationPlan,
    LiveExecutionUnavailableError,
    MappingStatus,
    PotentialStep,
    SDKCandidateInspection,
    Technique,
    TraceMismatchError,
    TraceReplayBackend,
    TraceValidationError,
    inspect_sdk_candidate,
    run_connection_preflight,
    sdk_mapping_manifest,
    validate_trace_payload,
)
from chi760.cli import main
from chi760.trace import json_safe


class ConnectionBoundaryTests(unittest.TestCase):
    def test_dry_run_controller_records_zero_hardware_operations(self):
        backend = DryRunCHI760E()
        controller = CHI760Controller(backend, model="760E")
        self.assertTrue(controller.connect())
        cv = controller.run_cv(CVParameters(0.0, 0.2, -0.2, 0.05, 1))
        ca = controller.run_ca(
            CAParameters([PotentialStep(0.1, 2.0)], sample_interval_s=1.0)
        )
        controller.disconnect()

        self.assertEqual("dry_run", cv["execution_mode"])
        self.assertEqual("documented_libec", cv["mapping_status"])
        self.assertIsNone(cv["sdk_entrypoint"])
        self.assertEqual([], ca["current_A"])
        self.assertFalse(backend.hardware_connected)
        self.assertFalse(backend.sdk_loaded)
        self.assertEqual(0, backend.hardware_calls)

        payload = backend.trace_payload()
        self.assertFalse(payload["hardware_connected"])
        self.assertEqual(0, payload["hardware_calls"])
        self.assertEqual(
            ["connect", "run_cv", "run_ca", "disconnect"],
            [event["operation"] for event in payload["events"]],
        )
        json.dumps(payload)

    def test_dry_run_requires_explicit_logical_session(self):
        backend = DryRunCHI760E()
        with self.assertRaises(BackendStateError):
            backend.run_cv(initial_potential=0.0)
        backend.connect()
        with self.assertRaises(BackendStateError):
            backend.connect()
        backend.disconnect()
        with self.assertRaises(BackendStateError):
            backend.disconnect()

    def test_trace_replay_matches_parameters_and_rejects_drift(self):
        parameters = CVParameters(0.0, 0.2, -0.2, 0.05, 1)
        backend = DryRunCHI760E()
        controller = CHI760Controller(backend, model="760E")
        controller.connect()
        expected = controller.run_cv(parameters)
        controller.disconnect()

        replay = TraceReplayBackend(backend.trace_payload())
        replay_controller = CHI760Controller(replay, model="760E")
        with self.assertRaises(TraceMismatchError):
            replay_controller.run_cv(parameters)
        self.assertTrue(replay_controller.connect())
        self.assertEqual(expected, replay_controller.run_cv(parameters))
        replay_controller.disconnect()
        self.assertEqual(0, replay.remaining_events)
        self.assertEqual(0, replay.hardware_calls)

        mismatched = TraceReplayBackend(backend.trace_payload())
        mismatched.connect()
        with self.assertRaises(TraceMismatchError):
            mismatched.run_cv(
                initial_potential=0.1,
                high_potential=0.2,
                low_potential=-0.2,
                scan_rate=0.05,
                cycles=1,
            )

    def test_ir_dry_run_records_trials_but_never_reports_hardware_application(self):
        backend = DryRunCHI760E()
        backend.connect()
        plan = IRCompensationPlan()
        result = backend.prepare_ir_compensation(
            plan,
            trial_ru_attempts_ohm=(
                (10.0, 10.1, 10.05),
                (10.2, 10.1, 10.15),
                (10.0, 10.05, 10.02),
            ),
            observed_fractions=(0.70, 0.90, 0.95),
        )
        disabled = backend.disable_ir_compensation()
        cell_off = backend.cell_off()
        backend.disconnect()

        self.assertEqual("planned_not_hardware_applied", result["state"])
        self.assertEqual(3, result["progress"]["accepted_trial_number"])
        self.assertFalse(result["hardware_applied"])
        self.assertIsNone(result["mapping"]["apply_compensation_entrypoint"])
        self.assertFalse(disabled["hardware_state_changed"])
        self.assertFalse(cell_off["hardware_state_changed"])
        self.assertEqual(0, result["hardware_calls"])

        replay = TraceReplayBackend(backend.trace_payload())
        replay.connect()
        replayed = replay.prepare_ir_compensation(
            plan,
            trial_ru_attempts_ohm=(
                (10.0, 10.1, 10.05),
                (10.2, 10.1, 10.15),
                (10.0, 10.05, 10.02),
            ),
            observed_fractions=(0.70, 0.90, 0.95),
        )
        self.assertEqual(result, replayed)
        replay.disable_ir_compensation()
        replay.cell_off()
        replay.disconnect()
        self.assertEqual(0, replay.remaining_events)

    def test_ir_input_mismatch_is_blocking_and_live_request_is_unavailable(self):
        backend = DryRunCHI760E()
        backend.connect()
        with self.assertRaisesRegex(ValueError, "plan is disabled"):
            backend.prepare_ir_compensation(
                IRCompensationPlan(enabled=False),
                trial_ru_attempts_ohm=((10.0, 10.1),),
                observed_fractions=(0.8,),
            )
        with self.assertRaisesRegex(ValueError, "equal lengths"):
            backend.prepare_ir_compensation(
                IRCompensationPlan(),
                trial_ru_attempts_ohm=((10.0, 10.1),),
                observed_fractions=(0.8, 0.9),
            )
        with self.assertRaises(LiveExecutionUnavailableError):
            backend.request_live_execution()

    def test_manifest_covers_every_internal_technique_without_invented_bindings(self):
        self.assertEqual(set(Technique), set(CHI760E_TECHNIQUE_MAPPINGS))
        documented = [
            mapping
            for mapping in CHI760E_TECHNIQUE_MAPPINGS.values()
            if mapping.status is MappingStatus.DOCUMENTED_LIBEC
        ]
        self.assertTrue(documented)
        self.assertTrue(all(mapping.sdk_entrypoint is None for mapping in documented))
        self.assertFalse(CHI760E_IR_MAPPING.live_binding_resolved)
        self.assertFalse(
            IRSDKMapping(
                measure_ru_entrypoint="",
                apply_compensation_entrypoint="apply",
                readback_entrypoint="read",
                disable_compensation_entrypoint="disable",
                cell_off_entrypoint="cell_off",
                mode_parameter_identifier="mode",
                resistance_parameter_identifier="resistance",
                readback_parameter_identifier="readback",
            ).live_binding_resolved
        )
        self.assertIn("GEIS", CHI760E_UNVERIFIED_TECHNIQUE_MAPPINGS)
        manifest = sdk_mapping_manifest()
        self.assertFalse(manifest["hardware_execution_enabled"])
        self.assertIn("ir_compensation", manifest["unresolved_live_bindings"])
        self.assertIn("GEIS", manifest["unverified_techniques"])
        self.assertFalse(
            manifest["derived_outputs"]["chronocoulometry_C"][
                "separate_sdk_technique_claimed"
            ]
        )

    def test_preflight_on_mac_requires_no_connection_or_library_load(self):
        report = run_connection_preflight()
        self.assertEqual("awaiting_sdk_artifacts", report.status)
        self.assertFalse(report.sdk_loaded)
        self.assertFalse(report.device_contacted)
        self.assertFalse(report.ready_for_live_connection)
        self.assertTrue(report.unresolved_live_bindings)

    def test_preflight_reads_pe_architecture_without_loading_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            dll_path = Path(directory) / "candidate.dll"
            dll_path.write_bytes(_minimal_pe(machine=0x014C, magic=0x10B))
            candidate = inspect_sdk_candidate(dll_path)
            report = run_connection_preflight((dll_path,))

        self.assertIsNone(candidate.error)
        self.assertEqual("PE", candidate.file_format)
        self.assertEqual("x86", candidate.architecture)
        self.assertEqual(32, candidate.bitness)
        self.assertTrue(candidate.sha256)
        self.assertEqual("inspection_complete_mapping_required", report.status)
        self.assertFalse(report.sdk_loaded)
        self.assertFalse(report.device_contacted)

        unknown_machine = _inspect_sdk_candidate_bytes_for_test(
            _minimal_pe(machine=0x9999, magic=0x10B)
        )
        self.assertFalse(unknown_machine.is_32_bit_windows_pe)

    def test_preflight_reads_export_names_without_loading_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            dll_path = Path(directory) / "candidate.dll"
            dll_path.write_bytes(_minimal_pe_with_export("verified_example"))
            candidate = inspect_sdk_candidate(dll_path)
            report = run_connection_preflight(
                (dll_path,), required_exports=("verified_example",)
            )

        self.assertEqual(("verified_example",), candidate.exported_symbols)
        self.assertEqual((), report.missing_required_exports)
        self.assertEqual("inspection_complete_mapping_required", report.status)
        self.assertFalse(report.sdk_loaded)
        self.assertFalse(report.device_contacted)

    def test_preflight_rejects_non_pe_and_reports_missing_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid_path = Path(directory) / "not-a-dll.txt"
            invalid_path.write_text("not a PE file", encoding="utf-8")
            invalid = inspect_sdk_candidate(invalid_path)

            dll_path = Path(directory) / "candidate.dll"
            dll_path.write_bytes(_minimal_pe(machine=0x014C, magic=0x10B))
            report = run_connection_preflight(
                (dll_path,), required_exports=("not_yet_verified",)
            )

        self.assertIn("not a Windows PE file", invalid.error or "")
        self.assertEqual("required_exports_missing", report.status)
        self.assertEqual(("not_yet_verified",), report.missing_required_exports)

    def test_trace_validation_rejects_hardware_or_sequence_ambiguity(self):
        payload = {
            "schema_version": "0.1",
            "execution_mode": "dry_run",
            "hardware_connected": False,
            "hardware_calls": 1,
            "events": [],
        }
        with self.assertRaises(TraceValidationError):
            validate_trace_payload(payload)

        payload["hardware_calls"] = 0
        payload["events"] = [
            {
                "sequence": 2,
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "monotonic_ns": 0,
                "operation": "connect",
                "payload": {},
                "result": {},
            }
        ]
        with self.assertRaises(TraceValidationError):
            validate_trace_payload(payload)

    def test_trace_validation_rejects_silent_numeric_and_clock_corruption(self):
        payload = {
            "schema_version": "0.1",
            "execution_mode": "dry_run",
            "hardware_connected": False,
            "hardware_calls": 0,
            "events": [
                {
                    "sequence": 0,
                    "timestamp_utc": "2026-01-01T00:00:00+00:00",
                    "monotonic_ns": 1,
                    "operation": "run_cv",
                    "payload": {"parameters": {"scan_rate": float("nan")}},
                    "result": {},
                }
            ],
        }
        with self.assertRaises(TraceValidationError):
            validate_trace_payload(payload)

        with self.assertRaisesRegex(TypeError, "keys must be strings"):
            json_safe({1: "first", "1": "second"})

        payload["events"][0]["payload"] = {}
        payload["events"][0]["timestamp_utc"] = "2026-01-01T00:00:00"
        with self.assertRaises(TraceValidationError):
            validate_trace_payload(payload)

        payload["events"][0]["timestamp_utc"] = "2026-01-01T00:00:00+00:00"
        payload["events"][0]["monotonic_ns"] = -1
        with self.assertRaises(TraceValidationError):
            validate_trace_payload(payload)

        payload["events"][0]["monotonic_ns"] = 1
        payload["events"][0]["timestamp_utc"] = "2026-01-01T01:00:00+01:00"
        with self.assertRaises(TraceValidationError):
            validate_trace_payload(payload)

    def test_mac_safe_cli_runs_mapping_preflight_and_full_dry_run(self):
        for arguments in (("mapping",), ("preflight",), ("dry-run-smoke",)):
            with self.subTest(arguments=arguments):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(0, main(arguments))
                payload = json.loads(output.getvalue())
                if arguments[0] == "dry-run-smoke":
                    self.assertEqual(0, payload["hardware_calls"])
                    self.assertFalse(payload["hardware_connected"])
                    self.assertEqual(
                        [
                            "connect",
                            "run_ocp",
                            "run_eis",
                            "prepare_ir_compensation",
                            "run_cv",
                            "run_it",
                            "run_ca",
                            "run_swv",
                            "run_impe",
                            "run_step",
                            "run_istep",
                            "disable_ir_compensation",
                            "cell_off",
                            "disconnect",
                        ],
                        [event["operation"] for event in payload["events"]],
                    )

    def test_mac_safe_cli_writes_and_exactly_replays_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "dry-run.json"
            self.assertEqual(
                0,
                main(("dry-run-smoke", "--output", str(trace_path))),
            )
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(("replay", str(trace_path))))

        replay = json.loads(output.getvalue())
        self.assertTrue(replay["replay_valid"])
        self.assertEqual(14, replay["events_replayed"])
        self.assertEqual(0, replay["hardware_calls"])
        self.assertFalse(replay["hardware_connected"])


def _minimal_pe(*, machine: int, magic: int) -> bytes:
    data = bytearray(512)
    data[:2] = b"MZ"
    pe_offset = 0x80
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset:pe_offset + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, pe_offset + 4, machine)
    struct.pack_into("<H", data, pe_offset + 6, 0)
    optional_size = 104 if magic == 0x10B else 120
    struct.pack_into("<H", data, pe_offset + 20, optional_size)
    struct.pack_into("<H", data, pe_offset + 24, magic)
    return bytes(data)


def _minimal_pe_with_export(symbol: str) -> bytes:
    data = bytearray(1024)
    data[:2] = b"MZ"
    pe_offset = 0x80
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset:pe_offset + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, pe_offset + 4, 0x014C)
    struct.pack_into("<H", data, pe_offset + 6, 1)
    optional_size = 104
    struct.pack_into("<H", data, pe_offset + 20, optional_size)
    optional_offset = pe_offset + 24
    struct.pack_into("<H", data, optional_offset, 0x10B)
    struct.pack_into("<II", data, optional_offset + 96, 0x1000, 40)

    section_offset = optional_offset + optional_size
    data[section_offset:section_offset + 8] = b".edata\x00\x00"
    struct.pack_into("<I", data, section_offset + 8, 0x200)
    struct.pack_into("<I", data, section_offset + 12, 0x1000)
    struct.pack_into("<I", data, section_offset + 16, 0x200)
    struct.pack_into("<I", data, section_offset + 20, 0x200)

    export_offset = 0x200
    struct.pack_into("<I", data, export_offset + 24, 1)
    struct.pack_into("<I", data, export_offset + 32, 0x1040)
    struct.pack_into("<I", data, 0x240, 0x1050)
    encoded_symbol = symbol.encode("ascii") + b"\x00"
    data[0x250:0x250 + len(encoded_symbol)] = encoded_symbol
    return bytes(data)


def _inspect_sdk_candidate_bytes_for_test(data: bytes) -> SDKCandidateInspection:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "candidate.dll"
        path.write_bytes(data)
        return inspect_sdk_candidate(path)


if __name__ == "__main__":
    unittest.main()
