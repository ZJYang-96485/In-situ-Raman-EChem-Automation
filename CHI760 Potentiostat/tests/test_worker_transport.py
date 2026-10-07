from __future__ import annotations

from pathlib import Path
import struct
import sys
import tempfile
import unittest
from typing import Any, Mapping

from chi760.worker_transport import (
    PersistentSDKWorker,
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


class WorkerTransportTests(unittest.TestCase):
    def test_defaults_are_repository_relative_not_machine_coded(self) -> None:
        config = default_worker_launch_config()

        self.assertEqual("python.exe", config.python_executable.name)
        self.assertEqual("sdk_worker.py", config.worker_script.name)
        self.assertEqual(config.sdk_directory, config.runtime_directory)
        self.assertEqual("libec760e.dll", config.dll_name)

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


if __name__ == "__main__":
    unittest.main()
