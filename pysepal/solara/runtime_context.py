"""Runtime identity helpers for pysepal Solara app state.

Scopes ``SessionManager`` sessions and the ``NotificationProvider`` bus to the
current app runtime: Solara server, Voila (including preheated kernels), or
plain Jupyter Notebook/Lab.
"""

import solara.scope


class UnsupportedSolaraRuntimeError(RuntimeError):
    """Raised when pysepal cannot resolve a supported app runtime."""


def in_solara_server_context() -> bool:
    """True when the current thread runs inside a solara-server virtual kernel.

    Only solara-server ever populates ``solara.lab.headers`` (its websocket app
    loop copies the HTTP request headers at page connect). Voila and plain
    Jupyter execute app code in a real ipykernel with no request context, so
    headers can never arrive there and session material must come from
    in-container credentials instead. Thread-scoped by design: call it from the
    render path (as ``with_sepal_sessions``/``create_session`` do), not from
    worker threads.
    """
    import solara.server.kernel_context as kernel_context

    return kernel_context.has_current_context()


def get_current_runtime_id() -> str:
    """Return a stable id for the current app runtime.

    Thin adapter over Solara's own ``solara.scope.get_kernel_id`` resolver: it
    returns the Solara-server virtual-kernel id and otherwise falls back to the
    active IPython/ipykernel -- covering ``solara run``, Voila (including
    preheated kernels, which start before ``SERVER_SOFTWARE`` is set), and plain
    Jupyter Notebook/Lab. We deliberately do not reimplement that resolution;
    we only translate its failure modes -- no kernel at all, or an ipykernel
    whose connection filename it cannot parse -- into a typed error the
    notification/session registries already handle by disabling scoped state.
    """
    try:
        return solara.scope.get_kernel_id(ipython_fallback=True)
    except (RuntimeError, AttributeError) as exc:
        raise UnsupportedSolaraRuntimeError(
            "No supported pysepal runtime context is available"
        ) from exc
