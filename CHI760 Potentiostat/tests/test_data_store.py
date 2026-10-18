from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from chi760 import RunDataStore, RunDirectoryExistsError


class RunDataStoreTests(unittest.TestCase):
    def test_layout_contains_no_fake_run(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunDataStore(Path(directory) / "data")
            store.ensure_layout()

            self.assertTrue(store.runs_root.is_dir())
            self.assertTrue(store.discovery_root.is_dir())
            self.assertTrue(store.simulations_root.is_dir())
            self.assertEqual([], list(store.runs_root.iterdir()))

    def test_default_run_ids_are_unique_at_the_same_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunDataStore(Path(directory) / "data")
            timestamp = datetime(2026, 10, 4, 15, 30, tzinfo=timezone.utc)

            first = store.create_run(timestamp=timestamp)
            second = store.create_run(timestamp=timestamp)

            self.assertNotEqual(first.paths.directory, second.paths.directory)
            self.assertTrue(first.paths.directory.is_dir())
            self.assertTrue(second.paths.directory.is_dir())

    def test_existing_run_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunDataStore(Path(directory) / "data")
            timestamp = datetime(2026, 10, 4, 15, 30, tzinfo=timezone.utc)
            first = store.create_run(run_id="fixed", timestamp=timestamp)
            marker = first.paths.directory / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")

            with self.assertRaises(RunDirectoryExistsError):
                store.create_run(run_id="fixed", timestamp=timestamp)

            self.assertEqual("preserve", marker.read_text(encoding="utf-8"))

    def test_task_trials_are_grouped_by_day_and_increment_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            store = RunDataStore(root)
            timestamp = datetime(2026, 10, 18, 15, 30, tzinfo=timezone.utc)

            first = store.create_task_trial(
                "OCP / EIS: catalyst A", timestamp=timestamp
            )
            marker = first.paths.directory / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            second = store.create_task_trial(
                "OCP / EIS: catalyst A", timestamp=timestamp
            )

            task_directory = (
                root / "runs" / "2026-10-18" / "OCP-EIS-catalyst A"
            )
            self.assertEqual(task_directory / "trial-001", first.paths.directory)
            self.assertEqual(task_directory / "trial-002", second.paths.directory)
            self.assertEqual("preserve", marker.read_text(encoding="utf-8"))

    def test_simulation_trials_are_separate_from_real_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            store = RunDataStore(root)
            timestamp = datetime(2026, 10, 18, 15, 30, tzinfo=timezone.utc)

            first = store.create_simulation_trial("EChem screening", timestamp=timestamp)
            second = store.create_simulation_trial("EChem screening", timestamp=timestamp)
            first.write_simulation_session_once({"execution_mode": "connection_free_simulation"})

            task_directory = root / "simulations" / "2026-10-18" / "EChem screening"
            self.assertEqual(task_directory / "trial-001", first.paths.directory)
            self.assertEqual(task_directory / "trial-002", second.paths.directory)
            self.assertTrue(first.paths.simulation_session.is_file())
            self.assertFalse(store.runs_root.exists())

    def test_task_trial_rejects_blank_reserved_and_excessive_names(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunDataStore(Path(directory) / "data")
            timestamp = datetime(2026, 10, 18, 15, 30, tzinfo=timezone.utc)

            for task_name in ("   ", "CON", "x" * 81):
                with self.subTest(task_name=task_name):
                    with self.assertRaises(ValueError):
                        store.create_task_trial(task_name, timestamp=timestamp)

    def test_task_name_cannot_escape_the_runs_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            store = RunDataStore(root)
            writer = store.create_task_trial(
                "../outside",
                timestamp=datetime(2026, 10, 18, 15, 30, tzinfo=timezone.utc),
            )

            self.assertEqual("outside", writer.paths.directory.parent.name)
            self.assertEqual(
                root / "runs" / "2026-10-18" / "outside" / "trial-001",
                writer.paths.directory,
            )
            self.assertFalse((root.parent / "outside").exists())

    def test_raw_processed_metadata_and_logs_remain_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunDataStore(Path(directory) / "data")
            writer = store.create_run(
                run_id="test",
                timestamp=datetime(2026, 10, 4, 15, 30, tzinfo=timezone.utc),
            )
            writer.write_protocol_once({"technique": "CA", "authorized": True})
            with self.assertRaises(FileExistsError):
                writer.write_protocol_once({"technique": "CV"})

            writer.append_raw_output(b"time_s,current_A\r\n")
            writer.append_raw_output(b"0.0,1.0e-6\r\n")
            writer.append_processed_output(b"time_s,charge_C\n0.0,0.0\n")
            writer.append_instrument_trace({"operation": "fake", "return_code": 0})
            writer.append_event({"state": "running"})
            metadata = {
                "started_at": "2026-10-04T15:30:00+00:00",
                "units": {"time": "s", "current": "A"},
                "technique": "CA",
                "parameters": {"potential_V": 0.1},
                "software_version": "test",
                "chi_identity": {"model": "CHI 760E", "serial": "test"},
                "state": "running",
            }
            writer.write_metadata(metadata)
            metadata.update(
                {
                    "state": "completed",
                    "completed_at": "2026-10-04T15:31:00+00:00",
                }
            )
            writer.write_metadata(metadata)

            self.assertEqual(
                b"time_s,current_A\r\n0.0,1.0e-6\r\n",
                writer.paths.echem_raw.read_bytes(),
            )
            self.assertNotEqual(
                writer.paths.echem_raw.read_bytes(),
                writer.paths.echem_processed.read_bytes(),
            )
            saved_metadata = json.loads(writer.paths.metadata.read_text("utf-8"))
            self.assertEqual("completed", saved_metadata["state"])
            self.assertEqual(1, len(writer.paths.instrument_trace.read_text("utf-8").splitlines()))
            self.assertEqual(1, len(writer.paths.events.read_text("utf-8").splitlines()))

    def test_discovery_records_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunDataStore(Path(directory) / "data")
            path = store.write_discovery_record(
                "identity.json", {"read_only": True, "model": "CHI 760E"}
            )
            with self.assertRaises(FileExistsError):
                store.write_discovery_record("identity.json", {"model": "other"})

            self.assertEqual(store.discovery_root, path.parent)
            self.assertFalse(store.runs_root.exists())


if __name__ == "__main__":
    unittest.main()
