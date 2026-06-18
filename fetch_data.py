import click
import requests
from db import init_db, get_or_create_city, insert_shops, get_city_bbox

NOMINATIM_API = "https://nominatim.openstreetmap.org/search"
OVERPASS_API = "https://overpass-api.de/api/interpreter"

def fetch_city_bbox(city_name):
    """Fetch city bounding box from Nominatim with size limit validation. Returns bbox metadata."""
    resp = requests.get(
        NOMINATIM_API,
        params={"format": "json", "limit": 1, "q": city_name},
        headers={"User-Agent": "ShopTiles/1.0 (contact: github.com/user/shoptiles)"},
        timeout=15
    )
    resp.raise_for_status()

    results = resp.json()
    if not results:
        raise ValueError(f"City '{city_name}' not found in OpenStreetMap. Please check spelling or try a more specific query.")

    place = results[0]
    bbox = [float(x) for x in place["boundingbox"]]  # [minLat, maxLat, minLon, maxLon]

    # Bounding box limits validation to prevent server timeout/crashes
    lat_diff = abs(bbox[1] - bbox[0])
    lon_diff = abs(bbox[3] - bbox[2])
    if lat_diff > 1.5 or lon_diff > 1.5:
        raise ValueError(
            f"The geographic bounding box for '{city_name}' is too large ({lat_diff:.2f}° x {lon_diff:.2f}°). "
            f"Please specify a smaller region or city name to avoid API timeouts and service restrictions."
        )

    return {
        "osm_id": place["osm_id"],
        "osm_type": place["osm_type"],
        "min_lat": bbox[0],
        "max_lat": bbox[1],
        "min_lon": bbox[2],
        "max_lon": bbox[3],
    }

def fetch_shops_overpass(city_name, query_tag, tag_type, chain_name=None):
    """Fetch shops from Overpass API. Returns list of shops and bbox metadata."""
    # Get city bbox first (may be cached in DB)
    bbox_info = get_city_bbox(city_name)
    if not bbox_info:
        bbox_info = fetch_city_bbox(city_name)

    osm_id = bbox_info["osm_id"]
    osm_type = bbox_info["osm_type"]
    min_lat, max_lat, min_lon, max_lon = bbox_info["min_lat"], bbox_info["max_lat"], bbox_info["min_lon"], bbox_info["max_lon"]

    # Sanitize user inputs to prevent Overpass QL quote injection/corruption
    sanitized_tag = query_tag.replace('"', '\\"')
    sanitized_type = tag_type.replace('"', '\\"')

    # Build query
    if osm_type == "relation":
        try:
            area_id = 3600000000 + int(osm_id)
        except ValueError:
            # Fallback if osm_id is not integer (e.g. invalid cached state)
            area_id = None

    if osm_type == "relation" and area_id is not None:
        query = f"""[out:json][timeout:120];
area({area_id})->.city;
(
  node["{sanitized_type}"="{sanitized_tag}"](area.city);
  way["{sanitized_type}"="{sanitized_tag}"](area.city);
  relation["{sanitized_type}"="{sanitized_tag}"](area.city);
);
out center qt;
"""
    else:
        # Fallback to bbox query for non-relations
        query = f"""[out:json][timeout:120];
(
  node["{sanitized_type}"="{sanitized_tag}"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["{sanitized_type}"="{sanitized_tag}"]({min_lat},{min_lon},{max_lat},{max_lon});
  relation["{sanitized_type}"="{sanitized_tag}"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out center qt;
"""

    resp = requests.post(
        OVERPASS_API,
        data={"data": query},
        headers={"User-Agent": "ShopTiles/1.0 (contact: github.com/user/shoptiles)"},
        timeout=120
    )
    resp.raise_for_status()

    data = resp.json()
    shops = []

    for elem in data.get("elements", []):
        lat = elem.get("lat") or (elem.get("center", {}).get("lat") if elem.get("center") else None)
        lon = elem.get("lon") or (elem.get("center", {}).get("lon") if elem.get("center") else None)

        if lat is not None and lon is not None:
            shops.append({
                "osm_id": str(elem.get("id", "")),
                "osm_type": elem.get("type", ""),
                "lat": lat,
                "lon": lon,
                "name": elem.get("tags", {}).get("name", ""),
                "query_tag": f"{tag_type}:{query_tag}",
            })

    return shops, bbox_info

@click.command()
@click.option("--city", required=True, help="City name (e.g. Berlin)")
@click.option("--shop-type", required=True, help="Shop type tag value (e.g. cafe, boulangerie)")
@click.option("--tag", type=click.Choice(["amenity", "shop"]), required=True, help="OSM tag type")
@click.option("--chain", default=None, help="Chain name to fetch (e.g. 'LAP Coffee')")
def main(city, shop_type, tag, chain):
    """Fetch shop data from OSM and cache in SQLite."""
    init_db()

    click.echo(f"Fetching {tag}={shop_type} for {city}...")

    try:
        # Fetch background shops
        shops, bbox_info = fetch_shops_overpass(city, shop_type, tag)
        click.echo(f"  Found {len(shops)} {shop_type} shops")

        # Store city
        city_id = get_or_create_city(
            city, bbox_info["osm_id"], bbox_info["osm_type"],
            bbox_info["min_lat"], bbox_info["max_lat"],
            bbox_info["min_lon"], bbox_info["max_lon"]
        )

        # Insert shops
        insert_shops(city_id, shops)
        click.echo(f"  Stored {len(shops)} shops in DB")

        # Fetch chain if specified
        if chain:
            click.echo(f"Fetching chain: {chain}...")
            chain_shops, _ = fetch_shops_overpass(city, chain, "name")
            click.echo(f"  Found {len(chain_shops)} {chain} locations")
            insert_shops(city_id, chain_shops)
            click.echo(f"  Stored {len(chain_shops)} chain locations in DB")

        click.echo("Done!")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise

if __name__ == "__main__":
    main()
