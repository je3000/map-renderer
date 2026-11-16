#!/usr/bin/env python3
"""Small local web app for rendering Copernicus DEM contours."""

import json
import math
import mimetypes
import os
import sys
import threading
import time
import traceback
import uuid
import urllib.parse
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.patches import Rectangle
from matplotlib.path import Path as MplPath
import numpy as np
import rasterio
from affine import Affine
from rasterio.merge import merge
from rasterio.plot import plotting_extent
from rasterio.warp import (
    Resampling,
    calculate_default_transform,
    reproject,
    transform as transform_coords,
)
from shapely.geometry import LineString, Polygon, box
from shapely.ops import (
    linemerge,
    polygonize,
    transform as transform_geometry,
    unary_union,
)
from shapely.validation import make_valid
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent
GENERATED = ROOT / "generated"
BASE_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
MAX_SPAN = 2.0
OVERPASS_URLS = (
    "https://api.overpass-turbo.eu/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
GENERATED.mkdir(exist_ok=True)


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"


def tile_url(lat: int, lon: int) -> str:
    name = tile_name(lat, lon)
    return f"{BASE_URL}/{name}/{name}.tif"


def fetch_elevation(bounds):
    west, south, east, north = bounds
    datasets = []
    try:
        for lat in range(math.floor(south), math.ceil(north)):
            for lon in range(math.floor(west), math.ceil(east)):
                url = tile_url(lat, lon)
                try:
                    datasets.append(rasterio.open(url))
                except rasterio.errors.RasterioIOError:
                    continue
        if not datasets:
            raise ValueError("No Copernicus DEM tiles were found for these bounds.")
        elevation, transform = merge(datasets, bounds=bounds)
        return elevation[0], transform, datasets[0].crs
    finally:
        for dataset in datasets:
            dataset.close()


def reproject_dem(elevation, transform, crs, bounds):
    west, south, east, north = bounds
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    zone = int((center_lon + 180) / 6) + 1
    dst_crs = f"EPSG:{32600 + zone if center_lat >= 0 else 32700 + zone}"
    height, width = elevation.shape
    dst_transform, dst_width, dst_height = calculate_default_transform(
        crs, dst_crs, width, height, west, south, east, north
    )
    projected = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
    reproject(
        source=elevation,
        destination=projected,
        src_transform=transform,
        src_crs=crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return projected, dst_transform


def fetch_osm_water(bounds):
    """Fetch OSM water and assemble way/relation polygons, including holes."""
    west, south, east, north = bounds
    log(f"Water bbox: west={west}, south={south}, east={east}, north={north}")
    query = f"""[out:json][timeout:180];
(
  way[\"natural\"=\"water\"]({south},{west},{north},{east});
  way[\"natural\"=\"wetland\"]({south},{west},{north},{east});
  way[\"natural\"=\"glacier\"]({south},{west},{north},{east});
  way[\"water\"]({south},{west},{north},{east});
  way[\"waterway\"]({south},{west},{north},{east});
  way[\"landuse\"=\"basin\"]({south},{west},{north},{east});
  way[\"waterway\"=\"riverbank\"]({south},{west},{north},{east});
  way[\"natural\"=\"coastline\"]({south},{west},{north},{east});
  relation[\"type\"=\"multipolygon\"][\"natural\"=\"water\"]({south},{west},{north},{east});
  relation[\"type\"=\"multipolygon\"][\"natural\"=\"wetland\"]({south},{west},{north},{east});
  relation[\"type\"=\"multipolygon\"][\"water\"]({south},{west},{north},{east});
  relation[\"type\"=\"multipolygon\"][\"natural\"=\"glacier\"]({south},{west},{north},{east});
  relation[\"type\"=\"multipolygon\"][\"landuse\"=\"basin\"]({south},{west},{north},{east});
);
out geom({south},{west},{north},{east});
>;
out geom({south},{west},{north},{east}) qt;"""
    data = None
    for endpoint in OVERPASS_URLS:
        log(f"Overpass request started: {endpoint}")
        request = urllib.request.Request(
            endpoint,
            data=urllib.parse.urlencode({"data": query}).encode(),
            headers={
                "User-Agent": "TopoRenderer/1.0 (local OSM map tool)",
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Accept": "application/json",
                "Origin": "https://overpass-turbo.eu",
                "Referer": "https://overpass-turbo.eu/",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=200) as response:
                data = json.load(response)
            log(f"Overpass response received: {len(data.get('elements', []))} elements")
            break
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
            log(f"Overpass request failed: {error}")
            continue
        if data is not None:
            break
    if data is None:
        raise OSError("OpenStreetMap data services timed out.")
    log("Parsing OSM ways and relations")
    elements = data.get("elements", [])
    ways = {}
    for element in elements:
        if element.get("type") != "way":
            continue
        points = [
            (point["lon"], point["lat"])
            for point in element.get("geometry", [])
            if point and "lon" in point and "lat" in point
        ]
        if len(points) >= 2:
            ways[element["id"]] = points
    areas = []
    lines = []

    def close_at_bbox(points):
        if points[0] == points[-1]:
            return points
        west, south, east, north = bounds
        eps = max(east - west, north - south) * 1e-7

        def edge_point(point):
            x, y = point
            if abs(x - west) <= eps:
                return west, min(north, max(south, y))
            if abs(x - east) <= eps:
                return east, min(north, max(south, y))
            if abs(y - south) <= eps:
                return min(east, max(west, x)), south
            if abs(y - north) <= eps:
                return min(east, max(west, x)), north
            return None

        start, end = edge_point(points[0]), edge_point(points[-1])
        if not start or not end:
            return points
        perimeter = [
            (west, south),
            (east, south),
            (east, north),
            (west, north),
            (west, south),
        ]

        def position(point):
            for index, ((x1, y1), (x2, y2)) in enumerate(zip(perimeter, perimeter[1:])):
                if x1 == x2 and point[0] == x1:
                    return index + (point[1] - y1) / (y2 - y1 or 1)
                if y1 == y2 and point[1] == y1:
                    return index + (point[0] - x1) / (x2 - x1 or 1)
            return 0

        end_position, start_position = position(end), position(start)
        if start_position <= end_position:
            start_position += 4
        boundary = []
        for index, point in enumerate(perimeter[:-1]):
            value = index
            if end_position <= value <= start_position:
                boundary.append(point)
        return points + boundary + [start]

    seen_area_ids = set()
    for element in elements:
        if element.get("type") != "way":
            continue
        tags = element.get("tags", {})
        points = ways.get(element["id"], [])
        if len(points) < 2:
            continue
        if tags.get("waterway"):
            lines.append(points)
        if (
            tags.get("natural") in {"water", "wetland", "glacier", "coastline"}
            or tags.get("water")
            or tags.get("landuse") == "basin"
            or tags.get("waterway") == "riverbank"
        ):
            closed = close_at_bbox(points)
            if closed and (closed[0] == closed[-1] or len(closed) > 3):
                areas.append(Polygon(closed))
            seen_area_ids.add(element["id"])

    for relation in (
        element for element in elements if element.get("type") == "relation"
    ):
        outers, inners = [], []
        for member in relation.get("members", []):
            if member.get("type") != "way" or member.get("ref") not in ways:
                continue
            (inners if member.get("role") == "inner" else outers).append(
                ways[member["ref"]]
            )
        if not outers:
            continue
        outer_polygons = list(
            polygonize(linemerge([LineString(path) for path in outers]))
        )
        inner_polygons = (
            list(polygonize(linemerge([LineString(path) for path in inners])))
            if inners
            else []
        )
        holes = unary_union(inner_polygons) if inner_polygons else None
        for polygon in outer_polygons:
            polygon = polygon.difference(holes) if holes else polygon
            if not polygon.is_empty:
                areas.append(polygon)
    clip = box(west, south, east, north)
    clipped_areas = []
    for area in areas:
        if area.is_empty:
            continue
        try:
            repaired = make_valid(area)
            clipped = repaired.intersection(clip)
        except Exception:
            clipped = area.buffer(0).intersection(clip)
        if not clipped.is_empty:
            clipped_areas.append(clipped)
    log(f"OSM geometry ready: {len(clipped_areas)} areas, {len(lines)} waterways")
    return clipped_areas, lines


def render_water_map(
    bounds,
    color,
    line_color,
    line_width,
    long_side,
    output_format="png",
    fill_water=False,
):
    if output_format not in {"png", "svg"}:
        raise ValueError("Output format must be png or svg.")
    log("Water map generation started")
    areas, waterways = fetch_osm_water(bounds)
    west, south, east, north = bounds
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    zone = int((center_lon + 180) / 6) + 1
    dst_crs = f"EPSG:{32600 + zone if center_lat >= 0 else 32700 + zone}"
    projector = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    areas = [transform_geometry(projector.transform, area) for area in areas]
    waterways = [[projector.transform(x, y) for x, y in line] for line in waterways]
    projected_corners = [
        projector.transform(x, y)
        for x, y in ((west, south), (west, north), (east, south), (east, north))
    ]
    west_m = min(point[0] for point in projected_corners)
    east_m = max(point[0] for point in projected_corners)
    south_m = min(point[1] for point in projected_corners)
    north_m = max(point[1] for point in projected_corners)
    projected_width = abs(east_m - west_m)
    projected_height = abs(north_m - south_m)
    width = (
        long_side
        if projected_width >= projected_height
        else max(1, round(long_side * projected_width / projected_height))
    )
    height = (
        long_side
        if projected_height > projected_width
        else max(1, round(long_side * projected_height / projected_width))
    )
    filename = f"{uuid.uuid4().hex}.{output_format}"
    output = GENERATED / filename
    fig = plt.figure(
        figsize=(width / 180, height / 180),
        dpi=180,
        facecolor="none" if color == "none" else color,
    )
    ax = fig.add_axes([0, 0, 1, 1], facecolor="none" if color == "none" else color)
    ax.set_axis_off()

    def draw_polygon(polygon):
        if polygon.geom_type == "GeometryCollection":
            for geometry in polygon.geoms:
                draw_polygon(geometry)
            return
        if polygon.geom_type not in {"Polygon", "MultiPolygon"}:
            return
        polygons = polygon.geoms if polygon.geom_type == "MultiPolygon" else [polygon]
        for item in polygons:
            vertices = []
            codes = []
            for ring in [item.exterior, *item.interiors]:
                coordinates = list(ring.coords)
                vertices.extend(coordinates)
                codes.extend(
                    [MplPath.MOVETO]
                    + [MplPath.LINETO] * (len(coordinates) - 2)
                    + [MplPath.CLOSEPOLY]
                )
            ax.add_patch(
                PathPatch(
                    MplPath(vertices, codes),
                    facecolor=line_color if fill_water else "none",
                    edgecolor=line_color,
                    linewidth=max(line_width, 0.35),
                    zorder=1,
                )
            )

    for area in areas:
        draw_polygon(area)
    for line in waterways:
        xs, ys = zip(*line)
        ax.plot(xs, ys, color=line_color, linewidth=max(line_width, 0.35), zorder=2)
    ax.set(xlim=(west_m, east_m), ylim=(south_m, north_m), aspect="equal")
    fig.savefig(
        output,
        format=output_format,
        facecolor="none" if color == "none" else color,
        edgecolor="none",
        transparent=color == "none",
        bbox_inches=None,
        pad_inches=0,
    )
    plt.close(fig)
    log(f"Water map written: {filename}")
    return filename, 0, 0, (height, width)


def render_map(
    bounds,
    interval,
    color,
    line_color,
    line_width,
    long_side,
    output_format="png",
    show_water=True,
):
    print("Rendering map with bounds:", bounds)
    if output_format not in {"png", "svg"}:
        raise ValueError("Output format must be png or svg.")
    elevation, transform, crs = fetch_elevation(bounds)
    projected, projected_transform = reproject_dem(elevation, transform, crs, bounds)
    valid = np.isfinite(projected)
    top, bottom = 0, projected.shape[0]
    left, right = 0, projected.shape[1]
    while right - left > 1 and bottom - top > 1:
        if (
            valid[top, left:right].all()
            and valid[bottom - 1, left:right].all()
            and valid[top:bottom, left].all()
            and valid[top:bottom, right - 1].all()
        ):
            break
        if not valid[top, left:right].all():
            top += 1
        if not valid[bottom - 1, left:right].all():
            bottom -= 1
        if not valid[top:bottom, left].all():
            left += 1
        if not valid[top:bottom, right - 1].all():
            right -= 1
    projected = projected[top:bottom, left:right]
    projected_transform = projected_transform * Affine.translation(left, top)
    projected_height, projected_width = projected.shape
    if projected_width >= projected_height:
        output_width = long_side
        output_height = max(1, round(long_side * projected_height / projected_width))
    else:
        output_height = long_side
        output_width = max(1, round(long_side * projected_width / projected_height))
    minimum = float(np.nanmin(projected))
    maximum = float(np.nanmax(projected))
    start = math.floor(minimum / interval) * interval
    stop = math.ceil(maximum / interval) * interval + interval
    levels = np.arange(start, stop, interval)
    # Do not draw a contour on the DEM boundary; it appears as a frame.
    levels = levels[(levels > minimum) & (levels < maximum)]
    extent = plotting_extent(projected, projected_transform)
    projected = np.ma.masked_invalid(projected)

    # if show_water:
    #     try:
    #         water_areas, waterways = fetch_osm_water(bounds)
    #     except (OSError, ValueError, json.JSONDecodeError):
    #         # Hydrography is an optional overlay; an Overpass outage should
    #         # not prevent the elevation export from completing.
    #         water_areas, waterways = [], []
    # else:
    #     water_areas, waterways = [], []

    def project_path(path):
        xs, ys = transform_coords(
            "EPSG:4326", crs, [point[0] for point in path], [point[1] for point in path]
        )
        return xs, ys

    filename = f"{uuid.uuid4().hex}.{output_format}"
    output = GENERATED / filename
    fig = plt.figure(
        figsize=(output_width / 180, output_height / 180),
        dpi=180,
        frameon=True,
        facecolor="none" if color == "none" else color,
    )
    ax = fig.add_axes(
        [0, 0, 1, 1],
        frameon=True,
        facecolor="none" if color == "none" else color,
    )
    ax.set_axis_off()
    if color != "none":
        ax.add_patch(
            Rectangle(
                (extent[0], extent[2]),
                extent[1] - extent[0],
                extent[3] - extent[2],
                facecolor=color,
                edgecolor="none",
                zorder=0,
            )
        )
    # for area in water_areas:
    #     xs, ys = project_path(area)
    #     ax.fill(xs, ys, color="#9bc9d8", linewidth=0, zorder=1)
    # for line in waterways:
    #     xs, ys = project_path(line)
    #     ax.plot(xs, ys, color="#6daabd", linewidth=max(line_width, 0.35), zorder=2)
    if levels.size:
        ax.contour(
            projected,
            levels=levels,
            extent=extent,
            origin="upper",
            colors=line_color,
            linewidths=line_width,
            zorder=3,
        )
    ax.set_aspect("equal")
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.margins(0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.savefig(
        output,
        format=output_format,
        facecolor="none" if color == "none" else color,
        edgecolor="none",
        transparent=color == "none",
        bbox_inches=None,
        pad_inches=0,
    )
    plt.close(fig)
    print("Map rendered to file:", output)
    return filename, minimum, maximum, (output_height, output_width)


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, body, content_type, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if path == "/":
            path = "/index.html"
        file_path = ROOT / path.lstrip("/")
        if path.startswith("/generated/"):
            file_path = GENERATED / Path(path).name
        if not file_path.is_file() or ROOT not in file_path.parents:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_bytes(
            file_path.read_bytes(),
            mimetypes.guess_type(file_path)[0] or "application/octet-stream",
        )

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/api/render":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            bounds = tuple(
                float(payload[key]) for key in ("west", "south", "east", "north")
            )
            west, south, east, north = bounds
            if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
                raise ValueError("Bounds must be valid geographic coordinates.")
            if east - west > MAX_SPAN or north - south > MAX_SPAN:
                raise ValueError(
                    f"Please keep each map span at or below {MAX_SPAN} degrees."
                )
            interval = float(payload.get("interval", 40))
            if interval <= 0:
                raise ValueError("Contour interval must be greater than zero.")
            long_side = int(payload.get("longSide", 2000))
            if not 100 <= long_side <= 6000:
                raise ValueError("The long side must be between 100 and 6000 pixels.")

            common = (
                bounds,
                payload.get("background", "#f3ead2"),
                payload.get("lineColor", "#26352d"),
                float(payload.get("lineWidth", 0.4)),
                long_side,
                payload.get("format", "png"),
            )
            mode = payload.get("mode", "topo")
            if mode not in {"topo", "water"}:
                raise ValueError("Unknown map mode.")
            if mode == "water":
                result = render_water_map(
                    *common, bool(payload.get("fillWater", False))
                )
            else:
                result = render_map(
                    bounds, interval, *common[1:], bool(payload.get("showWater", True))
                )
            filename, minimum, maximum, shape = result
            body = json.dumps(
                {
                    "url": f"/generated/{filename}",
                    "filename": filename,
                    "min": round(minimum),
                    "max": round(maximum),
                    "shape": list(shape),
                }
            ).encode()
            self.send_bytes(body, "application/json")
        except Exception as exc:  # Return useful errors to the UI.
            log(f"Render failed: {exc}")
            traceback.print_exc()
            body = json.dumps({"error": str(exc)}).encode()
            self.send_bytes(body, "application/json", HTTPStatus.BAD_REQUEST)


def reload_on_change(server):
    watched = [path for path in ROOT.glob("*.py")]
    modified = {path: path.stat().st_mtime_ns for path in watched}
    while True:
        time.sleep(0.5)
        for path in watched:
            current = path.stat().st_mtime_ns
            if current != modified[path]:
                server.shutdown()
                os.execv(sys.executable, [sys.executable, *sys.argv])


if __name__ == "__main__":
    host = os.environ.get("TOPO_HOST", "0.0.0.0")
    port = int(os.environ.get("TOPO_PORT", "8002"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Topo app listening on {host}:{port}")
    if "--reload" in sys.argv:
        threading.Thread(target=reload_on_change, args=(server,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
