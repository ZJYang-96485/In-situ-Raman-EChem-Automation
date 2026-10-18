from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from typing import Any, Mapping

from chi760.worker_transport import (
    CHI760ECommissioningError,
    PersistentSDKWorker,
    REQUIRED_760E_COMMISSIONING_CONFIRMATIONS,
    SDKWorkerCommissioningGateway,
    SDKWorkerDiscoveryGateway,
    WorkerLaunchConfig,
    default_worker_launch_config,
)


class FakeWorker:
    def __init__(self, *, ready: bool = True) -> None:
        self.running = True
        self.closed = False
        self.requests: list[str] = []
        self.status = {
            "ready_to_load": ready,
            "process_bitness": 32,
            "library_bitness": 32,
            "error": None if ready else "test SDK unavailable",
        }

    def start(self) -> dict[str, object]:
        return dict(self.status)

    def request(
        self,
        command: str,
        *,
        payload: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]:
        del payload, timeout_s
        self.requests.append(command)
        return {
            "error": None,
            "reported_model_series": "760E",
            "supported_techniques": [{"name": "CV", "id": 0}],
            "vendor_functions_called": 3,
            "process_bitness": 32,
            "library_bitness": 32,
            "library_sha256": "abc123",
            "note": "SDK metadata only",
        }

    def close(self) -> None:
        self.closed = True
        self.running = False


class FakeCommissioningWorker(FakeWorker):
    def __init__(self) -> None:
        super().__init__()
        self.status.update(
            {
                "commissioning_mode_enabled": True,
                "experiments_enabled": True,
                "missing_commissioning_exports": [],
            }
        )
        self.request_payloads: list[tuple[str, Mapping[str, Any] | None]] = []
        self.x_values = [-0.1, 0.0, 0.1]
        self.y_values = [-1e-6, 0.0, 1e-6]

    def request(
        self,
        command: str,
        *,
        payload: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]:
        del timeout_s
        self.requests.append(command)
        self.request_payloads.append((command, payload))
        if command == "cv-start":
            return {"job_id": "job-760e", "state": "starting", "target_model": "760E"}
        if command == "cv-status":
            return {
                "job_id": "job-760e",
                "state": "completed",
                "data_points": 3,
                "result_available": True,
                "stop_requested": False,
                "error": None,
            }
        if command == "cv-stop":
            return {"job_id": "job-760e", "state": "stopping"}
        if command == "cv-result":
            offset = int((payload or {}).get("offset", 0))
            limit = int((payload or {}).get("limit", 4096))
            end = min(len(self.x_values), offset + limit)
            return {
                "job_id": "job-760e",
                "offset": offset,
                "count": max(0, end - offset),
                "total": len(self.x_values),
                "next_offset": end if end < len(self.x_values) else None,
                "x_values": self.x_values[offset:end],
                "y_values": self.y_values[offset:end],
                "units": {"x": "V", "y": "A"},
            }
        return super().request(command, payload=payload)


def bounded_760e_plan() -> dict[str, object]:
    return {
        "target_model": "760E",
        "initial_potential_v": 0.0,
        "high_potential_v": 0.2,
        "low_potential_v": -0.2,
        "initial_scan_direction": "positive",
        "scan_rate_v_s": 0.05,
        "potential_step_v": 0.002,
        "quiet_time_s": 0.0,
        "sweep_segments": 2,
    }


def commissioning_confirmations() -> dict[str, bool]:
    return {name: True for name in REQUIRED_760E_COMMISSIONING_CONFIRMATIONS}


class WorkerTransportTests(unittest.TestCase):
    def test_defaults_are_repository_relative_not_machine_coded(self) -> None:
        config = default_worker_launch_config()

        self.assertEqual("python.exe", config.python_executable.name)
        self.assertEqual("sdk_worker.py", config.worker_script.name)
        self.assertEqual(config.sdk_directory, config.runtime_directory)
        self.assertEqual("libec760e.dll", config.dll_name)
        self.assertNotIn("--enable-chi760e-commissioning", config.command())

    def test_commissioning_worker_flag_is_explicit_in_launch_command(self) -> None:
        config = default_worker_launch_config()
        enabled = WorkerLaunchConfig(
            python_executable=config.python_executable,
            worker_script=config.worker_script,
            sdk_directory=config.sdk_directory,
            runtime_directory=config.runtime_directory,
            dll_name=config.dll_name,
            enable_chi760e_commissioning=True,
        )

        self.assertEqual(
            1, enabled.command().count("--enable-chi760e-commissioning")
        )

    def test_persistent_process_handles_multiple_requests(self) -> None:
        worker_script = (
            Path(__file__).resolve().parents[1] / "chi760" / "sdk_worker.py"
        )
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            worker = PersistentSDKWorker(
                WorkerLaunchConfig(
                    python_executable=Path(sys.executable),
                    worker_script=worker_script,
                    sdk_directory=runtime,
                    runtime_directory=runtime,
                )
            )
            try:
                first = worker.start()
                second = worker.request("status")
                self.assertTrue(worker.running)
                self.assertEqual(struct.calcsize("P") * 8, first["process_bitness"])
                self.assertEqual(first["process_bitness"], second["process_bitness"])
                self.assertFalse(first["library_loaded"])
            finally:
                worker.close()
            self.assertFalse(worker.running)

    def test_gateway_exposes_sdk_readiness_without_claiming_physical_identity(self) -> None:
        worker = FakeWorker()
        gateway = SDKWorkerDiscoveryGateway(worker)

        status = gateway.public_status()
        discovery = gateway.discover()

        self.assertTrue(status["worker_connected"])
        self.assertTrue(status["discovery_enabled"])
        self.assertFalse(status["experiment_control_enabled"])
        self.assertFalse(status["physical_connection_confirmed"])
        self.assertFalse(discovery["physical_connection_confirmed"])
        self.assertEqual("Not provided by libec", discovery["identity"]["serial_number"])
        self.assertEqual(["discover"], worker.requests)
        self.assertEqual(0, gateway.hardware_calls)
        self.assertEqual(3, gateway.vendor_functions_called)
        gateway.close()
        self.assertTrue(worker.closed)

    def test_gateway_stays_locked_when_worker_preflight_fails(self) -> None:
        gateway = SDKWorkerDiscoveryGateway(FakeWorker(ready=False))

        status = gateway.public_status()

        self.assertFalse(status["discovery_enabled"])
        self.assertEqual("adapter_unavailable", status["state"])
        self.assertIn("test SDK unavailable", status["blocker"])

    def test_commissioning_prepare_is_disk_only_then_start_and_status_save_data(self) -> None:
        worker = FakeCommissioningWorker()
        gateway = SDKWorkerCommissioningGateway(
            worker,
            execution_enabled=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preparation = gateway.prepare(
                bounded_760e_plan(), root, "760E catalyst screening"
            )

            self.assertEqual([], worker.requests)
            protocol_files = list(root.glob("runs/*/*/*/protocol.json"))
            self.assertEqual(1, len(protocol_files))
            self.assertEqual("trial-001", preparation["run_label"])
            self.assertEqual("760E catalyst screening", preparation["task_folder"])
            protocol = protocol_files[0].read_text(encoding="utf-8")
            self.assertIn('"target_model": "760E"', protocol)
            self.assertIn('"task_name": "760E catalyst screening"', protocol)

            started = gateway.start(
                str(preparation["preparation_token"]),
                commissioning_confirmations(),
            )
            status = gateway.job_status(str(started["job_id"]))

            self.assertTrue(started["started"])
            self.assertEqual("completed", status["state"])
            self.assertTrue(status["data_saved"])
            self.assertEqual(
                ["cv-start", "cv-status", "cv-result"], worker.requests
            )
            raw_files = list(root.glob("runs/*/*/*/echem_raw.csv"))
            self.assertEqual(1, len(raw_files))
            self.assertEqual(
                "potential_V,current_A\n-0.1,-1e-06\n0,0\n0.1,1e-06\n",
                raw_files[0].read_text(encoding="ascii"),
            )
            metadata_files = list(root.glob("runs/*/*/*/metadata.json"))
            metadata = metadata_files[0].read_text(encoding="utf-8")
            self.assertIn('"state": "completed"', metadata)
            self.assertNotIn(str(root), json.dumps(status))

    def test_commissioning_stays_locked_without_both_enable_layers(self) -> None:
        worker = FakeCommissioningWorker()
        gateway = SDKWorkerCommissioningGateway(
            worker,
            execution_enabled=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CHI760ECommissioningError):
                gateway.prepare(
                    bounded_760e_plan(), Path(directory), "760E locked test"
                )

        self.assertFalse(gateway.public_status()["experiment_control_enabled"])
        self.assertEqual([], worker.requests)

    def test_commissioning_start_rechecks_every_confirmation(self) -> None:
        worker = FakeCommissioningWorker()
        gateway = SDKWorkerCommissioningGateway(
            worker,
            execution_enabled=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            preparation = gateway.prepare(
                bounded_760e_plan(), Path(directory), "760E confirmation test"
            )
            confirmations = commissioning_confirmations()
            confirmations["no_other_chi_measurement_running"] = False

            with self.assertRaisesRegex(
                CHI760ECommissioningError, "no_other_chi_measurement_running"
            ):
                gateway.start(
                    str(preparation["preparation_token"]), confirmations
                )

        self.assertEqual([], worker.requests)

    def test_bridge_side_plan_validation_rejects_expanded_voltage_before_disk_or_worker(self) -> None:
        worker = FakeCommissioningWorker()
        gateway = SDKWorkerCommissioningGateway(
            worker,
            execution_enabled=True,
        )
        plan = bounded_760e_plan()
        plan["high_potential_v"] = 0.3
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(CHI760ECommissioningError, "0.25"):
                gateway.prepare(plan, root, "760E expanded voltage test")

            self.assertFalse((root / "runs").exists())
        self.assertEqual([], worker.requests)


if __name__ == "__main__":
    unittest.main()
