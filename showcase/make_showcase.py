"""Build the Cairo Metro showcase from the committed data (offline).

Run from the repository root:  python showcase/make_showcase.py

Question: which Cairo Metro stations lie within 5 km of Sadat (Tahrir), the
system's central interchange, and how far away is each one?

Steps: csv_to_geojson.convert_file reads showcase/data/cairo_metro_stations.csv
(WGS 84 degrees, written as [lon, lat] in GeoJSON). Distances are geodesic
(great-circle, haversine on a sphere of the WGS 84 mean radius, 6371.0088 km),
never planar maths on degrees. The 5 km circle is built with the matching
spherical destination formula.
"""
import html
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from csv_to_geojson import convert_file  # noqa: E402

EARTH_RADIUS_KM = 6371.0088  # WGS 84 mean radius
CENTER_NAME = "Sadat"
RADIUS_KM = 5.0
BANDS = [  # (upper bound km, label, colour)
    (2.0, "0-2 km", "#08306b"),
    (5.0, "2-5 km", "#2171b5"),
    (10.0, "5-10 km", "#6baed6"),
    (math.inf, "over 10 km", "#d9a441"),
]
CREDIT = "Data: (c) OpenStreetMap contributors, ODbL"
REPO_URL = "https://github.com/AmmarYasser455/csv-to-geojson"


def distance_km(lon1, lat1, lon2, lat2):
    """Great-circle distance in km between two lon/lat points (degrees)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def circle_ring(lon, lat, radius_km, n=72):
    """Closed counter-clockwise ring (RFC 7946) of points radius_km from lon/lat."""
    phi1, lmb1 = math.radians(lat), math.radians(lon)
    delta = radius_km / EARTH_RADIUS_KM
    ring = []
    for i in range(n + 1):
        theta = math.radians(360 - 360 * i / n)  # decreasing bearing = counter-clockwise
        phi2 = math.asin(math.sin(phi1) * math.cos(delta)
                         + math.cos(phi1) * math.sin(delta) * math.cos(theta))
        lmb2 = lmb1 + math.atan2(math.sin(theta) * math.sin(delta) * math.cos(phi1),
                                 math.cos(delta) - math.sin(phi1) * math.sin(phi2))
        ring.append([round(math.degrees(lmb2), 6), round(math.degrees(phi2), 6)])
    ring[-1] = list(ring[0])
    return ring


def band_of(d):
    for upper, label, _ in BANDS:
        if d <= upper:
            return label
    return BANDS[-1][1]


def analyse(csv_path):
    """Run csv_to_geojson on the CSV and add distance properties.

    Returns (geojson, summary dict, conversion result).
    """
    result = convert_file(csv_path)
    if result.errors:
        raise RuntimeError(f"{len(result.errors)} rows could not be parsed")
    feats = result.geojson["features"]
    centre = next(f for f in feats if f["properties"]["name"] == CENTER_NAME)
    clon, clat = centre["geometry"]["coordinates"]
    for f in feats:
        lon, lat = f["geometry"]["coordinates"]
        d = round(distance_km(clon, clat, lon, lat), 3)
        f["properties"].update(
            feature_type="station",
            dist_to_sadat_km=d,
            band=band_of(d),
            within_5km=d <= RADIUS_KM,
        )
    feats.sort(key=lambda f: (f["properties"]["dist_to_sadat_km"], f["properties"]["osm_id"]))
    others = [f for f in feats if f["properties"]["name"] != CENTER_NAME]
    dists = [f["properties"]["dist_to_sadat_km"] for f in others]
    summary = {
        "stations": len(feats),
        "within_5km": sum(1 for d in dists if d <= RADIUS_KM),
        "within_2km": sum(1 for d in dists if d <= 2.0),
        "median_km": round(statistics.median(dists), 2),
        "nearest": others[0]["properties"]["name"],
        "nearest_km": others[0]["properties"]["dist_to_sadat_km"],
        "farthest": others[-1]["properties"]["name"],
        "farthest_km": others[-1]["properties"]["dist_to_sadat_km"],
        "lat_column": result.lat_column,
        "lon_column": result.lon_column,
    }
    circle = {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [circle_ring(clon, clat, RADIUS_KM)]},
        "properties": {"feature_type": "radius", "name": f"{RADIUS_KM:g} km from Sadat",
                       "radius_km": RADIUS_KM},
    }
    gj = {"type": "FeatureCollection", "features": feats + [circle]}
    return gj, summary, result


def geojson_text(gj):
    return json.dumps(gj, ensure_ascii=False, indent=1) + "\n"


def plot_map(ax, gj, label_far=True):
    """Draw the result on a matplotlib axis (lon on x, lat on y, north up)."""
    from matplotlib.lines import Line2D

    stations = [f for f in gj["features"] if f["properties"]["feature_type"] == "station"]
    circle = next(f for f in gj["features"] if f["properties"]["feature_type"] == "radius")
    ring = circle["geometry"]["coordinates"][0]
    ax.plot([p[0] for p in ring], [p[1] for p in ring], color="#444444", lw=1.2, ls="--")
    colours = {label: c for _, label, c in BANDS}
    for f in stations:
        lon, lat = f["geometry"]["coordinates"]
        ax.scatter(lon, lat, s=34, c=colours[f["properties"]["band"]],
                   edgecolors="white", linewidths=0.6, zorder=3)
    centre = next(f for f in stations if f["properties"]["name"] == CENTER_NAME)
    clon, clat = centre["geometry"]["coordinates"]
    ax.scatter(clon, clat, s=170, marker="*", c="#c0392b", edgecolors="black",
               linewidths=0.6, zorder=4)
    ax.annotate("Sadat (Tahrir)", (clon, clat), xytext=(8, 8), textcoords="offset points",
                fontsize=9, weight="bold")
    if label_far:
        far = stations[-1]
        flon, flat = far["geometry"]["coordinates"]
        ax.annotate(f"{far['properties']['name']}\n{far['properties']['dist_to_sadat_km']:.1f} km",
                    (flon, flat), xytext=(-8, 6), textcoords="offset points",
                    fontsize=8, ha="right")
    handles = [Line2D([], [], marker="*", ls="", color="#c0392b", markeredgecolor="black",
                      markersize=12, label="Sadat (centre)")]
    handles += [Line2D([], [], marker="o", ls="", color=c, markeredgecolor="white",
                       markersize=7, label=label) for _, label, c in BANDS]
    handles.append(Line2D([], [], color="#444444", ls="--", label="5 km radius"))
    ax.legend(handles=handles, title="Distance to Sadat", loc="upper left", fontsize=8,
              title_fontsize=9, framealpha=0.95)
    ax.set_aspect(1 / math.cos(math.radians(clat)))  # keep shapes roughly true at this latitude
    ax.set_xlabel("Longitude (degrees E, EPSG:4326)")
    ax.set_ylabel("Latitude (degrees N, EPSG:4326)")
    ax.grid(True, lw=0.3, alpha=0.5)


def write_png(gj, summary, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9.3, 10.4), dpi=150)
    plot_map(ax, gj)
    ax.set_title("Cairo Metro stations by distance to Sadat (Tahrir)\n"
                 f"{summary['within_5km']} of {summary['stations'] - 1} other mapped stations "
                 "within 5 km", fontsize=12)
    ax.text(0.99, 0.01, "North up. Lon/lat axes, x scaled by 1/cos(lat).\n" + CREDIT,
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7,
            bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"})
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cairo Metro stations within 5 km of Sadat</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
 body { margin: 0; font-family: system-ui, sans-serif; }
 header { padding: 10px 16px; }
 h1 { font-size: 1.2rem; margin: 0 0 4px; }
 p { margin: 2px 0; font-size: .9rem; color: #333; }
 #map { height: calc(100vh - 110px); }
</style>
</head>
<body>
<header>
<h1>Cairo Metro stations within 5 km of Sadat</h1>
<p>__LINE1__</p>
<p>__LINE2__ <a href="__REPO__">Source code: csv-to-geojson</a>. Serve over http (e.g. <code>python -m http.server</code>) so the page can load map.geojson.</p>
</header>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var colours = __COLOURS__;
var map = L.map('map');
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);
function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
  });
}
fetch('map.geojson').then(function (r) { return r.json(); }).then(function (data) {
  var layer = L.geoJSON(data, {
    style: function (f) {
      if (f.geometry.type === 'Point') { return {}; }
      return {color: '#444', weight: 2, dashArray: '6 4', fillOpacity: 0.04};
    },
    pointToLayer: function (f, latlng) {
      var c = colours[f.properties.band] || '#888';
      return L.circleMarker(latlng, {radius: f.properties.name === 'Sadat' ? 9 : 6,
        color: '#fff', weight: 1, fillColor: f.properties.name === 'Sadat' ? '#c0392b' : c,
        fillOpacity: 0.95});
    },
    onEachFeature: function (f, l) {
      var rows = Object.keys(f.properties).map(function (k) {
        return '<tr><th align="left">' + esc(k) + '</th><td>' + esc(f.properties[k]) + '</td></tr>';
      }).join('');
      l.bindPopup('<table>' + rows + '</table>');
    }
  }).addTo(map);
  map.fitBounds(layer.getBounds());
});
</script>
</body>
</html>
"""


def write_index(summary, path):
    line1 = (f"{summary['within_5km']} of the {summary['stations'] - 1} other Cairo Metro "
             "station nodes in OpenStreetMap are within 5 km of Sadat (Tahrir) station.")
    line2 = ("Points are coloured by great-circle distance to Sadat; the dashed circle is "
             "5 km. Data: (c) OpenStreetMap contributors (ODbL).")
    text = (INDEX_TEMPLATE
            .replace("__LINE1__", html.escape(line1))
            .replace("__LINE2__", html.escape(line2))
            .replace("__REPO__", REPO_URL)
            .replace("__COLOURS__", json.dumps({label: c for _, label, c in BANDS})))
    Path(path).write_text(text, encoding="utf-8")


def build(data_dir=None, out_dir=None, png=True):
    """Write map.geojson, index.html and (optionally) map.png into out_dir."""
    data_dir = Path(data_dir or HERE / "data")
    out_dir = Path(out_dir or HERE)
    out_dir.mkdir(parents=True, exist_ok=True)
    gj, summary, _ = analyse(data_dir / "cairo_metro_stations.csv")
    (out_dir / "map.geojson").write_text(geojson_text(gj), encoding="utf-8")
    write_index(summary, out_dir / "index.html")
    if png:
        write_png(gj, summary, out_dir / "map.png")
    return gj, summary


def main():
    gj, summary = build()
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
