"""MobilitySpace that also runs on Windows.

agentsociety2's MobilitySpace starts a native routing server that only exists
for Linux x86_64 and macOS arm64. This drop-in replacement keeps the class name
``MobilitySpace`` (custom modules registered from this workspace override the
built-in of the same name), so configs, agent skills and replay tables are
unchanged. The only difference is that, on Windows (or when
AS2_PYTHON_ROUTER=1), it starts ``custom/routing/py_router.py`` instead of the
native binary.

It also makes configs portable:
- a relative ``file_path`` is resolved against the workspace (paper_experiments/),
  e.g. ``maps/singapore_central/map.pb``;
- an empty ``home_dir`` becomes ``$AS2_RUN_DIR/mobility_workspace`` (run_study.py
  sets AS2_RUN_DIR to the run directory).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from subprocess import Popen
from typing import Any

from agentsociety2.contrib.env.mobility_space.environment import MobilitySpace as _StockMobilitySpace
from agentsociety2.contrib.env.mobility_space.utils import find_free_ports, wait_for_port
from agentsociety2.env import EnvBase
from agentsociety2.logger import get_logger

WORKSPACE = Path(os.environ.get("WORKSPACE_PATH") or Path(__file__).resolve().parents[2])
ROUTER_SCRIPT = Path(__file__).resolve().parents[1] / "routing" / "py_router.py"
_MARKER = "python-router: see custom/routing/py_router.py\n"


def _use_python_router() -> bool:
    return sys.platform == "win32" or os.environ.get("AS2_PYTHON_ROUTER") == "1"


class MobilitySpace(_StockMobilitySpace):
    """Urban mobility on a real road network (map .pb): people live in AOIs, move by walking or
    driving along routed paths, and search nearby POIs. Windows-capable build of MobilitySpace."""

    def __init__(
        self,
        file_path: str = "",
        home_dir: str = "",
        persons: list | None = None,
        poi_search_limit: int = 10,
    ):
        if not file_path:
            raise ValueError("MobilitySpace needs file_path (the map .pb file)")
        map_path = Path(os.path.expanduser(file_path))
        if not map_path.is_absolute():
            map_path = WORKSPACE / map_path
        if home_dir:
            home = Path(os.path.expanduser(home_dir))
        elif os.environ.get("AS2_RUN_DIR"):
            home = Path(os.environ["AS2_RUN_DIR"]) / "mobility_workspace"
        else:  # config check, no run directory
            home = Path(tempfile.gettempdir()) / "agentsociety_mobility_check"
        home.mkdir(parents=True, exist_ok=True)

        self._use_python_router = _use_python_router()
        marker = home / "routing"
        if self._use_python_router and not marker.exists():
            # download_binary() returns early when home_dir/routing exists, so nothing is downloaded.
            marker.write_text(_MARKER, encoding="utf-8")
        elif not self._use_python_router and marker.is_file() and marker.stat().st_size < 200:
            if marker.read_text(encoding="utf-8", errors="ignore") == _MARKER:
                marker.unlink()  # let the official binary be downloaded instead

        super().__init__(file_path=str(map_path), home_dir=str(home), persons=persons or [],
                         poi_search_limit=poi_search_limit)

    async def init(self, start_datetime: datetime) -> Any:
        if not self._use_python_router:
            return await super().init(start_datetime)
        await EnvBase.init(self, start_datetime)
        port = find_free_ports()[0]
        self._server_addr = f"localhost:{port}"
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self._routing_proc = Popen(
            [sys.executable, str(ROUTER_SCRIPT), "-listen", self._server_addr, "-map", self._file_path,
             "-log-level", "warn"],
            env=os.environ,
            creationflags=flags,
        )
        get_logger().info(f"start python routing at {self._server_addr}, PID={self._routing_proc.pid}")
        if not await asyncio.to_thread(wait_for_port, "localhost", port, 60.0):
            if self._routing_proc.poll() is None:
                self._routing_proc.kill()
            raise RuntimeError(f"Python routing server failed to start on port {port} within 60 seconds")
        get_logger().info(f"Python routing server is ready on {self._server_addr}")


# EnvMeta only registers @tool methods defined in a class's own body, so carry the parent's tools over.
for _attr in ("_registered_tools", "_readonly_tools", "_tool_kinds"):
    setattr(MobilitySpace, _attr, {**getattr(_StockMobilitySpace, _attr, {}), **getattr(MobilitySpace, _attr, {})})
