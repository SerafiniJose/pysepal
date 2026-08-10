"""Tests for pysepal Solara runtime identity resolution.

``get_current_runtime_id`` is a thin adapter over ``solara.scope.get_kernel_id``
(Solara's own Solara-server-or-IPython resolver), so these tests cover the
adapter contract: pass-through of the resolved id and translation of Solara's
failure modes into ``UnsupportedSolaraRuntimeError``.
"""

from unittest.mock import patch

import pytest

from pysepal.solara.runtime_context import (
    UnsupportedSolaraRuntimeError,
    get_current_runtime_id,
)


def test_current_runtime_id_delegates_to_solara_scope():
    with patch("solara.scope.get_kernel_id", return_value="kernel-uuid") as get_kernel_id:
        assert get_current_runtime_id() == "kernel-uuid"
        get_kernel_id.assert_called_once_with(ipython_fallback=True)


def test_current_runtime_id_raises_typed_error_when_no_runtime():
    with patch("solara.scope.get_kernel_id", side_effect=RuntimeError("Not in a kernel")):
        with pytest.raises(UnsupportedSolaraRuntimeError, match="No supported"):
            get_current_runtime_id()


def test_current_runtime_id_raises_typed_error_on_unparseable_connection_file():
    # solara.scope.get_kernel_id() regex-parses the ipykernel connection filename
    # and raises AttributeError when it does not match (e.g. non-standard kernel
    # launchers); degrade cleanly to "unsupported" instead of crashing render.
    err = AttributeError("'NoneType' object has no attribute 'group'")
    with patch("solara.scope.get_kernel_id", side_effect=err):
        with pytest.raises(UnsupportedSolaraRuntimeError, match="No supported"):
            get_current_runtime_id()


def test_in_solara_server_context_is_false_outside_the_server():
    """A pytest process is exactly the no-request-context case (like voila/Jupyter)."""
    from pysepal.solara.runtime_context import in_solara_server_context

    assert in_solara_server_context() is False


def test_in_solara_server_context_delegates_to_solara_kernel_context():
    from pysepal.solara.runtime_context import in_solara_server_context

    with patch("solara.server.kernel_context.has_current_context", return_value=True):
        assert in_solara_server_context() is True
