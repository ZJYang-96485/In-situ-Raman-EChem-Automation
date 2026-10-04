from __future__ import annotations

import unittest
from pathlib import Path
import struct
import tempfile

from chi760 import (
    CHI760ELiveBackend,
    ELECTROCHEMISTRY_ONLY,
    HardwareOperation,
    HardwareOperationBlockedError,
    InstalledCHIEvidence,
    InvalidVendorResponseError,
    LiveConnectionState,
    VendorCallTimeoutError,
    VendorEvidenceUnavailableError,
    VendorResponse,
    VerifiedDiscoveryMapping,
    inspect_installed_chi,
)


def _evidence() -> InstalledCHIEvidence:
    return InstalledCHIEvidence(
        executable_path="C:/verified/chi760e.exe",
        executable_sha256="a" * 64,
        executable_architecture="x86",
        executable_bitness=32,
        software_version="26.6",
        help_path="C:/verified/chi760e.chm",
        help_sha256="b" * 64,
        documented_automation_mechanism="test adapter only",
        read_only_identity_query_documented=True,
    )


def _mapping() -> VerifiedDiscoveryMapping:
    return VerifiedDiscoveryMapping(
        interface_kind="fake_verified_test_boundary",
        evidence_paths=("tests/fake-vendor-evidence",),
        open_identifier="fake.open",
        model_identifier="fake.model",
        serial_identifier="fake.serial",
        firmware_identifier="fake.firmware",
        software_identifier="fake.software",
        capabilities_identifier="fake.capabilities",
        close_identifier="fake.close",
    )


class FakeDiscoveryTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []
        self.responses = {
            "fake.open": VendorResponse(True, True, "FAKE_OK"),
            "fake.model": VendorResponse(True, "CHI 760E", "FAKE_OK"),
            "fake.serial": VendorResponse(True, "FAKE-SERIAL", "FAKE_OK"),
            "fake.firmware": VendorResponse(True, "FAKE-FW", "FAKE_OK"),
            "fake.software": VendorResponse(True, "26.6", "FAKE_OK"),
            "fake.capabilities": VendorResponse(
                True, {"identity_query": True}, "FAKE_OK"
            ),
            "fake.close": VendorResponse(True, True, "FAKE_OK"),
        }

    def call(self, identifier: str, *, timeout_s: float) -> VendorResponse:
        self.calls.append((identifier, timeout_s))
        response = self.responses[identifier]
        if isinstance(response, Exception):
            raise response
        return response


class LiveBackendBoundaryTests(unittest.TestCase):
    def test_installed_paths_are_supplied_at_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            installation = Path(directory) / "arbitrary vendor location"
            installation.mkdir()
            executable = installation / "device-software.exe"
            executable.write_bytes(_minimal_pe())
            help_file = installation / "matching-help.chm"
            help_file.write_bytes(b"matching test help")

            evidence = inspect_installed_chi(
                executable,
                help_file,
                software_version="test-version",
            )

        self.assertEqual(str(executable), evidence.executable_path)
        self.assertEqual(str(help_file), evidence.help_path)
        self.assertEqual("test-version", evidence.software_version)
        self.assertEqual("x86", evidence.executable_architecture)

    def test_installed_unresolved_mapping_cannot_reach_transport(self):
        transport = FakeDiscoveryTransport()
        backend = CHI760ELiveBackend(_evidence(), transport=transport)

        with self.assertRaises(VendorEvidenceUnavailableError):
            backend.connect()

        self.assertEqual([], transport.calls)
        self.assertEqual(0, backend.hardware_calls)
        self.assertEqual(LiveConnectionState.DISCONNECTED, backend.connection_state)
        self.assertIn("no transport call made", backend.trace_events[0].error or "")

    def test_fake_verified_identity_sequence_is_read_only_and_traced(self):
        transport = FakeDiscoveryTransport()
        backend = CHI760ELiveBackend(
            _evidence(), mapping=_mapping(), transport=transport, timeout_s=2.5
        )

        self.assertTrue(backend.connect())
        identity = backend.query_identity()
        capabilities = backend.query_capabilities()
        backend.disconnect()

        self.assertEqual("CHI 760E", identity["model"])
        self.assertEqual("FAKE-SERIAL", identity["serial_number"])
        self.assertEqual({"identity_query": True}, capabilities)
        self.assertEqual(
            [
                "fake.open",
                "fake.model",
                "fake.serial",
                "fake.firmware",
                "fake.software",
                "fake.capabilities",
                "fake.close",
            ],
            [identifier for identifier, _timeout in transport.calls],
        )
        self.assertTrue(all(timeout == 2.5 for _identifier, timeout in transport.calls))
        self.assertEqual(LiveConnectionState.DISCONNECTED, backend.connection_state)
        self.assertTrue(all(event.return_code == "FAKE_OK" for event in backend.trace_events))

    def test_every_experiment_path_is_blocked_before_transport(self):
        transport = FakeDiscoveryTransport()
        backend = CHI760ELiveBackend(
            _evidence(), mapping=_mapping(), transport=transport
        )
        experiment_methods = (
            backend.run_cv,
            backend.run_it,
            backend.run_lsv,
            backend.run_eis,
            backend.run_ocp,
            backend.run_ca,
            backend.run_swv,
            backend.run_impe,
            backend.run_step,
            backend.run_istep,
            backend.cell_off,
            backend.prepare_ir_compensation,
            backend.disable_ir_compensation,
        )

        for method in experiment_methods:
            with self.subTest(method=method.__name__):
                with self.assertRaises(HardwareOperationBlockedError):
                    method()

        self.assertEqual([], transport.calls)
        self.assertEqual(0, backend.hardware_calls)

    def test_invalid_identity_fails_closed_using_verified_close(self):
        transport = FakeDiscoveryTransport()
        transport.responses["fake.model"] = VendorResponse(True, None, "FAKE_OK")
        backend = CHI760ELiveBackend(
            _evidence(), mapping=_mapping(), transport=transport
        )
        backend.connect()

        with self.assertRaises(InvalidVendorResponseError):
            backend.query_identity()

        self.assertEqual(LiveConnectionState.DISCONNECTED, backend.connection_state)
        self.assertEqual("fake.close", transport.calls[-1][0])
        invalid_event = next(
            event
            for event in backend.trace_events
            if event.operation == "query_model"
        )
        self.assertFalse(invalid_event.success)

    def test_timeout_is_failure_not_success(self):
        transport = FakeDiscoveryTransport()
        transport.responses["fake.open"] = TimeoutError("fake timeout")  # type: ignore[assignment]
        backend = CHI760ELiveBackend(
            _evidence(), mapping=_mapping(), transport=transport
        )

        with self.assertRaises(VendorCallTimeoutError):
            backend.connect()

        self.assertEqual(LiveConnectionState.DISCONNECTED, backend.connection_state)
        self.assertFalse(backend.trace_events[-1].success)

    def test_runtime_profile_blocks_every_non_electrochemistry_domain(self):
        calls = 0

        def action() -> None:
            nonlocal calls
            calls += 1

        blocked = (
            HardwareOperation.CHI_EXPERIMENT,
            HardwareOperation.IR_COMPENSATION,
            HardwareOperation.RAMAN_ACQUISITION,
            HardwareOperation.LASER_CONTROL,
            HardwareOperation.TTL_TRIGGER,
            HardwareOperation.RDE_MOTOR_CONTROL,
            HardwareOperation.ML_ACTION,
            HardwareOperation.AUTOMATED_DECISION,
        )
        for operation in blocked:
            with self.subTest(operation=operation):
                with self.assertRaises(HardwareOperationBlockedError):
                    ELECTROCHEMISTRY_ONLY.dispatch(operation, operation.value, action)

        self.assertEqual(0, calls)


def _minimal_pe() -> bytes:
    data = bytearray(512)
    data[:2] = b"MZ"
    pe_offset = 0x80
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset:pe_offset + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, pe_offset + 4, 0x014C)
    struct.pack_into("<H", data, pe_offset + 6, 0)
    struct.pack_into("<H", data, pe_offset + 20, 104)
    struct.pack_into("<H", data, pe_offset + 24, 0x10B)
    return bytes(data)


if __name__ == "__main__":
    unittest.main()
