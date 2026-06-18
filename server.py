import json
from flask import Flask, render_template, request, jsonify
from db import init_db, list_cities, list_tags, get_db_stats
from fetch_data import fetch_shops_overpass, fetch_city_bbox
from db import get_or_create_city, insert_shops, get_city_bbox
from render import render_map

app = Flask(__name__, template_folder="templates")
init_db()

@app.route("/")
def index():
    """Serve the main UI."""
    return render_template("index.html")

@app.route("/api/cities")
def api_cities():
    """List cities in the database."""
    init_db()
    cities = list_cities()
    return jsonify({"cities": cities})

@app.route("/api/tags")
def api_tags():
    """List tags for a city."""
    init_db()
    city = request.args.get("city")
    if not city:
        return jsonify({"error": "city parameter required"}), 400

    tags = list_tags(city)
    return jsonify({"tags": tags})

@app.route("/api/stats")
def api_stats():
    """Return database stats for the dashboard."""
    init_db()
    try:
        stats = get_db_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    """Fetch shop data from OSM and cache in DB."""
    init_db()

    data = request.get_json() or {}
    city = data.get("city")
    shop_type = data.get("shop_type")
    tag = data.get("tag", "amenity")
    chain = data.get("chain")

    if not city or not shop_type:
        return jsonify({"error": "city and shop_type parameters are required"}), 400

    try:
        # Fetch background shops
        shops, bbox_info = fetch_shops_overpass(city, shop_type, tag)

        # Store city metadata
        city_id = get_or_create_city(
            city, bbox_info["osm_id"], bbox_info["osm_type"],
            bbox_info["min_lat"], bbox_info["max_lat"],
            bbox_info["min_lon"], bbox_info["max_lon"]
        )

        # Insert shops into cache
        insert_shops(city_id, shops)

        chain_count = 0
        if chain:
            chain_shops, _ = fetch_shops_overpass(city, chain, "name")
            insert_shops(city_id, chain_shops)
            chain_count = len(chain_shops)

        return jsonify({
            "status": "success",
            "background_count": len(shops),
            "chain_count": chain_count,
            "message": f"Fetched {len(shops)} background shops" + (f" and {chain_count} {chain} locations" if chain else "")
        })

    except ValueError as ve:
        # Handled validation or custom OSM errors (e.g. city not found, bbox too large)
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to fetch data: {str(e)}"}), 500

@app.route("/api/render", methods=["POST"])
def api_render():
    """Render choropleth map and return SVG."""
    init_db()

    data = request.get_json() or {}
    city = data.get("city")
    shop_type = data.get("shop_type")
    tag = data.get("tag", "amenity")
    chain = data.get("chain")
    palette = data.get("palette", "original")
    marker_color = data.get("marker_color", "#5b8fd4")
    title = data.get("title")
    show_roads = data.get("show_roads", False)

    if not city or not shop_type:
        return jsonify({"error": "city and shop_type required"}), 400

    # Validate tile_size input range
    try:
        tile_size = float(data.get("tile_size", 1.0))
        if tile_size <= 0:
            return jsonify({"error": "Tile size must be greater than 0"}), 400
        if tile_size > 10.0:
            return jsonify({"error": "Tile size must not exceed 10.0 km"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Tile size must be a valid decimal number"}), 400

    # If title is empty, generate default title
    if not title:
        title = f"{shop_type.capitalize()} in {city}"

    try:
        svg = render_map(city, shop_type, tag, chain, tile_size, palette, marker_color, title, show_roads)
        return jsonify({
            "status": "success",
            "svg": svg
        })
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to render map: {str(e)}"}), 500

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
