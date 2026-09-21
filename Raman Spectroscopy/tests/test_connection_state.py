import unittest

from raman import (
    ConnectionState,
    InstrumentIdentity,
    RamanController,
    RamanSafetyError,
)


class ConnectFailureBackend:
    is_simulated = False
    hardware_verified = True

    def __init__(self):
        self.disconnect_calls = 0

    def connect(self):
        raise RuntimeError("simulated partial connection failure")

    def disconnect(self):
        self.disconnect_calls += 1

    def acquire(self, plan):
        raise AssertionError("not reached")

    def abort(self):
        raise AssertionError("not reached")


class DisconnectFailureBackend:
    is_simulated = False
    hardware_verified = True

    def connect(self):
        return InstrumentIdentity(manufacturer="test backend")

    def disconnect(self):
        raise RuntimeError("simulated disconnect failure")

    def acquire(self, plan):
        raise AssertionError("not reached")

    def abort(self):
        raise AssertionError("not reached")


class RamanConnectionStateTests(unittest.TestCase):
    def test_connect_failure_attempts_cleanup(self):
        backend = ConnectFailureBackend()
        controller = RamanController(backend, live_connection_enabled=True)

        with self.assertRaisesRegex(RuntimeError, "partial connection"):
            controller.connect()

        self.assertEqual(1, backend.disconnect_calls)
        self.assertEqual(ConnectionState.DISCONNECTED, controller.connection_state)
        self.assertFalse(controller.connected)

    def test_disconnect_failure_marks_connection_state_unknown(self):
        controller = RamanController(
            DisconnectFailureBackend(), live_connection_enabled=True
        )
        controller.connect()

        with self.assertRaisesRegex(RuntimeError, "disconnect failure"):
            controller.disconnect()

        self.assertEqual(ConnectionState.UNKNOWN, controller.connection_state)
        self.assertFalse(controller.connected)
        with self.assertRaises(RamanSafetyError):
            controller.connect()


if __name__ == "__main__":
    unittest.main()
