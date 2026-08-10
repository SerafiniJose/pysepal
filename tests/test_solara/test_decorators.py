"""Tests for the with_sepal_sessions decorator's runtime gating.

Only solara-server ever populates ``solara.lab.headers`` (its websocket app
loop copies the HTTP request headers). Under voila and plain Jupyter no request
context exists, so waiting for headers would block the page forever -- the
decorator must only wait where headers can actually arrive.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pysepal.solara import decorators


def test_page_renders_without_headers_outside_solara_server():
    """Under voila the page renders immediately; the session is built locally."""
    session_manager_cls = MagicMock()

    @decorators.with_sepal_sessions(module_name="my_module")
    def page():
        return "rendered"

    with (
        patch.object(decorators, "in_solara_server_context", return_value=False),
        patch.object(decorators, "headers", SimpleNamespace(value=None)),
        patch.object(decorators, "SessionManager", session_manager_cls),
    ):
        result = page()

    assert result == "rendered"
    session_manager_cls.return_value.create_session.assert_called_once_with(
        module_name="my_module"
    )


def test_page_waits_for_headers_under_solara_server():
    """Under solara-server headers WILL arrive: keep the waiting behavior."""
    session_manager_cls = MagicMock()
    rendered = []

    @decorators.with_sepal_sessions(module_name="my_module", show_loading=False)
    def page():
        rendered.append(True)
        return "rendered"

    with (
        patch.object(decorators, "in_solara_server_context", return_value=True),
        patch.object(decorators, "headers", SimpleNamespace(value=None)),
        patch.object(decorators, "SessionManager", session_manager_cls),
    ):
        result = page()

    assert result is None
    assert rendered == []
    session_manager_cls.return_value.create_session.assert_not_called()
