from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from chi760.desktop_macro import (
    CHI760DDesktopController,
    DesktopMacroError,
    DummyCVPlan,
    DummySeriesPlan,
    render_dummy_cv_macro,
    render_dummy_series_macro,
)


def valid_protocol() -> dict[str, object]:
    return {
        "protocol_name": "760D internal dummy check",
        "target_model": "760D",
        "bench_state": "available",
        "validation": {"valid": True, "errors": [], "warnings": []},
        "raman_sync": {"policy": "none"},
        "ir_compensation": {"enabled": False},
        "steps": [
            {
                "source_technique": "cv",
                "name": "Bounded CV",
                "parameters": {
                    "initial_voltage_v": 0.0,
                    "apex1_voltage_v": 0.1,
                    "apex2_voltage_v": -0.1,
                    "final_voltage_v": 0.0,
                    "scan_rate_v_s": 0.1,
                    "step_size_v": 0.002,
                    "cycles": 1,
                },
            }
        ],
    }


def valid_series_protocol() -> dict[str, object]:
    protocol = valid_protocol()
    cv_step = protocol["steps"][0]  # type: ignore[index]
    protocol["protocol_name"] = "760D two-CV commissioning series"
    protocol["steps"] = [
        cv_step,
        {
            "source_technique": "wait",
            "name": "Cell-off delay",
            "parameters": {"duration_s": 5},
        },
        {
            **cv_step,  # type: ignore[dict-item]
            "name": "Second bounded CV",
        },
    ]
    return protocol


class FakeProcess:
    pid = 1234

    def __init__(self) -> None:
        self.return_code: int | None = None

    def poll(self) -> int | None:
        return self.return_code


class DesktopMacroTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.executable = self.root / "chi760d.exe"
        self.executable.write_bytes(b"audited-test-executable")
        self.expected_hash = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.data_root = self.root / "data"
        self.data_root.mkdir()
        self.launches: list[tuple[list[str], dict[str, object]]] = []
        self.process = FakeProcess()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def launcher(self, command: list[str], **kwargs: object) -> FakeProcess:
        self.launches.append((command, kwargs))
        return self.process

    def controller(self, *, enabled: bool) -> CHI760DDesktopController:
        return CHI760DDesktopController(
            self.executable,
            execution_enabled=enabled,
            expected_sha256=self.expected_hash,
            process_launcher=self.launcher,
        )

    def test_macro_contains_only_bounded_dummy_cv_and_cleanup(self) -> None:
        plan = DummyCVPlan.from_web_protocol(valid_protocol())
        macro = render_dummy_cv_macro(plan, self.data_root)

        self.assertIn("dummyon\n", macro)
        self.assertIn("abortov\n", macro)
        self.assertIn("tech:cv\n", macro)
        self.assertIn("eh:0.1\n", macro)
        self.assertIn("el:-0.1\n", macro)
        self.assertIn("cl:2\n", macro)
        self.assertIn("run\n", macro)
        self.assertIn("celloff\ndummyoff\n", macro)
        self.assertNotIn("fileoverride", macro)
        self.assertNotIn("noabort", macro)

    def test_series_macro_sequences_bounded_cv_and_cell_off_delays(self) -> None:
        plan = DummySeriesPlan.from_web_protocol(valid_series_protocol())
        macro = render_dummy_series_macro(plan, self.data_root)

        self.assertEqual(2, macro.count("tech:cv\n"))
        self.assertEqual(2, macro.count("run\n"))
        self.assertIn("celloff\ndelay:5\n", macro)
        self.assertIn("save:step_01_cv.bin\n", macro)
        self.assertIn("save:step_03_cv.bin\n", macro)
        self.assertTrue(macro.endswith("celloff\ndummyoff\nbeep\nend\n"))
        self.assertEqual(3, plan.public_summary()["step_count"])
        self.assertEqual(2, plan.public_summary()["cv_count"])

    def test_prepare_writes_files_without_launching_or_allowing_queue_spam(self) -> None:
        controller = self.controller(enabled=False)

        first = controller.prepare(valid_protocol(), self.data_root)
        with self.assertRaisesRegex(DesktopMacroError, "unused 760D preparation"):
            controller.prepare(valid_protocol(), self.data_root)

        self.assertTrue(first["preparation_token"])
        self.assertEqual([], self.launches)
        self.assertEqual(0, controller.hardware_calls)
        macros = list((self.data_root / "runs").rglob("*.mcr"))
        self.assertEqual(1, len(macros))

    def test_execution_is_locked_without_dedicated_runtime_flag(self) -> None:
        controller = self.controller(enabled=False)
        prepared = controller.prepare(valid_protocol(), self.data_root)

        with self.assertRaisesRegex(DesktopMacroError, "execution is locked"):
            controller.execute(str(prepared["preparation_token"]))

        self.assertEqual([], self.launches)
        self.assertEqual(0, controller.hardware_calls)

    def test_enabled_execution_launches_exact_executable_without_shell(self) -> None:
        controller = self.controller(enabled=True)
        prepared = controller.prepare(valid_protocol(), self.data_root)

        result = controller.execute(str(prepared["preparation_token"]))

        self.assertTrue(result["started"])
        self.assertEqual(1, controller.hardware_calls)
        command, options = self.launches[0]
        self.assertEqual(str(self.executable), command[0])
        self.assertTrue(command[1].startswith("/runmacro:"))
        self.assertEqual(False, options["shell"])
        self.assertEqual(str(self.executable.parent), options["cwd"])
        self.assertFalse(result["remote_stop_available"])
        metadata = next((self.data_root / "runs").rglob("metadata.json"))
        self.assertIn('"state": "running"', metadata.read_text(encoding="utf-8"))

    def test_unapproved_executable_hash_fails_closed(self) -> None:
        controller = CHI760DDesktopController(
            self.executable,
            execution_enabled=True,
            expected_sha256="0" * 64,
            process_launcher=self.launcher,
        )

        with self.assertRaisesRegex(DesktopMacroError, "hash does not match"):
            controller.prepare(valid_protocol(), self.data_root)

        self.assertFalse(controller.public_status()["experiment_control_enabled"])
        self.assertEqual([], self.launches)

    def test_windows_launch_failure_does_not_consume_preparation(self) -> None:
        def failing_launcher(_command: list[str], **_kwargs: object) -> FakeProcess:
            raise OSError("test launch failure")

        controller = CHI760DDesktopController(
            self.executable,
            execution_enabled=True,
            expected_sha256=self.expected_hash,
            process_launcher=failing_launcher,
        )
        prepared = controller.prepare(valid_protocol(), self.data_root)
        token = str(prepared["preparation_token"])

        with self.assertRaisesRegex(DesktopMacroError, "could not start"):
            controller.execute(token)

        self.assertEqual("SERIES", controller.preparation_summary(token)["technique"])

    def test_controller_prepares_multi_step_series_without_launching(self) -> None:
        controller = self.controller(enabled=False)

        prepared = controller.prepare(valid_series_protocol(), self.data_root)

        self.assertEqual(3, prepared["summary"]["step_count"])
        self.assertEqual(2, prepared["summary"]["cv_count"])
        self.assertEqual([], self.launches)
        macro = next((self.data_root / "runs").rglob("*.mcr")).read_text(encoding="ascii")
        self.assertEqual(2, macro.count("tech:cv"))

    def test_series_rejects_unsupported_steps_and_excessive_waits(self) -> None:
        protocol = valid_series_protocol()
        protocol["steps"][1]["source_technique"] = "ocp"  # type: ignore[index]
        with self.assertRaisesRegex(DesktopMacroError, "only bounded CV and wait"):
            DummySeriesPlan.from_web_protocol(protocol)

        protocol = valid_series_protocol()
        protocol["steps"][1]["parameters"]["duration_s"] = 301  # type: ignore[index]
        with self.assertRaisesRegex(DesktopMacroError, "delay must be"):
            DummySeriesPlan.from_web_protocol(protocol)

    def test_external_or_broad_protocols_are_rejected(self) -> None:
        protocol = valid_protocol()
        protocol["target_model"] = "760B"
        with self.assertRaisesRegex(DesktopMacroError, "requires target model CHI 760D"):
            DummyCVPlan.from_web_protocol(protocol)

        protocol = valid_protocol()
        protocol["bench_state"] = "busy"
        with self.assertRaisesRegex(DesktopMacroError, "locked for offline planning"):
            DummyCVPlan.from_web_protocol(protocol)

        protocol = valid_protocol()
        steps = protocol["steps"]
        self.assertIsInstance(steps, list)
        protocol["steps"] = steps + steps  # type: ignore[operator]
        with self.assertRaisesRegex(DesktopMacroError, "exactly one CV"):
            DummyCVPlan.from_web_protocol(protocol)

        protocol = valid_protocol()
        protocol["ir_compensation"] = {"enabled": True}
        with self.assertRaisesRegex(DesktopMacroError, "Disable iR"):
            DummyCVPlan.from_web_protocol(protocol)

        protocol = valid_protocol()
        step = protocol["steps"][0]  # type: ignore[index]
        step["parameters"]["apex1_voltage_v"] = 0.3  # type: ignore[index]
        with self.assertRaisesRegex(DesktopMacroError, "limited to"):
            DummyCVPlan.from_web_protocol(protocol)


if __name__ == "__main__":
    unittest.main()
