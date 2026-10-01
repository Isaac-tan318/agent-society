#!/usr/bin/env python3
"""Build an AgentSociety map (.pb) for any bounding box from OpenStreetMap.

Adapted from agentsociety1/scripts/build_singapore_map.py (the user's AgentSociety 1
project). It runs inside that project's map-builder Docker image, which has mosstool
1.3.21 and geojson<3.3.0 (mosstool needs numpy>=2 and can't share the Studio's env):

    docker run --rm --mount type=bind,source=<this dir>,target=/app/scripts,readonly \
        --mount type=bind,source=<map dir>,target=/app/data -w /app \
        agentsociety-singapore-mapbuilder:latest \
        python /app/scripts/build_osm_map.py --bbox 1.24,103.79,1.33,103.89 --name singapore_central \
        --out /app/data/map.pb

The Studio (ui/maps.py) runs this for you. mosstool downloads raw OSM data from the
public Overpass API; each stage is cached as GeoJSON under <out dir>/cache/.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import geojson
from mosstool.map.builder import Builder
from mosstool.map.osm import Building, PointOfInterest, RoadNet
from mosstool.type import Map
from mosstool.util.format_converter import dict2pb


def _stage(path: str, produce):
    """Run ``produce(path)`` unless ``path`` is cached, then read the result back from disk.

    mosstool's create_* helpers return plain feature lists while a cache hit is a
    FeatureCollection, so always reload from disk for a single shape.
    """
    name = os.path.basename(path)
    if os.path.exists(path):
        logging.info("[cache] reusing %s", name)
    else:
        started = time.time()
        logging.info("[build] %s ...", name)
        produce(path)
        logging.info("[build] %s done in %.1fs", name, time.time() - started)
    with open(path, "r", encoding="utf-8") as f:
        return geojson.load(f)


def _features(fc):
    return fc["features"] if isinstance(fc, dict) else fc


def build(bbox: dict, name: str, out_path: str, workers: int) -> int:
    # Transverse Mercator centred on the area keeps projection distortion negligible.
    lat0 = (bbox["min_lat"] + bbox["max_lat"]) / 2
    lon0 = (bbox["min_lon"] + bbox["max_lon"]) / 2
    proj_str = f"+proj=tmerc +lat_0={lat0:.6f} +lon_0={lon0:.6f}"
    cache = os.path.join(os.path.dirname(out_path) or ".", "cache")
    os.makedirs(cache, exist_ok=True)
    box = dict(max_latitude=bbox["max_lat"], min_latitude=bbox["min_lat"],
               max_longitude=bbox["max_lon"], min_longitude=bbox["min_lon"])
    logging.info("Area %s, projection %s", bbox, proj_str)

    # 1. Road network (Overpass download + topology).
    net = _stage(os.path.join(cache, "roads.geojson"),
                 lambda p: RoadNet(proj_str=proj_str, **box).create_road_net(p))
    # 2. Buildings -> AOIs. Agents' homes and workplaces are AOIs, so a map without them is useless.
    aois = _stage(os.path.join(cache, "aois.geojson"),
                  lambda p: Building(proj_str=proj_str, **box).create_building(output_path=p))
    # 3. Points of interest (shops, offices, amenities).
    pois = _stage(os.path.join(cache, "pois.geojson"),
                  lambda p: PointOfInterest(**box).create_pois(output_path=p))

    logging.info("[build] compiling map protobuf (workers=%d) ...", workers)
    started = time.time()
    builder = Builder(net=net, proj_str=proj_str, aois=_features(aois), pois=_features(pois),
                      gen_sidewalk_speed_limit=50 / 3.6, road_expand_mode="M", enable_tqdm=True, workers=workers)
    pb = dict2pb(builder.build(name), Map())
    if not pb.aois:
        logging.error("The map has no buildings (AOIs), so agents can't be placed. Choose a larger or denser area.")
        return 2
    tmp = out_path + ".partial"
    with open(tmp, "wb") as f:
        f.write(pb.SerializeToString())
    os.replace(tmp, out_path)
    logging.info("[build] compiled in %.1fs", time.time() - started)
    logging.info("Wrote %s (%.1f MB): %d AOIs, %d POIs, %d lanes, %d roads, %d junctions", out_path,
                 os.path.getsize(out_path) / 1e6, len(pb.aois), len(pb.pois), len(pb.lanes), len(pb.roads),
                 len(pb.junctions))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bbox", required=True, help="min_lat,min_lon,max_lat,max_lon")
    ap.add_argument("--name", required=True, help="map name stored in the map header")
    ap.add_argument("--out", required=True, help="output .pb path")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    min_lat, min_lon, max_lat, max_lon = (float(v) for v in args.bbox.split(","))
    bbox = {"min_lat": min_lat, "min_lon": min_lon, "max_lat": max_lat, "max_lon": max_lon}
    return build(bbox, args.name, args.out, args.workers)


if __name__ == "__main__":
    # Required: Builder uses multiprocessing.
    raise SystemExit(main())
