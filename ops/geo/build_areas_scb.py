"""
Bygger taxitips-backend/core/data/se_counties.geojson och se_municipalities.geojson:
Sveriges 21 län och 290 kommuner som polygoner i WGS84, med SCB:s koder.

Källa: SCB, "Digitala gränser" (län och kommuner, SWEREF 99 TM), version 2026-02-25.
Licens CC0 enligt SCB. Hämtad från
https://www.scb.se/contentassets/3443fea3fa6640f7a57ea15d9a372d33/shape_svenska_260225.zip
SCB beskriver gränserna som förenklade för tematisk presentation, inte för analys. Det
räcker för att välja körområde och placera ett tips; core/areas.py lägger en buffert
runt länen och kommunerna.

Inga beroenden: shapefil och DBF läses direkt, och SWEREF 99 TM räknas om till WGS84 med
Lantmäteriets formler för Gauss–Krügers projektion (GRS 80, medelmeridian 15°,
skalfaktor 0,9996, falsk östlig 500 000 m).

    curl -sSfLo /tmp/scb.zip <url ovan>
    unzip /tmp/scb.zip -d /tmp/scb
    unzip /tmp/scb/Kommun_Sweref99TM.zip -d /tmp/scb/kommun
    unzip /tmp/scb/LanSweref99TM.zip -d /tmp/scb/lan
    python3 ops/geo/build_areas_scb.py /tmp/scb/lan/Lan_Sweref99TM_region /tmp/scb/kommun/Kommun_Sweref99TM
"""

from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "taxitips-backend" / "core" / "data"

# --- SWEREF 99 TM -> WGS84 (Lantmäteriet, Gauss–Krüger) ------------------------------
A = 6378137.0
F = 1 / 298.257222101
LAMBDA0 = math.radians(15.0)
K0 = 0.9996
FALSE_NORTHING = 0.0
FALSE_EASTING = 500000.0

_E2 = F * (2 - F)
_N = F / (2 - F)
_A_ROOF = A / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64)
_DELTA = (
    _N / 2 - 2 * _N**2 / 3 + 37 * _N**3 / 96 - _N**4 / 360,
    _N**2 / 48 + _N**3 / 15 - 437 * _N**4 / 1440,
    17 * _N**3 / 480 - 37 * _N**4 / 840,
    4397 * _N**4 / 161280,
)
_A_STAR = _E2 + _E2**2 + _E2**3 + _E2**4
_B_STAR = -(7 * _E2**2 + 17 * _E2**3 + 30 * _E2**4) / 6
_C_STAR = (224 * _E2**3 + 889 * _E2**4) / 120
_D_STAR = -(4279 * _E2**4) / 1260


def sweref99tm_to_wgs84(northing: float, easting: float) -> tuple[float, float]:
    """(lat, lon) i grader."""
    xi = (northing - FALSE_NORTHING) / (K0 * _A_ROOF)
    eta = (easting - FALSE_EASTING) / (K0 * _A_ROOF)
    xi_prim, eta_prim = xi, eta
    for k, delta in enumerate(_DELTA, start=1):
        xi_prim -= delta * math.sin(2 * k * xi) * math.cosh(2 * k * eta)
        eta_prim -= delta * math.cos(2 * k * xi) * math.sinh(2 * k * eta)
    phi_star = math.asin(math.sin(xi_prim) / math.cosh(eta_prim))
    delta_lambda = math.atan(math.sinh(eta_prim) / math.cos(xi_prim))
    s = math.sin(phi_star)
    lat = phi_star + s * math.cos(phi_star) * (_A_STAR + _B_STAR * s**2 + _C_STAR * s**4 + _D_STAR * s**6)
    return math.degrees(lat), math.degrees(LAMBDA0 + delta_lambda)


# --- shapefil och DBF ----------------------------------------------------------------


def read_dbf(path: Path) -> list[dict]:
    data = path.read_bytes()
    count, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields, offset = [], 32
    while data[offset] != 0x0D:
        name = data[offset:offset + 11].split(b"\x00")[0].decode("latin-1")
        fields.append((name, data[offset + 16]))
        offset += 32
    rows = []
    for i in range(count):
        record = data[header_len + i * record_len: header_len + (i + 1) * record_len]
        pos, row = 1, {}
        for name, size in fields:
            row[name] = record[pos:pos + size].decode("latin-1").strip()
            pos += size
        rows.append(row)
    return rows


def read_polygons(path: Path) -> list[list[list[tuple[float, float]]]]:
    """En lista ringar (i SWEREF 99 TM: (easting, northing)) per post."""
    data = path.read_bytes()
    offset, shapes = 100, []
    while offset < len(data):
        _number, length_words = struct.unpack(">ii", data[offset:offset + 8])
        content = data[offset + 8: offset + 8 + length_words * 2]
        offset += 8 + length_words * 2
        shape_type = struct.unpack("<i", content[:4])[0]
        if shape_type == 0:
            shapes.append([])
            continue
        if shape_type != 5:
            raise SystemExit(f"oväntad shapetyp {shape_type}")
        num_parts, num_points = struct.unpack("<ii", content[36:44])
        parts = list(struct.unpack(f"<{num_parts}i", content[44:44 + 4 * num_parts]))
        points_at = 44 + 4 * num_parts
        coords = struct.unpack(f"<{2 * num_points}d", content[points_at:points_at + 16 * num_points])
        points = [(coords[2 * i], coords[2 * i + 1]) for i in range(num_points)]
        rings = [points[start:end] for start, end in zip(parts, parts[1:] + [num_points])]
        shapes.append(rings)
    return shapes


def _signed_area(ring) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])) / 2


def _inside(point, ring) -> bool:
    x, y = point
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def to_multipolygon(rings) -> list:
    """Shapefilens ringar -> GeoJSON MultiPolygon. Medurs = yttre ring, moturs = hål."""
    outers = [r for r in rings if _signed_area(r) < 0]
    holes = [r for r in rings if _signed_area(r) >= 0]
    polygons = [[outer] for outer in outers]
    for hole in holes:
        owner = next((p for p in polygons if _inside(hole[0], p[0])), None)
        if owner is not None:
            owner.append(hole)
    return [
        [[[round(lon, 5), round(lat, 5)] for lat, lon in (sweref99tm_to_wgs84(n, e) for e, n in ring)] for ring in polygon]
        for polygon in polygons
    ]


def build(stem: Path, code_field: str, name_field: str, extra=None) -> list[dict]:
    rows = read_dbf(stem.with_suffix(".dbf"))
    shapes = read_polygons(stem.with_suffix(".shp"))
    if len(rows) != len(shapes):
        raise SystemExit(f"{stem}: {len(rows)} poster men {len(shapes)} former")
    features = []
    for row, rings in zip(rows, shapes):
        props = {"code": row[code_field], "name": row[name_field]}
        if extra:
            props.update(extra(row))
        features.append({"type": "Feature", "properties": props,
                         "geometry": {"type": "MultiPolygon", "coordinates": to_multipolygon(rings)}})
    return sorted(features, key=lambda f: f["properties"]["code"])


def write(name: str, features: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "source": "SCB Digitala gränser 2026-02-25 (CC0), se ops/geo/build_areas_scb.py",
        "features": features,
    }, separators=(",", ":"), ensure_ascii=False))
    points = sum(len(ring) for f in features for poly in f["geometry"]["coordinates"] for ring in poly)
    print(f"skrev {path.name}: {len(features)} områden, {points} punkter, {path.stat().st_size // 1024} kB")


def main(county_stem: str, municipality_stem: str) -> None:
    counties = build(Path(county_stem), "LnKod", "LnNamn")
    municipalities = build(Path(municipality_stem), "KnKod", "KnNamn", extra=lambda row: {"county": row["KnKod"][:2]})
    if len(counties) != 21 or len(municipalities) != 290:
        raise SystemExit(f"förväntade 21 län och 290 kommuner, fick {len(counties)} och {len(municipalities)}")
    write("se_counties.geojson", counties)
    write("se_municipalities.geojson", municipalities)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
