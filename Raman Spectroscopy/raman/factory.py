"""Select a Raman backend without opening a hardware connection."""

from .andor_solis_backend import AndorSolisBackend
from .backend import RamanBackend
from .configuration import RamanConfiguration
from .controller import RamanController
from .mock_backend import MockRamanBackend


def create_raman_backend(configuration: RamanConfiguration) -> RamanBackend:
    """Construct the requested backend.

    Construction is safe: the mock backend never has hardware I/O, and the
    Andor/Solis backend is an explicit no-connect scaffold. Calling
    ``RamanController.connect()`` on the latter still raises until a verified
    live implementation replaces it.
    """

    if configuration.backend == "mock":
        return MockRamanBackend()
    if configuration.backend == "andor_solis":
        return AndorSolisBackend(
            configuration.hardware,
            connection_enabled=configuration.connection_enabled,
        )
    raise ValueError(f"unsupported Raman backend: {configuration.backend}")


def create_raman_controller(configuration: RamanConfiguration) -> RamanController:
    """Build a controller with the configuration's live-connection safeguard."""

    return RamanController(
        create_raman_backend(configuration),
        live_connection_enabled=configuration.connection_enabled,
    )
