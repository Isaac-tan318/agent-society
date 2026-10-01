"""Map store for AgentSociety Studio.

Maps live in paper_experiments/maps/<id>/ (git-ignored):
    map.pb        the city map (mosstool / MOSS protobuf format)
    meta.json     name, source, status, bbox, counts
    places.json   homes / workplaces agents can be placed at (reachable by road and on foot)
    preview.json  simplified roads + building footprints for the map view
    build.log     output of a Docker build

A map gets here by importing a .pb file (e.g. the Singapore map from the
user's AgentSociety 1 project) or by building one from OpenStreetMap with the
AgentSociety 1 map-builder Docker image. Either way ``prepare`` then runs in a
subprocess:

    python ui/maps.py prepare <map_dir>
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

UI_DIR = Path(__file__).resolve().parent
PROJECT = UI_DIR.parent
WORKSPACE = PROJECT / "paper_experiments"
MAPS = WORKSPACE / "maps"
ROUTER = WORKSPACE / "custom" / "routing" / "py_router.py"
BUILDER_DIR = UI_DIR / "mapbuilder"
BUILDER_IMAGE = "agentsociety-singapore-mapbuilder:latest"
PY = sys.executable
IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
MAX_UPLOAD = 2 * 1024 ** 3
MAX_AREA_KM2 = 2500
PREVIEW_MAX_AOIS = 40000

PRESETS = {
    "singapore_central": {"name": "Singapore - central",
                          "note": "CBD, Marina Bay, Orchard, Chinatown, Kallang. Builds in minutes.",
                          "bbox": [1.24, 103.79, 1.33, 103.89]},
    "singapore_island": {"name": "Singapore - whole island",
                         "note": "Whole main island. Expect tens of minutes and several GB of RAM.",
                         "bbox": [1.20, 103.60, 1.48, 104.09]},
}

# Land-use groups for the preview (fixed order = legend order = palette slot order; "Other" is neutral grey).
# Codes are the Chinese urban land-use classes mosstool assigns (R residential, B commercial, M industrial,
# W logistics, A public/institutional, G green, S transport, U utilities, E other/non-urban).
LAND_USE_GROUPS = ["Residential", "Business & industry", "Public & institutions", "Other"]
WORK_GROUPS = (1, 2)


def land_use_group(code: str) -> int:
    c = (code or "").upper()
    if c.startswith("R"):
        return 0
    if c.startswith(("B", "M", "W")):
        return 1
    if c.startswith("A"):
        return 2
    return 3


_JOBS: dict[str, subprocess.Popen] = {}  # map id -> running docker build / prepare process
_LOCK = threading.RLock()  # serializes job start/finish bookkeeping between request threads and build watchers


# --------------------------------------------------------------------------- helpers
def _json(p: Path, default: Any = None) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(p: Path, data: Any) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (s or "map")[:40]


def map_dir(map_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9_]{1,60}", map_id or ""):
        raise ValueError("bad map id")
    d = (MAPS / map_id).resolve()
    if d.parent != MAPS.resolve():
        raise ValueError("bad map id")
    return d


def _new_id(name: str) -> str:
    base, n = _slug(name), 1
    while (MAPS / (base if n == 1 else f"{base}_{n}")).exists():
        n += 1
    return base if n == 1 else f"{base}_{n}"


def _set_meta(d: Path, **updates: Any) -> dict:
    meta = _json(d / "meta.json", {}) or {}
    meta.update(updates)
    _write_json(d / "meta.json", meta)
    return meta


def _pid_alive(pid: Any) -> bool:
    if not pid:
        return False
    if IS_WINDOWS:
        import ctypes

        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        import os

        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _job_running(mid: str, meta: dict) -> bool:
    job = _JOBS.get(mid)
    return job.poll() is None if job else _pid_alive(meta.get("pid"))


# --------------------------------------------------------------------------- listing
def list_maps() -> list[dict]:
    out = []
    for f in sorted(MAPS.glob("*/meta.json")):
        mid = f.parent.name
        with _LOCK:
            meta = _json(f, {}) or {}
            if meta.get("status") in ("building", "preparing") and not _job_running(mid, meta):
                if meta["status"] == "building" and mid not in _JOBS and (f.parent / "map.pb").is_file():
                    _start_prepare(mid)  # the build finished while the Studio was closed
                elif meta["status"] == "preparing" or mid not in _JOBS:
                    # (a finished build tracked in _JOBS is picked up by _after_build)
                    _set_meta(f.parent, status="failed",
                              error=meta.get("error") or "Interrupted. Delete this map and try again.")
                meta = _json(f, {}) or {}
        log = f.parent / "build.log"
        out.append({**meta, "id": mid, "log_tail": _tail(log) if meta.get("status") in ("building", "failed") else ""})
    return out


def get_map(map_id: str) -> dict:
    d = map_dir(map_id)
    meta = _json(d / "meta.json")
    if not meta:
        raise KeyError(map_id)
    return {**meta, "id": map_id}


def _tail(p: Path, max_bytes: int = 6000) -> str:
    if not p.is_file():
        return ""
    with open(p, "rb") as f:
        f.seek(max(0, p.stat().st_size - max_bytes))
        text = f.read().decode("utf-8", errors="replace")
    # tqdm redraws lines with \r; keep the last state of each line
    return "\n".join(line.split("\r")[-1] for line in text.splitlines())[-4000:]


def suggestions() -> list[dict]:
    """.pb maps found in sibling projects (e.g. ../agentsociety1/data/) that aren't imported yet."""
    imported = {(_json(f, {}) or {}).get("source_path") for f in MAPS.glob("*/meta.json")}
    found = []
    for pb in sorted(PROJECT.parent.glob("*/data/*.pb")):
        if PROJECT in pb.parents or str(pb) in imported:
            continue
        found.append({"path": str(pb), "file": pb.name, "project": pb.parent.parent.name,
                      "size_mb": round(pb.stat().st_size / 1e6, 1),
                      "name": pb.stem.replace("_map", "").replace("_", " ").title()})
    return found


_DOCKER_CACHE: dict[str, Any] = {"t": 0.0, "v": None}


def docker_status() -> dict:
    if time.time() - _DOCKER_CACHE["t"] < 20 and _DOCKER_CACHE["v"]:
        return _DOCKER_CACHE["v"]
    st = {"docker": shutil.which("docker") is not None, "daemon": False, "image": False, "message": ""}
    if not st["docker"]:
        st["message"] = "Docker is not installed, so new areas can't be built (importing still works)."
    else:
        try:
            v = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True,
                               text=True, timeout=15, creationflags=NO_WINDOW)
            st["daemon"] = v.returncode == 0 and bool(v.stdout.strip())
            if st["daemon"]:
                i = subprocess.run(["docker", "image", "inspect", BUILDER_IMAGE], capture_output=True, text=True,
                                   timeout=15, creationflags=NO_WINDOW)
                st["image"] = i.returncode == 0
                if not st["image"]:
                    st["message"] = (f"The map-builder image {BUILDER_IMAGE} isn't on this PC. It comes from your "
                                     "AgentSociety 1 project (docker compose build).")
            else:
                st["message"] = "Docker Desktop isn't running. Start it from the Start menu, then refresh."
        except Exception as exc:
            st["message"] = f"Couldn't reach Docker: {exc}"
    _DOCKER_CACHE.update(t=time.time(), v=st)
    return st


# --------------------------------------------------------------------------- import / build
def _start_prepare(mid: str) -> None:
    d = map_dir(mid)
    with _LOCK:
        _set_meta(d, status="preparing", error=None, progress="Reading the map", pid=None)
        with open(d / "prepare.log", "w", encoding="utf-8") as log:
            proc = subprocess.Popen([PY, str(Path(__file__).resolve()), "prepare", str(d)], cwd=str(PROJECT),
                                    stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        _JOBS[mid] = proc
        _set_meta(d, pid=proc.pid)


def _new_map(name: str, **meta: Any) -> tuple[str, Path]:
    MAPS.mkdir(parents=True, exist_ok=True)
    mid = _new_id(name)
    d = MAPS / mid
    d.mkdir(parents=True)
    _write_json(d / "meta.json", {"name": name.strip() or mid, "created": datetime.now().isoformat(timespec="seconds"),
                                  **meta})
    return mid, d


def import_path(path: str, name: str) -> dict:
    src = Path(path)
    if src.suffix.lower() != ".pb" or not src.is_file():
        raise ValueError("Choose an existing .pb map file.")
    mid, d = _new_map(name or src.stem, source="import", source_path=str(src), status="copying")
    # Copy only the .pb: an AgentSociety 1 "<map>.pb.cache" next to it is a different format.
    shutil.copyfile(src, d / "map.pb")
    _start_prepare(mid)
    return get_map(mid)


def begin_upload(name: str, filename: str) -> tuple[str, Path]:
    """Create the map folder for a browser upload; the caller streams the body into the returned path."""
    if not filename.lower().endswith(".pb"):
        raise ValueError("Choose a .pb map file.")
    mid, d = _new_map(name or Path(filename).stem, source="upload", source_path=Path(filename).name,
                      status="copying")
    return mid, d / "map.pb"


def finish_upload(mid: str) -> dict:
    _start_prepare(mid)
    return get_map(mid)


def abort_upload(mid: str) -> None:
    shutil.rmtree(map_dir(mid), ignore_errors=True)


def bbox_area_km2(bbox: list[float]) -> float:
    min_lat, min_lon, max_lat, max_lon = bbox
    km_lat = 111.32
    km_lon = 111.32 * math.cos(math.radians((min_lat + max_lat) / 2))
    return abs(max_lat - min_lat) * km_lat * abs(max_lon - min_lon) * km_lon


def build(name: str, bbox: list[float], preset: str | None = None) -> dict:
    min_lat, min_lon, max_lat, max_lon = (float(v) for v in bbox)
    if not (-85 <= min_lat < max_lat <= 85 and -180 <= min_lon < max_lon <= 180):
        raise ValueError("The area must have south < north and west < east.")
    area = bbox_area_km2([min_lat, min_lon, max_lat, max_lon])
    if area > MAX_AREA_KM2:
        raise ValueError(f"That area is {area:,.0f} km2; the limit is {MAX_AREA_KM2:,} km2.")
    st = docker_status()
    if not (st["daemon"] and st["image"]):
        raise RuntimeError(st["message"] or "Docker isn't ready.")
    with _LOCK:
        if any(p.poll() is None for k, p in _JOBS.items() if (_json(MAPS / k / "meta.json", {}) or {}).get("status") == "building"):
            raise RuntimeError("Another map is already building. Wait for it to finish.")
        mid, d = _new_map(name or "map", source="build", preset=preset, status="building",
                          bbox_request=[min_lat, min_lon, max_lat, max_lon], area_km2=round(area, 1))
        cmd = ["docker", "run", "--rm", "--name", f"as2map_{mid}",
               "--mount", f"type=bind,source={BUILDER_DIR},target=/app/scripts,readonly",
               "--mount", f"type=bind,source={d},target=/app/data",
               "-w", "/app", BUILDER_IMAGE, "python", "/app/scripts/build_osm_map.py",
               "--bbox", f"{min_lat},{min_lon},{max_lat},{max_lon}", "--name", mid, "--out", "/app/data/map.pb"]
        log = open(d / "build.log", "w", encoding="utf-8")
        log.write(f"$ docker run ... build_osm_map.py --bbox {min_lat},{min_lon},{max_lat},{max_lon}\n")
        log.flush()
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        _JOBS[mid] = proc
        _set_meta(d, pid=proc.pid)
    threading.Thread(target=_after_build, args=(mid, proc, log), daemon=True).start()
    return get_map(mid)


def _after_build(mid: str, proc: subprocess.Popen, log: Any) -> None:
    code = proc.wait()
    log.close()
    d = MAPS / mid
    with _LOCK:
        if not d.exists() or (_json(d / "meta.json", {}) or {}).get("status") == "cancelled":
            return  # deleted or cancelled while building
        if code == 0 and (d / "map.pb").is_file():
            shutil.rmtree(d / "cache", ignore_errors=True)  # OSM GeoJSON stages (tens of MB), not needed any more
            _start_prepare(mid)
        else:
            _set_meta(d, status="failed", error=f"The map build failed (exit code {code}). See the build log below.")


def cancel(map_id: str) -> dict:
    d = map_dir(map_id)
    meta = _json(d / "meta.json", {}) or {}
    if meta.get("status") == "building":
        _set_meta(d, status="cancelled", error="Build cancelled.")
        subprocess.run(["docker", "kill", f"as2map_{map_id}"], capture_output=True, timeout=30, creationflags=NO_WINDOW)
    proc = _JOBS.get(map_id)
    if proc and proc.poll() is None:
        proc.kill()
    return get_map(map_id)


def delete(map_id: str) -> None:
    d = map_dir(map_id)
    cancel(map_id)
    for _ in range(20):  # the killed process may still hold files for a moment
        shutil.rmtree(d, ignore_errors=True)
        if not d.exists():
            return
        time.sleep(0.25)
    raise RuntimeError("Couldn't delete the map folder; close anything using it and try again.")


# --------------------------------------------------------------------------- people
def places(map_id: str) -> dict:
    return _json(map_dir(map_id) / "places.json", {}) or {}


def sample_people(map_id: str, n: int, seed: int | None = None) -> list[dict]:
    pl = places(map_id)
    # Maps without land-use tags fall back to any reachable building for both.
    homes, works = pl.get("homes") or pl.get("any") or [], pl.get("works") or pl.get("any") or []
    if not homes or not works:
        raise ValueError("This map has no reachable buildings to place people in.")
    rng = random.Random(seed)
    out = []
    for _ in range(max(1, min(n, 200))):
        home = rng.choice(homes)
        work = rng.choice(works)
        for _retry in range(5):  # keep home and workplace in different buildings when possible
            if work["id"] != home["id"]:
                break
            work = rng.choice(works)
        out.append({"home": home, "work": work})
    return out


def place_index(map_id: str) -> dict[int, dict]:
    pl = places(map_id)
    return {p["id"]: p for key in ("homes", "works", "any") for p in pl.get(key, [])}


# --------------------------------------------------------------------------- prepare (subprocess)
def _load_router():
    spec = importlib.util.spec_from_file_location("py_router", ROUTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def prepare(d: Path) -> None:
    import numpy as np
    import pyproj
    from pycityproto.city.map.v2 import map_pb2
    from shapely.geometry import LineString, Polygon

    started = time.time()
    pb_path = d / "map.pb"
    try:
        pb = map_pb2.Map.FromString(pb_path.read_bytes())
    except Exception as exc:
        raise ValueError(f"This isn't a readable AgentSociety/MOSS map file ({exc}).") from None
    if not pb.lanes or not pb.aois or not pb.header.projection:
        raise ValueError("The map has no roads or buildings (AOIs); it can't be used for mobility.")
    proj = pyproj.Proj(pb.header.projection)

    _set_meta(d, progress="Checking which places are reachable")
    router = _load_router()
    graph = router.RoutingGraph(pb)
    reach = graph.reachable_aois()

    # Named POIs on a 200 m grid, for "near <name>" labels.
    grid: dict[tuple[int, int], list[tuple[float, float, str]]] = {}
    for poi in pb.pois:
        if poi.name:
            x, y = poi.position.x, poi.position.y
            grid.setdefault((int(x // 200), int(y // 200)), []).append((x, y, poi.name))

    def label(x: float, y: float) -> str:
        best, best_d = "", 250.0 ** 2
        gx, gy = int(x // 200), int(y // 200)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for px, py, name in grid.get((gx + i, gy + j), ()):
                    dd = (px - x) ** 2 + (py - y) ** 2
                    if dd < best_d:
                        best, best_d = name, dd
        return best

    _set_meta(d, progress="Finding homes and workplaces")
    homes, works, anyp = [], [], []
    aoi_shapes = []
    for aoi in pb.aois:
        xs = [p.x for p in aoi.positions]
        ys = [p.y for p in aoi.positions]
        if not xs:
            continue
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        group = land_use_group(aoi.urban_land_use)
        if aoi.id in reach:
            lng, lat = proj(cx, cy, inverse=True)
            near = aoi.name or label(cx, cy)
            item = {"id": aoi.id, "lng": round(lng, 6), "lat": round(lat, 6),
                    "label": f"near {near}" if near and not aoi.name else (near or f"building {aoi.id}"),
                    "use": LAND_USE_GROUPS[group]}
            anyp.append(item)
            if group == 0:
                homes.append(item)
            elif group in WORK_GROUPS:
                works.append(item)
        if len(xs) >= 3:
            aoi_shapes.append((float(aoi.area or 0.0), group, xs, ys))
    _write_json(d / "places.json", {"homes": homes, "works": works, "any": anyp})

    _set_meta(d, progress="Drawing the preview")
    aoi_shapes.sort(key=lambda t: -t[0])
    preview_aois = []
    for _, group, xs, ys in aoi_shapes[:PREVIEW_MAX_AOIS]:
        try:
            poly = Polygon(list(zip(xs, ys))).simplify(1.5, preserve_topology=False)
        except Exception:
            continue
        if poly.is_empty or poly.geom_type != "Polygon":
            continue
        cx, cy = np.array(poly.exterior.coords).T
        lngs, lats = proj(cx, cy, inverse=True)
        preview_aois.append([group, [[round(a, 5), round(b, 5)] for a, b in zip(lngs, lats)]])
    roads = []
    lanes = {ln.id: ln for ln in pb.lanes}
    for road in pb.roads:
        lid = graph.road_main_lane.get(road.id) or (road.lane_ids[0] if road.lane_ids else None)
        if lid is None:
            continue
        pts = [(n.x, n.y) for n in lanes[lid].center_line.nodes]
        if len(pts) < 2:
            continue
        line = LineString(pts).simplify(2.0)
        cx, cy = np.array(line.coords).T
        lngs, lats = proj(cx, cy, inverse=True)
        roads.append([[round(a, 5), round(b, 5)] for a, b in zip(lngs, lats)])
    all_x = [n.x for ln in pb.lanes for n in ln.center_line.nodes[::4]]
    all_y = [n.y for ln in pb.lanes for n in ln.center_line.nodes[::4]]
    west, south = proj(min(all_x), min(all_y), inverse=True)
    east, north = proj(max(all_x), max(all_y), inverse=True)
    bbox = [round(south, 5), round(west, 5), round(north, 5), round(east, 5)]
    _write_json(d / "preview.json", {"bbox": bbox, "groups": LAND_USE_GROUPS, "aois": preview_aois, "roads": roads})

    counts = {"aois": len(pb.aois), "pois": len(pb.pois), "roads": len(pb.roads), "lanes": len(pb.lanes),
              "junctions": len(pb.junctions), "reachable": len(reach), "homes": len(homes), "works": len(works)}
    _set_meta(d, counts=counts, bbox=bbox, map_name=pb.header.name, progress="Indexing for simulations")

    # Build agentsociety2's own map cache now so the first simulation doesn't spend ~30 s on it.
    for stale in d.glob("map.pb.cache"):
        stale.unlink()
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT / ".env")
        from agentsociety2.contrib.env.mobility_space.map import Map

        Map(str(pb_path))
    except Exception as exc:  # not fatal: MobilitySpace builds the cache itself on first use
        print(f"warning: couldn't pre-build the simulation cache: {exc}")
    _set_meta(d, status="ready", progress=None, error=None, prepared_s=round(time.time() - started, 1),
              size_mb=round(pb_path.stat().st_size / 1e6, 1))


def _main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "prepare":
        d = Path(sys.argv[2]).resolve()
        try:
            prepare(d)
        except Exception as exc:
            _set_meta(d, status="failed", progress=None, error=str(exc))
            raise
    else:
        sys.exit("usage: python maps.py prepare <map_dir>")


if __name__ == "__main__":
    _main()
