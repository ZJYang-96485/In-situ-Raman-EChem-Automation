from __future__ import annotations

from http.client import HTTPResponse
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from chi760.web_bridge import (
    BridgeState,
    StorageSettings,
    UnavailableDiscoveryGateway,
    create_server,
)


class FakeReadyGateway:
    def __init__(self) -> None:
        self.calls = 0

    def public_status(self) -> dict[str, object]:
        return {
            "target": "CHI 760E",
            "state": "ready_for_identity",
            "discovery_enabled": True,
            "experiment_control_enabled": False,
            "hardware_calls": self.calls,
            "blocker": None,
        }

    def discover(self) -> dict[str, object]:
        self.calls += 1
        return {
            "identity": {
                "model": "CHI 760E",
                "serial_number": "TEST-ONLY",
                "firmware_version": "TEST-FW",
                "software_version": "TEST-SW",
            },
            "capabilities": {"identity_query": True},
        }


class WebBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.selected_folder = root / "chosen-data"
        self.selected_folder.mkdir()
        self.config_path = root / "settings" / "bridge.json"
        self.state = BridgeState(
            token="test-secret-token",
            storage=StorageSettings(self.config_path),
            gateway=UnavailableDiscoveryGateway("test adapter unavailable"),
            directory_picker=lambda _initial: self.selected_folder,
            discovery_approval=lambda: True,
        )
        self.server = create_server(self.state, port=0)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(
        self,
        route: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        token: str | None = "test-secret-token",
        origin: str | None = None,
    ) -> tuple[HTTPResponse, bytes]:
        data = None
        headers = {"Origin": origin or self.origin}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"http://127.0.0.1:{self.port}{route}",
            data=data,
            headers=headers,
            method=method,
        )
        response = urlopen(request, timeout=2)
        return response, response.read()

    def error_payload(self, error: HTTPError) -> dict[str, object]:
        try:
            return json.loads(error.read().decode("utf-8"))
        finally:
            error.close()

    def test_status_requires_ephemeral_bearer_token(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            self.request("/v1/status", token=None)

        self.assertEqual(401, caught.exception.code)
        self.assertEqual(
            "unauthorized",
            self.error_payload(caught.exception)["error"]["code"],  # type: ignore[index]
        )

    def test_status_is_fail_closed_and_has_no_machine_path(self) -> None:
        response, raw = self.request("/v1/status")
        payload = json.loads(raw.decode("utf-8"))

        self.assertEqual(200, response.status)
        self.assertEqual("loopback_only", payload["service"]["binding"])
        self.assertFalse(payload["instrument"]["discovery_enabled"])
        self.assertFalse(payload["instrument"]["experiment_control_enabled"])
        self.assertEqual(0, payload["instrument"]["hardware_calls"])
        self.assertTrue(payload["safety"]["local_confirmation_required"])
        self.assertNotIn(str(self.config_path.parent), raw.decode("utf-8"))

    def test_untrusted_web_origin_is_rejected(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            self.request("/v1/status", origin="https://attacker.invalid")

        self.assertEqual(403, caught.exception.code)
        self.assertEqual(
            "origin_not_allowed",
            self.error_payload(caught.exception)["error"]["code"],  # type: ignore[index]
        )

    def test_private_network_preflight_allows_only_the_trusted_origin(self) -> None:
        request = Request(
            f"http://127.0.0.1:{self.port}/v1/status",
            headers={
                "Origin": "https://spectraloop.org",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
                "Access-Control-Request-Private-Network": "true",
            },
            method="OPTIONS",
        )

        with urlopen(request, timeout=2) as response:
            self.assertEqual(204, response.status)
            self.assertEqual(
                "https://spectraloop.org",
                response.headers["Access-Control-Allow-Origin"],
            )
            self.assertEqual(
                "true", response.headers["Access-Control-Allow-Private-Network"]
            )

    def test_storage_picker_persists_locally_but_api_returns_only_folder_name(self) -> None:
        response, raw = self.request(
            "/v1/storage/select", method="POST", payload={}
        )
        payload = json.loads(raw.decode("utf-8"))

        self.assertEqual(200, response.status)
        self.assertEqual("chosen-data", payload["storage"]["folder_name"])
        self.assertTrue(payload["storage"]["available"])
        self.assertNotIn(str(self.selected_folder), raw.decode("utf-8"))
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(str(self.selected_folder.resolve()), saved["storage_root"])

        reloaded = StorageSettings(self.config_path)
        self.assertEqual(self.selected_folder.resolve(), reloaded.root)

    def test_discovery_requires_every_safety_confirmation(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/v1/instrument/discover",
                method="POST",
                payload={"confirmations": {"identity_only": True}},
            )

        self.assertEqual(400, caught.exception.code)
        self.assertEqual(
            "confirmations_required",
            self.error_payload(caught.exception)["error"]["code"],  # type: ignore[index]
        )

    def test_unavailable_adapter_cannot_make_a_hardware_call(self) -> None:
        confirmations = {
            "identity_only": True,
            "no_sample_connected": True,
            "electrode_leads_safe": True,
            "cell_output_off": True,
        }
        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/v1/instrument/discover",
                method="POST",
                payload={"confirmations": confirmations},
            )

        self.assertEqual(409, caught.exception.code)
        caught.exception.close()
        self.assertEqual(0, self.state.gateway.hardware_calls)  # type: ignore[attr-defined]

    def test_no_experiment_api_is_exposed(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/v1/instrument/run",
                method="POST",
                payload={"technique": "CV"},
            )

        self.assertEqual(404, caught.exception.code)
        caught.exception.close()
        self.assertEqual(0, self.state.gateway.hardware_calls)  # type: ignore[attr-defined]

    def test_ready_gateway_runs_only_after_confirmations(self) -> None:
        gateway = FakeReadyGateway()
        self.state.gateway = gateway
        confirmations = {
            "identity_only": True,
            "no_sample_connected": True,
            "electrode_leads_safe": True,
            "cell_output_off": True,
        }

        response, raw = self.request(
            "/v1/instrument/discover",
            method="POST",
            payload={"confirmations": confirmations},
        )
        payload = json.loads(raw.decode("utf-8"))

        self.assertEqual(200, response.status)
        self.assertEqual(1, gateway.calls)
        self.assertEqual("CHI 760E", payload["discovery"]["identity"]["model"])
        self.assertFalse(gateway.public_status()["experiment_control_enabled"])

    def test_local_approval_can_block_a_ready_gateway(self) -> None:
        gateway = FakeReadyGateway()
        self.state.gateway = gateway
        self.state.discovery_approval = lambda: False
        confirmations = {
            "identity_only": True,
            "no_sample_connected": True,
            "electrode_leads_safe": True,
            "cell_output_off": True,
        }

        with self.assertRaises(HTTPError) as caught:
            self.request(
                "/v1/instrument/discover",
                method="POST",
                payload={"confirmations": confirmations},
            )

        self.assertEqual(409, caught.exception.code)
        self.assertEqual(
            "local_approval_declined",
            self.error_payload(caught.exception)["error"]["code"],  # type: ignore[index]
        )
        self.assertEqual(0, gateway.calls)

    def test_server_refuses_non_loopback_binding(self) -> None:
        with self.assertRaises(ValueError):
            create_server(self.state, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
