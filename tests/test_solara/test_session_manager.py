"""Tests for Solara SessionManager runtime scoping."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pysepal.solara.session_manager import SessionManager


def test_session_manager_kernel_id_uses_shared_runtime_resolver():
    manager = SessionManager()

    with patch(
        "pysepal.solara.session_manager.get_current_runtime_id",
        return_value="voila:kernel-1",
    ):
        assert manager.get_kernel_id() == "voila:kernel-1"


def test_getters_fall_back_when_no_session_can_exist():
    """Voila and plain Jupyter have no SEPAL headers, so no session can exist.

    ``setup_sessions`` initialises the SessionManager on every kernel start,
    including under Voila, but ``create_session`` bails out when
    ``headers.value`` is None. Treating "initialised but sessionless" as a
    missing ``@with_sepal_sessions`` therefore broke every non-Solara runtime:
    the headerless fallbacks were unreachable.
    """
    from pysepal.solara import theme, utils

    # Two patch targets on purpose: utils binds the predicate at import time,
    # while theme must import it lazily (session_manager imports ThemeState from
    # theme, so a module-level import there would be circular).
    with (
        patch.object(SessionManager, "is_initialized", return_value=True),
        patch.object(SessionManager, "get_session_component", return_value=None),
        patch.object(utils, "can_create_sessions", return_value=False),
        patch("pysepal.solara.session_manager.can_create_sessions", return_value=False),
        patch.object(utils, "_get_fallback_gee_interface", return_value="fallback-gee"),
        patch.object(utils, "_get_fallback_drive_interface", return_value="fallback-drive"),
        patch.object(theme, "_get_fallback_theme_state", return_value="fallback-theme"),
    ):
        assert utils.get_current_gee_interface() == "fallback-gee"
        assert utils.get_current_drive_interface() == "fallback-drive"
        assert theme.get_current_theme_state() == "fallback-theme"


def test_getters_still_raise_when_headers_exist_but_session_is_missing():
    """With headers present we ARE in a solara request, so a missing session is a bug.

    That is the case the error message is for -- a Page without
    ``@with_sepal_sessions`` -- and it must keep raising.
    """
    import pytest

    from pysepal.solara import theme, utils

    with (
        patch.object(SessionManager, "is_initialized", return_value=True),
        patch.object(SessionManager, "get_session_component", return_value=None),
        patch.object(utils, "can_create_sessions", return_value=True),
        patch("pysepal.solara.session_manager.can_create_sessions", return_value=True),
    ):
        for getter in (
            utils.get_current_gee_interface,
            utils.get_current_drive_interface,
            theme.get_current_theme_state,
        ):
            with pytest.raises(RuntimeError, match="Session manager is active"):
                getter()


# ---------------------------------------------------------------------------
# create_session runtime awareness (voila / plain Jupyter local sessions)
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_session_manager():
    """Isolate the SessionManager singleton so create_session tests start empty."""
    old_instance = SessionManager._instance
    old_sessions = SessionManager._sessions
    SessionManager._instance = None
    SessionManager._sessions = {}
    yield
    SessionManager._instance = old_instance
    SessionManager._sessions = old_sessions


def _local_runtime_patches(sm, **overrides):
    """Patches simulating a voila/Jupyter runtime with SEPAL sandbox credentials."""
    ee_cls = overrides.pop("ee_cls", MagicMock())
    sepal_cls = overrides.pop("sepal_cls", MagicMock())
    patches = [
        patch.object(sm, "get_current_runtime_id", return_value="voila:kernel-1"),
        patch.object(sm, "in_solara_server_context", return_value=False),
        patch.object(sm, "EESession", ee_cls),
        patch.object(sm, "GEEInterface", lambda session: {"ee_session": session}),
        patch.object(sm, "SepalClient", sepal_cls),
        patch.object(sm, "GDriveInterface", lambda: "drive"),
        patch.object(sm, "ThemeState", lambda: "theme"),
        patch.object(sm, "LocaleState", lambda: "locale"),
        patch("getpass.getuser", return_value="sepal-user"),
        patch("atexit.register"),
    ]
    return patches, ee_cls, sepal_cls


def test_create_session_outside_solara_server_uses_local_credentials(
    clean_session_manager, monkeypatch
):
    """Voila/Jupyter never see request headers: the session comes from the sandbox.

    GEE resolves via ``EESession.from_default()`` (the SEPAL-provisioned
    credentials file) and SepalClient via ``detect_auth()`` (the sandbox api
    key), so no ``session_id`` is passed.
    """
    from pysepal.solara import session_manager as sm

    monkeypatch.delenv("SOLARA_TEST", raising=False)
    manager = SessionManager()
    patches, ee_cls, sepal_cls = _local_runtime_patches(sm)
    sepal_cls.create.return_value = "sepal-client"

    with patch.object(sm, "headers", SimpleNamespace(value=None)):
        for p in patches:
            p.start()
        try:
            manager.create_session(module_name="spatial_risk")
        finally:
            for p in patches:
                p.stop()

    session = manager._sessions["voila:kernel-1"]
    ee_cls.from_default.assert_called_once_with()
    sepal_cls.create.assert_called_once_with(module_name="spatial_risk")
    assert session["gee_interface"] == {"ee_session": ee_cls.from_default.return_value}
    assert session["sepal_client"] == "sepal-client"
    assert session["drive_interface"] == "drive"
    assert session["username"] == "sepal-user"
    assert session["theme_state"] == "theme"
    assert session["locale_state"] == "locale"


def test_local_session_degrades_without_sepal_api_credentials(
    clean_session_manager, monkeypatch
):
    """No sandbox api key (e.g. dev voila) must not kill the page: client is None."""
    from pysepal_api.errors import NoCredentialsError

    from pysepal.solara import session_manager as sm

    monkeypatch.delenv("SOLARA_TEST", raising=False)
    manager = SessionManager()
    patches, _, sepal_cls = _local_runtime_patches(sm)
    sepal_cls.create.side_effect = NoCredentialsError("no api key")

    for p in patches:
        p.start()
    try:
        manager.create_session(module_name="spatial_risk")
    finally:
        for p in patches:
            p.stop()

    session = manager._sessions["voila:kernel-1"]
    assert session["sepal_client"] is None
    assert session["gee_interface"] is not None


def test_local_session_registers_atexit_cleanup(clean_session_manager, monkeypatch):
    """on_kernel_start never fires outside solara-server, so cleanup hooks atexit."""
    from pysepal.solara import session_manager as sm

    monkeypatch.delenv("SOLARA_TEST", raising=False)
    manager = SessionManager()
    patches, _, sepal_cls = _local_runtime_patches(sm)
    sepal_cls.create.return_value = "sepal-client"

    mocks = [p.start() for p in patches]
    register_mock = mocks[-1]  # the atexit.register patch
    try:
        manager.create_session(module_name="spatial_risk")
    finally:
        for p in patches:
            p.stop()

    register_mock.assert_called_once_with(manager.cleanup_session, "voila:kernel-1")


def test_create_session_still_waits_for_headers_under_solara_server(
    clean_session_manager, monkeypatch
):
    """Under solara-server the headers WILL arrive: keep waiting, build nothing."""
    from pysepal.solara import session_manager as sm

    monkeypatch.delenv("SOLARA_TEST", raising=False)
    manager = SessionManager()

    with (
        patch.object(sm, "get_current_runtime_id", return_value="solara:kernel-1"),
        patch.object(sm, "in_solara_server_context", return_value=True),
        patch.object(sm, "headers", SimpleNamespace(value=None)),
    ):
        manager.create_session(module_name="spatial_risk")

    assert manager._sessions == {}


def test_solara_test_builds_header_session_without_waiting_for_headers(
    clean_session_manager, monkeypatch
):
    """SOLARA_TEST dev override authenticates locally; no header seeding needed."""
    from pysepal.solara import session_manager as sm

    monkeypatch.setenv("SOLARA_TEST", "true")
    manager = SessionManager()

    fake_headers = MagicMock()
    fake_headers.sepal_user.username = "test-user"
    fake_headers.cookies = {"SEPAL-SESSIONID": "sid-1"}
    ee_cls = MagicMock()
    sepal_cls = MagicMock()
    sepal_cls.create.return_value = "sepal-client"

    with (
        patch.object(sm, "get_current_runtime_id", return_value="voila:kernel-1"),
        patch.object(sm, "headers", SimpleNamespace(value=None)),
        patch.object(sm, "get_sepal_headers_from_auth", return_value=fake_headers),
        patch.object(sm, "EESession", ee_cls),
        patch.object(sm, "GEEInterface", lambda session: {"ee_session": session}),
        patch.object(sm, "SepalClient", sepal_cls),
        patch.object(sm, "GDriveInterface", lambda sepal_headers: {"drive": sepal_headers}),
        patch.object(sm, "ThemeState", lambda: "theme"),
        patch.object(sm, "LocaleState", lambda: "locale"),
        patch("atexit.register"),
    ):
        manager.create_session(module_name="spatial_risk")

    session = manager._sessions["voila:kernel-1"]
    assert session["username"] == "test-user"
    ee_cls.from_sepal_headers.assert_called_once_with(fake_headers)
    sepal_cls.create.assert_called_once_with(session_id="sid-1", module_name="spatial_risk")
