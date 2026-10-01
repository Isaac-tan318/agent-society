"""Pure-Python stand-in for AgentSociety's routing server.

MobilitySpace starts a routing server as a child process and POSTs JSON to
``/city.routing.v2.RoutingService/GetRoute``. The official server is a native
binary that only exists for Linux x86_64 and macOS arm64, so on Windows the
Studio's MobilitySpace (custom/envs/mobility_space_windows.py) launches this
script instead, with the same command line:

    python py_router.py -listen localhost:PORT -map path/to/map.pb [-log-level warn]

Routes are shortest travel time over the map's own lanes:

* driving: road-level graph (roads joined through junction lanes), cost =
  length / max_speed; starts and ends on the AOI's driving gate, which in
  mosstool maps sits on a road's last driving lane. That is also where
  MobilitySpace's route drawing (Map._route_to_xys) looks for it.
* walking: lane-endpoint graph over walking lanes at 1.34 m/s, with
  per-lane moving direction.

The request ``type`` is read as a routing ``RouteType`` exactly like the
official server does. (MobilitySpace actually sends TripMode numbers, which
swaps driving and walking; mirroring the official server keeps the reply
consistent with how MobilitySpace parses it.)

The module is also used as a library by the Studio's map preparation step
(``load_graph``, ``RoutingGraph.route`` and ``RoutingGraph.reachable_aois``).
"""

from __future__ import annotations

import argparse
import heapq
import json
import logging
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from google.protobuf.json_format import ParseDict
from pycityproto.city.map.v2 import map_pb2
from pycityproto.city.routing.v2 import routing_pb2, routing_service_pb2

LANE_DRIVING, LANE_WALKING = map_pb2.LANE_TYPE_DRIVING, map_pb2.LANE_TYPE_WALKING
CONN_HEAD = map_pb2.LANE_CONNECTION_TYPE_HEAD
FORWARD, BACKWARD = routing_pb2.MOVING_DIRECTION_FORWARD, routing_pb2.MOVING_DIRECTION_BACKWARD
WALK_SPEED = 1.34  # m/s, same constant MobilitySpace uses
DEFAULT_DRIVE_SPEED = 60 / 3.6
HEAD, TAIL = 0, 1  # lane end index in the walking graph

log = logging.getLogger("py_router")


class NoRoute(Exception):
    """No route exists (unknown place, no gate, or disconnected network)."""


class RoutingGraph:
    def __init__(self, pb: map_pb2.Map) -> None:
        self.lane_type: dict[int, int] = {}
        self.lane_len: dict[int, float] = {}
        self.lane_speed: dict[int, float] = {}
        self.lane_parent: dict[int, int] = {}
        self.lane_mid: dict[int, tuple[float, float]] = {}
        succ: dict[int, list[tuple[int, int]]] = {}
        pred: dict[int, list[tuple[int, int]]] = {}
        for ln in pb.lanes:
            self.lane_type[ln.id] = ln.type
            self.lane_len[ln.id] = max(float(ln.length), 0.01)
            self.lane_speed[ln.id] = float(ln.max_speed) if ln.max_speed > 0 else DEFAULT_DRIVE_SPEED
            self.lane_parent[ln.id] = ln.parent_id
            nodes = ln.center_line.nodes
            if nodes:
                mid = nodes[len(nodes) // 2]
                self.lane_mid[ln.id] = (mid.x, mid.y)
            succ[ln.id] = [(c.id, c.type) for c in ln.successors]
            pred[ln.id] = [(c.id, c.type) for c in ln.predecessors]

        self.road_lanes: dict[int, list[int]] = {r.id: list(r.lane_ids) for r in pb.roads}
        self.junction_lanes: dict[int, list[int]] = {j.id: list(j.lane_ids) for j in pb.junctions}
        self.junction_succ: dict[int, list[int]] = {lid: [s for s, _ in succ[lid]] for lid in succ
                                                    if self.lane_parent[lid] in self.junction_lanes}
        # A road's "main" driving lane is its last driving lane: AOI driving gates attach there and
        # Map._get_driving_geo() measures route start/end s along it.
        self.road_main_lane: dict[int, int] = {}
        for rid, lids in self.road_lanes.items():
            driving = [lid for lid in lids if self.lane_type[lid] == LANE_DRIVING]
            if driving:
                self.road_main_lane[rid] = driving[-1]
        self.main_lane_road = {lid: rid for rid, lid in self.road_main_lane.items()}

        # Driving: road -> {next road: extra seconds spent on the connecting junction lane}.
        self.drive_adj: dict[int, dict[int, float]] = defaultdict(dict)
        for rid, lids in self.road_lanes.items():
            for lid in lids:
                if self.lane_type[lid] != LANE_DRIVING:
                    continue
                for sid, _ in succ[lid]:
                    for nxt, extra in self._roads_after(sid, succ):
                        if nxt != rid or extra > 0:
                            old = self.drive_adj[rid].get(nxt)
                            if old is None or extra < old:
                                self.drive_adj[rid][nxt] = extra

        # Walking: lane end -> [(other lane end, 0 s)]; walking along a lane costs len / speed.
        self.walk_adj: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)
        for lid, t in self.lane_type.items():
            if t != LANE_WALKING:
                continue
            for sid, ctype in succ[lid]:
                if self.lane_type.get(sid) == LANE_WALKING:
                    self._walk_link((lid, TAIL), (sid, HEAD if ctype == CONN_HEAD else TAIL))
            for pid, ctype in pred[lid]:
                if self.lane_type.get(pid) == LANE_WALKING:
                    self._walk_link((lid, HEAD), (pid, HEAD if ctype == CONN_HEAD else TAIL))

        # AOI gates.
        self.aoi_drive: dict[int, list[tuple[int, float]]] = {}
        self.aoi_walk: dict[int, list[tuple[int, float]]] = {}
        for aoi in pb.aois:
            self.aoi_drive[aoi.id] = [(self.main_lane_road[p.lane_id], float(p.s))
                                      for p in aoi.driving_positions if p.lane_id in self.main_lane_road]
            self.aoi_walk[aoi.id] = [(p.lane_id, float(p.s)) for p in aoi.walking_positions
                                     if self.lane_type.get(p.lane_id) == LANE_WALKING]
        self._walking_lanes = [lid for lid, t in self.lane_type.items() if t == LANE_WALKING and lid in self.lane_mid]

    # ------------------------------------------------------------------ graph helpers
    def _roads_after(self, lane_id: int, succ: dict[int, list[tuple[int, int]]]) -> list[tuple[int, float]]:
        parent = self.lane_parent.get(lane_id)
        if parent in self.road_lanes:
            return [(parent, 0.0)]
        if parent in self.junction_lanes:
            extra = self.lane_len[lane_id] / self.lane_speed[lane_id]
            return [(self.lane_parent[s], extra) for s, _ in succ.get(lane_id, [])
                    if self.lane_parent.get(s) in self.road_lanes]
        return []

    def _walk_link(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        self.walk_adj[a].add(b)
        self.walk_adj[b].add(a)

    def _road_len(self, rid: int) -> float:
        return self.lane_len[self.road_main_lane[rid]]

    def _road_time(self, rid: int, dist: float) -> float:
        return max(dist, 0.0) / self.lane_speed[self.road_main_lane[rid]]

    def _nearest_walking_lane(self, lane_id: int) -> int:
        x, y = self.lane_mid.get(lane_id, (0.0, 0.0))
        return min(self._walking_lanes, key=lambda w: (self.lane_mid[w][0] - x) ** 2 + (self.lane_mid[w][1] - y) ** 2)

    # ------------------------------------------------------------------ endpoints
    def _drive_points(self, pos, is_start: bool) -> list[tuple[int, float]]:
        if pos.HasField("aoi_position"):
            pts = self.aoi_drive.get(pos.aoi_position.aoi_id)
            if pts is None:
                raise NoRoute(f"AOI {pos.aoi_position.aoi_id} not in map")
            if not pts:
                raise NoRoute(f"AOI {pos.aoi_position.aoi_id} has no road access")
            return pts
        if pos.HasField("lane_position"):
            lid, s = pos.lane_position.lane_id, float(pos.lane_position.s)
            parent = self.lane_parent.get(lid)
            if parent in self.road_main_lane:
                scale = self._road_len(parent) / self.lane_len[lid]
                return [(parent, min(s * scale, self._road_len(parent)))]
            if parent in self.junction_lanes:  # inside a junction: continue onto the roads it feeds
                roads = {self.lane_parent[s] for jl in self.junction_lanes[parent]
                         if self.lane_type[jl] == LANE_DRIVING for s in self.junction_succ.get(jl, [])
                         if self.lane_parent.get(s) in self.road_main_lane}
                if roads:
                    return [(r, 0.0 if is_start else self._road_len(r)) for r in roads]
            raise NoRoute(f"lane {lid} is not on a drivable road")
        raise NoRoute("position has neither aoi_position nor lane_position")

    def _walk_points(self, pos) -> list[tuple[int, float]]:
        if pos.HasField("aoi_position"):
            pts = self.aoi_walk.get(pos.aoi_position.aoi_id)
            if pts is None:
                raise NoRoute(f"AOI {pos.aoi_position.aoi_id} not in map")
            if not pts:
                raise NoRoute(f"AOI {pos.aoi_position.aoi_id} has no footpath access")
            return pts
        if pos.HasField("lane_position"):
            lid, s = pos.lane_position.lane_id, float(pos.lane_position.s)
            if lid not in self.lane_type:
                raise NoRoute(f"lane {lid} not in map")
            if self.lane_type[lid] == LANE_WALKING:
                return [(lid, min(s, self.lane_len[lid]))]
            frac = min(max(s / self.lane_len[lid], 0.0), 1.0)
            parent = self.lane_parent.get(lid)
            siblings = self.road_lanes.get(parent) or self.junction_lanes.get(parent) or []
            walks = [w for w in siblings if self.lane_type[w] == LANE_WALKING]
            if not walks and self._walking_lanes:
                walks = [self._nearest_walking_lane(lid)]
            if walks:
                return [(w, frac * self.lane_len[w]) for w in walks]
            raise NoRoute("map has no footpaths")
        raise NoRoute("position has neither aoi_position nor lane_position")

    # ------------------------------------------------------------------ search
    def drive(self, start, end) -> tuple[list[int], float]:
        sources = self._drive_points(start, True)
        targets: dict[int, list[float]] = defaultdict(list)
        for rid, s in self._drive_points(end, False):
            targets[rid].append(s)
        best, best_path = float("inf"), None
        dist: dict[int, float] = {}
        prev: dict[int, int | None] = {}
        heap: list[tuple[float, int]] = []
        for rid, s in sources:
            for ts in targets.get(rid, []):  # same road, ahead of us
                if ts >= s:
                    cost = self._road_time(rid, ts - s)
                    if cost < best:
                        best, best_path = cost, [rid]
            cost = self._road_time(rid, self._road_len(rid) - s)  # reach the end of the first road
            if cost < dist.get(rid, float("inf")):
                dist[rid], prev[rid] = cost, None
                heapq.heappush(heap, (cost, rid))
        while heap:
            d, rid = heapq.heappop(heap)
            if d > dist.get(rid, float("inf")) or d >= best:
                continue
            for nxt, extra in self.drive_adj.get(rid, {}).items():
                base = d + extra
                for ts in targets.get(nxt, []):
                    cost = base + self._road_time(nxt, ts)
                    if cost < best:
                        best, best_path = cost, self._unwind(prev, rid) + [nxt]
                nd = base + self._road_time(nxt, self._road_len(nxt))
                if nd < dist.get(nxt, float("inf")):
                    dist[nxt], prev[nxt] = nd, rid
                    heapq.heappush(heap, (nd, nxt))
        if best_path is None:
            raise NoRoute("no driving route between these places")
        return best_path, best

    @staticmethod
    def _unwind(prev: dict[int, Any], node: int) -> list[int]:
        path = [node]
        while prev.get(path[-1]) is not None:
            path.append(prev[path[-1]])
        return path[::-1]

    def walk(self, start, end) -> tuple[list[tuple[int, int]], float]:
        sources = self._walk_points(start)
        targets: dict[int, list[float]] = defaultdict(list)
        for lid, s in self._walk_points(end):
            targets[lid].append(s)
        best, best_route = float("inf"), None
        dist: dict[tuple[int, int], float] = {}
        prev: dict[tuple[int, int], Any] = {}
        heap: list[tuple[float, tuple[int, int]]] = []
        for lid, s in sources:
            length = self.lane_len[lid]
            for ts in targets.get(lid, []):  # same footpath
                cost = abs(ts - s) / WALK_SPEED
                if cost < best:
                    best, best_route = cost, [(lid, FORWARD if ts >= s else BACKWARD)]
            for end, cost in (((lid, HEAD), s / WALK_SPEED), ((lid, TAIL), (length - s) / WALK_SPEED)):
                if cost < dist.get(end, float("inf")):
                    dist[end], prev[end] = cost, ("start", lid)
                    heapq.heappush(heap, (cost, end))
        while heap:
            d, node = heapq.heappop(heap)
            if d > dist.get(node, float("inf")) or d >= best:
                continue
            lid, side = node
            # Arrive at a target on this lane from this end.
            for ts in targets.get(lid, []):
                along = ts if side == HEAD else self.lane_len[lid] - ts
                cost = d + along / WALK_SPEED
                if cost < best and prev.get(node, (None,))[0] != "start":
                    best, best_route = cost, self._walk_route(prev, node) + [(lid, FORWARD if side == HEAD else BACKWARD)]
            nbrs = [((lid, 1 - side), self.lane_len[lid] / WALK_SPEED)] + [(n, 0.0) for n in self.walk_adj.get(node, ())]
            for nxt, step in nbrs:
                nd = d + step
                if nd < dist.get(nxt, float("inf")):
                    dist[nxt], prev[nxt] = nd, node
                    heapq.heappush(heap, (nd, nxt))
        if best_route is None:
            raise NoRoute("no walking route between these places")
        # Merge consecutive entries on the same lane (can't happen with distinct lanes, but be safe).
        merged: list[tuple[int, int]] = []
        for seg in best_route:
            if not merged or merged[-1][0] != seg[0]:
                merged.append(seg)
        return merged, best

    def _walk_route(self, prev: dict, node: tuple[int, int]) -> list[tuple[int, int]]:
        """Lanes walked, with direction, to reach lane end ``node`` (excluding the lane we arrive on)."""
        chain = [node]
        while not (isinstance(prev[chain[-1]], tuple) and prev[chain[-1]][0] == "start"):
            chain.append(prev[chain[-1]])
        chain.reverse()  # chain[0] is an end of the first lane
        first_lane, first_side = chain[0]
        route = [(first_lane, FORWARD if first_side == TAIL else BACKWARD)]
        for a, b in zip(chain, chain[1:]):
            if a[0] == b[0]:  # walked the full length of lane a[0]
                route.append((a[0], FORWARD if a[1] == HEAD else BACKWARD))
        return route

    # ------------------------------------------------------------------ API
    def route(self, request: dict) -> dict:
        req = ParseDict(request, routing_service_pb2.GetRouteRequest(), ignore_unknown_fields=True)
        if (req.start.HasField("aoi_position") and req.end.HasField("aoi_position")
                and req.start.aoi_position.aoi_id == req.end.aoi_position.aoi_id):
            raise NoRoute("already at the destination")
        if req.type == routing_pb2.ROUTE_TYPE_DRIVING:
            road_ids, eta = self.drive(req.start, req.end)
            return {"journeys": [{"type": routing_pb2.JOURNEY_TYPE_DRIVING,
                                  "driving": {"road_ids": road_ids, "eta": eta}}]}
        if req.type == routing_pb2.ROUTE_TYPE_WALKING:
            segs, eta = self.walk(req.start, req.end)
            return {"journeys": [{"type": routing_pb2.JOURNEY_TYPE_WALKING,
                                  "walking": {"route": [{"lane_id": l, "moving_direction": d} for l, d in segs],
                                              "eta": eta}}]}
        raise NoRoute(f"unsupported route type {req.type}")

    def reachable_aois(self) -> set[int]:
        """AOIs whose driving gate is in the largest strongly connected road network and whose
        walking gate is in the largest footpath network, so trips between any two of them succeed."""
        big_roads = self._largest_scc()
        big_walk = self._largest_walk_component()
        return {a for a in self.aoi_drive
                if any(r in big_roads for r, _ in self.aoi_drive[a])
                and any(l in big_walk for l, _ in self.aoi_walk.get(a, []))}

    def _largest_scc(self) -> set[int]:
        nodes = list(self.road_main_lane)
        index, low, on_stack, stack, best = {}, {}, set(), [], set()
        counter = 0
        for root in nodes:  # iterative Tarjan
            if root in index:
                continue
            work = [(root, iter(self.drive_adj.get(root, {})))]
            index[root] = low[root] = counter; counter += 1
            stack.append(root); on_stack.add(root)
            while work:
                v, it = work[-1]
                advanced = False
                for w in it:
                    if w not in self.road_main_lane:
                        continue
                    if w not in index:
                        index[w] = low[w] = counter; counter += 1
                        stack.append(w); on_stack.add(w)
                        work.append((w, iter(self.drive_adj.get(w, {}))))
                        advanced = True
                        break
                    if w in on_stack:
                        low[v] = min(low[v], index[w])
                if advanced:
                    continue
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = set()
                    while True:
                        w = stack.pop(); on_stack.discard(w); comp.add(w)
                        if w == v:
                            break
                    if len(comp) > len(best):
                        best = comp
        return best

    def _largest_walk_component(self) -> set[int]:
        seen: set[int] = set()
        best: set[int] = set()
        for lid in self._walking_lanes:
            if lid in seen:
                continue
            comp, todo = set(), [lid]
            seen.add(lid)
            while todo:
                cur = todo.pop()
                comp.add(cur)
                for side in (HEAD, TAIL):
                    for other, _ in self.walk_adj.get((cur, side), ()):
                        if other not in seen:
                            seen.add(other)
                            todo.append(other)
            if len(comp) > len(best):
                best = comp
        return best


def load_graph(map_path: str | Path) -> RoutingGraph:
    started = time.time()
    pb = map_pb2.Map.FromString(Path(map_path).read_bytes())
    graph = RoutingGraph(pb)
    log.info("graph ready in %.1fs: %d roads, %d walking lanes", time.time() - started,
             len(graph.road_main_lane), len(graph._walking_lanes))
    return graph


# ---------------------------------------------------------------------- HTTP server
class _State:
    graph: RoutingGraph | None = None
    error: str | None = None
    ready = threading.Event()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # route stdlib access logs to our logger
        log.debug(fmt, *args)

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send(200, {"ready": _State.ready.is_set(), "error": _State.error})

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if not self.path.rstrip("/").endswith("/GetRoute"):
            self._send(404, {"code": "not_found", "message": self.path})
            return
        if not _State.ready.wait(timeout=600) or _State.graph is None:
            self._send(503, {"code": "unavailable", "message": _State.error or "map still loading"})
            return
        try:
            self._send(200, _State.graph.route(json.loads(body or b"{}")))
        except NoRoute as exc:
            self._send(422, {"code": "not_found", "message": str(exc)})
        except Exception as exc:  # malformed request
            log.exception("route failed")
            self._send(400, {"code": "invalid_argument", "message": str(exc)})


def _load_in_background(map_path: str) -> None:
    try:
        _State.graph = load_graph(map_path)
    except Exception as exc:
        _State.error = f"failed to load map: {exc}"
        log.exception(_State.error)
    finally:
        _State.ready.set()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Python routing server for MobilitySpace")
    ap.add_argument("-listen", required=True, help="host:port")
    ap.add_argument("-map", required=True, help="map .pb file")
    ap.add_argument("-log-level", default="warn")
    args = ap.parse_args(argv)
    level = {"warn": "WARNING"}.get(args.log_level.lower(), args.log_level.upper())
    logging.basicConfig(level=getattr(logging, level, logging.WARNING), format="[py_router] %(message)s")
    host, port = args.listen.rsplit(":", 1)
    server = ThreadingHTTPServer((host, int(port)), _Handler)
    server.daemon_threads = True
    threading.Thread(target=_load_in_background, args=(args.map,), daemon=True).start()
    log.info("listening on %s", args.listen)
    server.serve_forever()


if __name__ == "__main__":
    main()
