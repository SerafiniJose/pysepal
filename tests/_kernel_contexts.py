"""A real Solara kernel context, without running a Solara server.

State that solara isolates per virtual kernel -- the locale reactive, the
theme store -- can only be tested against real contexts: a fake scope id
proves nothing about storage solara keys by its own kernel context.
"""

import pytest


@pytest.fixture
def kernel_contexts(monkeypatch, tmp_path):
    """Return a factory creating Solara kernel contexts, closed at teardown."""
    import asyncio
    import sys
    from uuid import uuid4

    monkeypatch.setenv("IPYTHONDIR", str(tmp_path / "ipython"))
    from ipywidgets import Widget
    from solara.server.kernel import Kernel
    from solara.server.kernel_context import VirtualKernelContext, get_current_context

    monkeypatch.setattr(sys, "argv", ["solara"])

    # Without a Solara server nothing scopes ipywidgets' registry per kernel, so
    # the Widget.close_all() in a context's close() would also close widgets
    # whose comm belongs to another kernel: unregistering those raises KeyError,
    # which solara >= 1.64 no longer swallows. close() runs inside its context,
    # so close only the widgets of that kernel.
    def close_own_widgets():
        own = get_current_context().kernel.comm_manager.comms
        for widget in list(Widget.widgets.values()):
            if widget.comm is not None and widget.comm.comm_id in own:
                widget.close()

    monkeypatch.setattr(Widget, "close_all", staticmethod(close_own_widgets))
    contexts = []
    event_loop = asyncio.new_event_loop()

    def create():
        context = VirtualKernelContext(
            id=uuid4().hex, session_id="test", kernel=Kernel(), event_loop=event_loop
        )
        contexts.append(context)
        return context

    yield create
    for context in reversed(contexts):
        context.close()
    event_loop.close()
