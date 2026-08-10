"""Session Manager for gee, drive and sepal interfaces for Solara applications.

This module provides centralized session management for gee, gdrive and sepal interfaces,
handling initialization, cleanup, and session tracking across different
Solara applications.
"""

import atexit
import getpass
import logging
import os
from typing import Any, Callable, Dict, Optional

from eeclient.client import EESession
from eeclient.helpers import get_sepal_headers_from_auth
from eeclient.models import SepalHeaders
from solara.lab import headers

from pysepal.scripts.drive_interface import GDriveInterface
from pysepal.scripts.gee_interface import GEEInterface
from pysepal.scripts.sepal_client import SepalClient
from pysepal.solara.locale import LocaleState
from pysepal.solara.runtime_context import (
    get_current_runtime_id,
    in_solara_server_context,
)
from pysepal.solara.theme import ThemeState

logger = logging.getLogger("sepalui.session_manager")


class SessionManager:
    """A singleton session manager for solara-sepal applications.

    This class manages the lifecycle of sessions across different Solara applications,
    providing a centralized way to handle session creation, retrieval, and cleanup for
    GEE interfaces, SepalClient and GDriveInterface.

    Note: Do not instantiate this class directly. Use the @with_sepal_sessions
    decorator or the utility functions in sepal_ui.solara.utils instead.
    """

    _instance = None
    """Singleton instance of the SessionManager."""
    _sessions: Dict[str, Dict[str, Any]] = {}
    """Dictionary to hold sessions keyed by kernel ID."""

    def __new__(cls):
        """Create or return the singleton instance of SessionManager."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the SessionManager singleton instance."""
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._sessions = {}

    @classmethod
    def is_initialized(cls) -> bool:
        """Check if the SessionManager has been initialized."""
        return cls._instance is not None and hasattr(cls._instance, "_initialized")

    def get_kernel_id(self) -> str:
        """Get the current supported Solara/Voila runtime ID."""
        return get_current_runtime_id()

    def create_session(self, module_name: str = "default") -> None:
        """Create a new session with all the interfaces for the current kernel ID.

        Three sources, in precedence order:

        1. ``SOLARA_TEST=true`` -- dev override: authenticate against SEPAL with
           ``LOCAL_SEPAL_USER``/``LOCAL_SEPAL_PASSWORD`` regardless of runtime.
        2. Solara-server -- the forwarded request headers (``solara.lab.headers``);
           bail out and wait while they have not arrived yet.
        3. Voila / plain Jupyter -- no HTTP layer ever reaches the kernel, so the
           session is built from what SEPAL provisions inside the sandbox itself
           (see ``_build_local_session``).

        Args:
            module_name: The module name for the SepalClient.

        Raises:
            EEClientError: For authentication-related errors.
            Exception: For other validation or connection errors.
        """
        kernel_id = self.get_kernel_id()

        # Skip if a session already exists for this kernel (idempotent)
        if kernel_id in self._sessions:
            logger.debug(f"Session already exists for kernel {kernel_id}, skipping creation")
            return

        in_server = in_solara_server_context()

        if os.getenv("SOLARA_TEST", "false").lower() == "true":
            logger.debug(f"Creating SOLARA_TEST session for kernel {kernel_id}")
            session = self._build_header_session(get_sepal_headers_from_auth(), module_name)
        elif in_server:
            current_headers = headers.value
            if current_headers is None:
                logger.warning(f"Headers not available yet for kernel {kernel_id}")
                return
            logger.debug(f"Creating session for kernel {kernel_id}")
            session = self._build_header_session(
                SepalHeaders.model_validate(current_headers), module_name
            )
        else:
            logger.debug(f"Creating local-credential session for kernel {kernel_id}")
            session = self._build_local_session(module_name)

        self._sessions[kernel_id] = session
        if not in_server:
            # on_kernel_start (and therefore setup_sessions' cleanup) only runs
            # under solara-server; close the interfaces at interpreter exit.
            atexit.register(self.cleanup_session, kernel_id)
        logger.debug(
            f"Sessions created for kernel {kernel_id} and gee_interface "
            f"{id(session['gee_interface'])}"
        )

    def _build_header_session(
        self, sepal_headers: SepalHeaders, module_name: str
    ) -> Dict[str, Any]:
        """Build a session from SEPAL request headers (solara-server / SOLARA_TEST)."""
        sepal_session_id = sepal_headers.cookies["SEPAL-SESSIONID"]
        gee_session = EESession.from_sepal_headers(sepal_headers)

        return {
            "username": sepal_headers.sepal_user.username,
            "gee_interface": GEEInterface(gee_session),
            "sepal_client": SepalClient.create(
                session_id=sepal_session_id, module_name=module_name
            ),
            "drive_interface": GDriveInterface(sepal_headers=sepal_headers),
            "theme_state": ThemeState(),
            "locale_state": LocaleState(),
        }

    def _build_local_session(self, module_name: str) -> Dict[str, Any]:
        """Build a session from in-container credentials (voila / plain Jupyter).

        GEE and Drive resolve through ``eeclient``'s default provider (the
        SEPAL-provisioned ``~/.config/earthengine/credentials`` in a SEPAL
        sandbox). SepalClient resolves through ``pysepal_api.detect_auth()``
        (the sandbox api key at ``/var/run/sepal-api-key``); where no api-key
        source exists -- e.g. a dev machine -- it degrades to ``None`` instead
        of failing the page, matching what header-less runtimes had before.
        """
        gee_interface = GEEInterface(EESession.from_default())

        try:
            sepal_client = SepalClient.create(module_name=module_name)
        except Exception as e:
            logger.warning(f"SepalClient unavailable for local session: {e}")
            sepal_client = None

        return {
            "username": getpass.getuser(),
            "gee_interface": gee_interface,
            "sepal_client": sepal_client,
            "drive_interface": GDriveInterface(),
            "theme_state": ThemeState(),
            "locale_state": LocaleState(),
        }

    def cleanup_session(self, kernel_id: str) -> None:
        """Clean up a session for the given kernel ID.

        Args:
            kernel_id: The kernel ID to clean up.
        """
        logger.debug(f"Cleaning up session for kernel {kernel_id}")

        if kernel_id in self._sessions:
            session = self._sessions[kernel_id]
            try:
                session["gee_interface"].close()
            except Exception as e:
                logger.error(f"Error closing GEE interface for kernel {kernel_id}: {e}")

            sepal_client = session.get("sepal_client")
            if sepal_client is not None:
                try:
                    sepal_client.close()
                except Exception as e:
                    logger.error(f"Error closing SepalClient for kernel {kernel_id}: {e}")

            del self._sessions[kernel_id]
            logger.debug(f"Session cleaned up for kernel {kernel_id}")

    def get_session_component(
        self, component_name: str, kernel_id: Optional[str] = None
    ) -> Optional[Any]:
        """Get a specific component from a session.

        Args:
            component_name: The name/key of the component to retrieve.
            kernel_id: The kernel ID to get component from. If None, uses current kernel.

        Returns:
            The component instance or None if not found.
        """
        if kernel_id is None:
            kernel_id = self.get_kernel_id()

        if kernel_id not in self._sessions:
            return None

        session = self._sessions[kernel_id]
        username = session.get("username", "unknown")

        # debug log for session retrieval
        logger.debug(
            f"Retrieving component '{component_name}' for kernel {kernel_id}, user {username}"
        )

        return session.get(component_name)

    def get_session_info(self, kernel_id: Optional[str] = None) -> dict:
        """Get session information for a specific kernel.

        Args:
            kernel_id: The kernel ID to get info for. If None, uses current kernel.

        Returns:
            Dictionary with session information.
        """
        if kernel_id is None:
            kernel_id = self.get_kernel_id()

        current_session = self._sessions.get(kernel_id)

        if current_session is None:
            return {
                "kernel_id": kernel_id,
                "username": None,
                "has_gee_interface": False,
                "has_sepal_client": False,
                "has_drive_interface": False,
                "has_theme_state": False,
                "has_locale_state": False,
                "session_ready": False,
            }

        return {
            "kernel_id": kernel_id,
            "username": current_session.get("username"),
            "has_gee_interface": current_session.get("gee_interface") is not None,
            "has_sepal_client": current_session.get("sepal_client") is not None,
            "has_drive_interface": current_session.get("drive_interface") is not None,
            "has_theme_state": current_session.get("theme_state") is not None,
            "has_locale_state": current_session.get("locale_state") is not None,
            "session_ready": current_session.get("gee_interface") is not None,
        }

    def list_sessions(self) -> Dict[str, Dict[str, Any]]:
        """Get all active sessions."""
        return self._sessions.copy()


def can_create_sessions() -> bool:
    """Whether a *header-based* SEPAL session can exist for the current runtime.

    Voila, plain Jupyter and plain scripts never see solara's request headers,
    so an initialized-but-sessionless manager there is expected rather than a
    forgotten ``@with_sepal_sessions`` -- the getters degrade to their
    headerless fallback instead of raising. (A *decorated* page in those
    runtimes gets a real local-credential session via ``create_session``, so
    its getters never reach this check.)
    """
    return headers.value is not None


def setup_sessions() -> Callable:
    """Set up sessions management for Solara applications.

    This function should be called with the @solara.lab.on_kernel_start decorator
    to automatically manage GEE, Drive, and Sepal sessions for your application.

    Returns:
        Cleanup function to be called when kernel shuts down.
    """
    session_manager = SessionManager()
    kernel_id = session_manager.get_kernel_id()

    logger.debug(f"Setting up sepal sessions for kernel {kernel_id}")

    # Return cleanup function
    def cleanup():
        session_manager.cleanup_session(kernel_id)

    return cleanup
