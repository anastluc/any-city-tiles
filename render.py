import click
import math
import matplotlib
from matplotlib.figure import Figure
from matplotlib.colors import LinearSegmentedColormap, Normalize
import matplotlib.patches as patches
from db import init_db, get_city_bbox, get_shops, get_geo_features, insert_geo_features, get_db_connection
import io
import requests

# Color palettes (using modern matplotlib.colormaps instead of stateful pyplot)
PALETTES = {
    "original": LinearSegmentedColormap.from_list(
        "original",
        ["#f5f0e8", "#e8b35c", "#c85a47", "#6b3d4a"]
    ),
    "hot": matplotlib.colormaps["YlOrRd"],
    "cool": matplotlib.colormaps["YlGnBu"],
    "viridis": matplotlib.colormaps["viridis"],
    "grayscale": matplotlib.colormaps["Greys"],
}

def build_tile_grid(min_lat, max_lat, min_lon, max_lon, tile_km):
    """Generate square tile grid. Returns list of {minLat, maxLat, minLon, maxLon}."""
    delta_lat = tile_km / 111.32
    mid_lat = (min_lat + max_lat) / 2
    delta_lon = tile_km / (111.32 * math.cos(math.radians(mid_lat)))

    tiles = []
    lat = min_lat
    while lat < max_lat:
        lon = min_lon
        while lon < max_lon:
            tiles.append({
                "minLat": lat,
                "maxLat": lat + delta_lat,
                "minLon": lon,
                "maxLon": lon + delta_lon,
            })
            lon += delta_lon
        lat += delta_lat

    return tiles

def count_shops_in_tile(shops, tile):
    """Count shops inside a tile."""
    count = 0
    for shop in shops:
        if (tile["minLat"] <= shop["lat"] < tile["maxLat"] and
            tile["minLon"] <= shop["lon"] < tile["maxLon"]):
            count += 1
    return count

def fetch_water_features(min_lat, max_lat, min_lon, max_lon):
    """Fetch water features (rivers, lakes, canals) from Overpass API. Returns list of coordinates lists."""
    query = f"""[out:json][timeout:60];
(
  way["natural"="water"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["waterway"~"river|canal|stream"]({min_lat},{min_lon},{max_lat},{max_lon});
  relation["natural"="water"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out geom qt;
"""
    try:
        resp = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            headers={"User-Agent": "ShopTiles/1.0 (contact: github.com/user/shoptiles)"},
            timeout=60
        )
        resp.raise_for_status()
        data = resp.json()

        features = []
        for elem in data.get("elements", []):
            if "geometry" in elem:
                coords = [(pt["lon"], pt["lat"]) for pt in elem["geometry"]]
                if len(coords) > 1:
                    features.append(coords)
        return features
    except Exception as e:
        print(f"Warning: Could not fetch water features: {e}")
        return []

def fetch_major_roads(min_lat, max_lat, min_lon, max_lon):
    """Fetch major roads from Overpass API. Returns list of coordinates lists."""
    query = f"""[out:json][timeout:60];
(
  way["highway"~"motorway|trunk|primary|secondary"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out geom qt;
"""
    try:
        resp = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            headers={"User-Agent": "ShopTiles/1.0 (contact: github.com/user/shoptiles)"},
            timeout=60
        )
        resp.raise_for_status()
        data = resp.json()

        features = []
        for elem in data.get("elements", []):
            if "geometry" in elem:
                coords = [(pt["lon"], pt["lat"]) for pt in elem["geometry"]]
                if len(coords) > 1:
                    features.append(coords)
        return features
    except Exception as e:
        print(f"Warning: Could not fetch roads: {e}")
        return []

def render_map(city, shop_type, tag, chain=None, tile_size=1.0, palette="original", marker_color="#5b8fd4", title=None, show_roads=False):
    """Render the choropleth map with geographic underlay and correct aspect ratio. Returns SVG string."""
    init_db()

    # Input validation
    if tile_size <= 0:
        raise ValueError("Tile size must be greater than 0.")

    # Fetch city bbox
    bbox = get_city_bbox(city)
    if not bbox:
        raise ValueError(f"City '{city}' not found in DB. Run fetch_data.py first.")

    min_lat, max_lat = bbox["min_lat"], bbox["max_lat"]
    min_lon, max_lon = bbox["min_lon"], bbox["max_lon"]

    # Fetch shops
    query_tag = f"{tag}:{shop_type}"
    background_shops = get_shops(city, query_tag)
    if not background_shops:
        raise ValueError(f"No shops found for {query_tag} in {city}. Run fetch_data.py first.")

    chain_shops = []
    if chain:
        chain_shops = get_shops(city, f"name:{chain}")

    # Build tile grid and compute density
    tiles = build_tile_grid(min_lat, max_lat, min_lon, max_lon, tile_size)

    max_density = 0
    for tile in tiles:
        count = count_shops_in_tile(background_shops, tile)
        tile["density"] = count / (tile_size * tile_size) if count > 0 else 0
        max_density = max(max_density, tile["density"])

    # 1. Fetch geographic features (Check cache first)
    print("Checking database for cached water features...")
    water_features = get_geo_features(city, "water")
    if water_features is None:
        print("  Water features not cached. Fetching live from Overpass...")
        water_features = fetch_water_features(min_lat, max_lat, min_lon, max_lon)
        # Store in DB cache if city ID exists
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM cities WHERE name = ?", (city,))
            row = cursor.fetchone()
            if row:
                insert_geo_features(row[0], "water", water_features)
                print("  Stored water features in DB cache.")
        finally:
            conn.close()
    else:
        print(f"  Loaded {len(water_features)} water features from DB cache.")

    roads_features = []
    if show_roads:
        print("Checking database for cached road features...")
        roads_features = get_geo_features(city, "road")
        if roads_features is None:
            print("  Road features not cached. Fetching live from Overpass...")
            roads_features = fetch_major_roads(min_lat, max_lat, min_lon, max_lon)
            # Store in DB cache
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM cities WHERE name = ?", (city,))
                row = cursor.fetchone()
                if row:
                    insert_geo_features(row[0], "road", roads_features)
                    print("  Stored road features in DB cache.")
            finally:
                conn.close()
        else:
            print(f"  Loaded {len(roads_features)} road features from DB cache.")

    # 2. Project geographic coordinates correctly using Equirectangular projection
    mid_lat = (min_lat + max_lat) / 2
    cos_lat = math.cos(math.radians(mid_lat))

    def project(lat, lon):
        """Project lat/lon using Equirectangular projection to preserve aspect ratio."""
        x = (lon - min_lon) * cos_lat
        y = lat - min_lat
        return x, y

    # Compute bounds in projected space
    max_x = (max_lon - min_lon) * cos_lat
    max_y = max_lat - min_lat

    # 3. Create figure using the thread-safe object-oriented Matplotlib API
    fig = Figure(figsize=(8, 10), dpi=100)
    ax = fig.subplots()
    ax.set_facecolor("#e8dcc8")  # Warmer background for map feel
    fig.patch.set_facecolor("white")

    # Normalize density for coloring
    norm = Normalize(vmin=0, vmax=max_density if max_density > 0 else 1)
    cmap = PALETTES.get(palette, PALETTES["original"])

    # Draw water features (background, light blue)
    for feature in water_features:
        # feature contains (lon, lat) pairs
        coords = [project(lat, lon) for lon, lat in feature]
        if len(coords) > 1:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            ax.fill(xs, ys, color="#c5dff8", edgecolor="#8ab4f8", linewidth=0.5, alpha=0.6, zorder=5)

    # Draw major roads (background, light gray)
    if roads_features:
        for feature in roads_features:
            coords = [project(lat, lon) for lon, lat in feature]
            if len(coords) > 1:
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                ax.plot(xs, ys, color="#d0d0d0", linewidth=1.2, alpha=0.7, zorder=10)

    # Draw tiles (main choropleth layer) - now guaranteed to be square!
    for tile in tiles:
        x_min, y_min = project(tile["minLat"], tile["minLon"])
        x_max, y_max = project(tile["maxLat"], tile["maxLon"])
        color = cmap(norm(tile["density"]))

        # Rectangles are drawn from (x_min, y_min) with width & height
        rect = patches.Rectangle(
            (x_min, y_min),
            x_max - x_min, y_max - y_min,
            linewidth=0, facecolor=color, alpha=0.85, zorder=20
        )
        ax.add_patch(rect)

    # Draw chain markers on top of tiles
    if chain_shops:
        chain_lons = [s["lon"] for s in chain_shops]
        chain_lats = [s["lat"] for s in chain_shops]
        chain_coords = [project(lat, lon) for lat, lon in zip(chain_lats, chain_lons)]
        chain_x = [c[0] for c in chain_coords]
        chain_y = [c[1] for c in chain_coords]
        ax.scatter(chain_x, chain_y, s=60, c=marker_color, edgecolor="white", linewidth=1, zorder=100)

    # Set exact limits in projected space
    ax.set_xlim(0, max_x)
    ax.set_ylim(0, max_y)
    ax.set_aspect("equal")
    ax.axis("off")

    # Add title if specified
    if title:
        ax.text(0.5, 0.98, title, ha="center", va="top", fontsize=16, fontweight="bold", transform=ax.transAxes)

    # Add legend
    sm = matplotlib.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation="horizontal", pad=0.05, shrink=0.6, aspect=30)
    cbar.set_label("Shops per km²", fontsize=10)

    # Render to SVG string
    buf = io.BytesIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", dpi=100)
    buf.seek(0)
    svg_string = buf.read().decode("utf-8")

    return svg_string

@click.command()
@click.option("--city", required=True, help="City name")
@click.option("--shop-type", required=True, help="Shop type")
@click.option("--tag", type=click.Choice(["amenity", "shop"]), required=True, help="OSM tag type")
@click.option("--chain", default=None, help="Chain name")
@click.option("--tile-size", type=float, default=1.0, help="Tile size in km")
@click.option("--palette", type=click.Choice(list(PALETTES.keys())), default="original", help="Color palette")
@click.option("--marker-color", default="#5b8fd4", help="Hex color for markers")
@click.option("--title", default=None, help="Map title")
@click.option("--show-roads", is_flag=True, help="Include major roads on the map")
@click.option("--output", type=click.Path(), required=True, help="Output SVG file path")
def main(city, shop_type, tag, chain, tile_size, palette, marker_color, title, show_roads, output):
    """Render choropleth map and save to SVG."""
    try:
        svg = render_map(city, shop_type, tag, chain, tile_size, palette, marker_color, title, show_roads)
        with open(output, "w") as f:
            f.write(svg)
        click.echo(f"Map saved to {output}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise

if __name__ == "__main__":
    main()
