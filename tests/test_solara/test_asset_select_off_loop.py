"""AssetSelectComponent must keep eeclient traffic on GEEInterface's private loop.

eeclient caches one ``httpx.AsyncClient`` per session; its pooled connection
binds to the first event loop that drives it. GEEInterface's blocking API runs
every coroutine on its own private loop, so any component that instead awaits
a ``*_async`` method on the kernel loop (or a ``use_task`` thread loop) makes
the next call from the other side fail with "Non-thread-safe operation
invoked on an event loop other than the current one" (spatial-risk Variables
modal, 2026-09-11). The selector therefore has to call the blocking
``get_folder`` / ``get_assets`` / ``get_asset`` / ``get_info`` from a worker
thread, like ``aoi.admin.process_admin`` does.
"""

import asyncio
import threading
import time

import solara

from pysepal.solara.components.inputs.asset_select import AssetSelectComponent

_OTHER_LOOP = "Non-thread-safe operation invoked on an event loop other than the current one"


class _FakeInterface:
    """Records which API each call used and whether a loop was running."""

    def __init__(self):
        self.async_calls = []
        self.blocking_calls = []
        self.blocking_saw_running_loop = False
        self.threads = []

    def _record(self, name):
        self.blocking_calls.append(name)
        self.threads.append(threading.current_thread())
        try:
            asyncio.get_running_loop()
            self.blocking_saw_running_loop = True
        except RuntimeError:
            pass

    def get_folder(self):
        self._record("get_folder")
        return "projects/p/assets/"

    def get_assets(self, folder=""):
        self._record("get_assets")
        return [{"id": "projects/p/assets/img", "type": "IMAGE"}]

    def get_asset(self, asset_id, not_exists_ok=False):
        self._record("get_asset")
        return {"id": asset_id, "type": "IMAGE"}

    def get_info(self, ee_object=None, *args, **kwargs):
        self._record("get_info")
        return {"properties": {}}

    async def get_folder_async(self):
        self.async_calls.append("get_folder_async")
        raise RuntimeError(_OTHER_LOOP)

    async def get_assets_async(self, folder=""):
        self.async_calls.append("get_assets_async")
        raise RuntimeError(_OTHER_LOOP)

    async def get_asset_async(self, asset_id, not_exists_ok=False):
        self.async_calls.append("get_asset_async")
        raise RuntimeError(_OTHER_LOOP)

    async def get_info_async(self, *args, **kwargs):
        self.async_calls.append("get_info_async")
        raise RuntimeError(_OTHER_LOOP)


async def _settle(pred, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline and not pred():
        await asyncio.sleep(0.05)


def test_asset_select_keeps_gee_traffic_off_caller_loop():
    """Listing and validating assets use the blocking API from a worker thread."""
    interface = _FakeInterface()
    values = []

    async def _scenario():
        loop_thread = threading.current_thread()
        box, rc = solara.render(
            AssetSelectComponent(
                types=["IMAGE"],
                gee_interface=interface,
                initial={"asset_id": "projects/p/assets/img"},
                on_value=values.append,
            ),
            handle_error=False,
        )
        try:
            await _settle(
                lambda: "get_assets" in interface.blocking_calls
                and "get_asset" in interface.blocking_calls
            )
        finally:
            rc.close()

        assert interface.async_calls == []
        assert {"get_folder", "get_assets", "get_asset"} <= set(interface.blocking_calls)
        assert interface.blocking_saw_running_loop is False
        assert all(t is not loop_thread for t in interface.threads)
        assert values and values[-1]["asset_id"] == "projects/p/assets/img"
        assert values[-1]["type"] == "IMAGE"

    asyncio.run(_scenario())
