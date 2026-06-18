"""Generate test data for development."""
import sqlite3
from db import init_db, get_or_create_city, insert_shops
import random

DB_PATH = "shops.db"

def generate_test_data():
    """Create test dataset for Berlin with cafes and LAP Coffee."""
    init_db()

    # Berlin bounds (approximate)
    berlin_bbox = {
        "min_lat": 52.34,
        "max_lat": 52.67,
        "min_lon": 13.09,
        "max_lon": 13.76,
        "osm_id": "62422",
        "osm_type": "relation",
    }

    # Create city
    city_id = get_or_create_city(
        "Berlin",
        berlin_bbox["osm_id"],
        berlin_bbox["osm_type"],
        berlin_bbox["min_lat"],
        berlin_bbox["max_lat"],
        berlin_bbox["min_lon"],
        berlin_bbox["max_lon"],
    )

    # Generate random cafes across Berlin (higher density in Mitte and Prenzlauer Berg)
    cafes = []

    # Dense cluster in Mitte (central)
    mitte_lat = 52.52
    mitte_lon = 13.40
    for _ in range(400):
        cafes.append({
            "osm_id": f"cafe_{len(cafes)}",
            "osm_type": "node",
            "lat": mitte_lat + random.gauss(0, 0.05),
            "lon": mitte_lon + random.gauss(0, 0.05),
            "name": f"Cafe {len(cafes)}",
            "query_tag": "amenity:cafe",
        })

    # Dense cluster in Prenzlauer Berg (northeast)
    pb_lat = 52.55
    pb_lon = 13.41
    for _ in range(350):
        cafes.append({
            "osm_id": f"cafe_{len(cafes)}",
            "osm_type": "node",
            "lat": pb_lat + random.gauss(0, 0.04),
            "lon": pb_lon + random.gauss(0, 0.04),
            "name": f"Cafe {len(cafes)}",
            "query_tag": "amenity:cafe",
        })

    # Medium cluster in Kreuzberg (south-central)
    kb_lat = 52.50
    kb_lon = 13.37
    for _ in range(280):
        cafes.append({
            "osm_id": f"cafe_{len(cafes)}",
            "osm_type": "node",
            "lat": kb_lat + random.gauss(0, 0.04),
            "lon": kb_lon + random.gauss(0, 0.04),
            "name": f"Cafe {len(cafes)}",
            "query_tag": "amenity:cafe",
        })

    # Scattered cafes across rest of Berlin
    for _ in range(800):
        cafes.append({
            "osm_id": f"cafe_{len(cafes)}",
            "osm_type": "node",
            "lat": random.uniform(berlin_bbox["min_lat"], berlin_bbox["max_lat"]),
            "lon": random.uniform(berlin_bbox["min_lon"], berlin_bbox["max_lon"]),
            "name": f"Cafe {len(cafes)}",
            "query_tag": "amenity:cafe",
        })

    insert_shops(city_id, cafes)
    print(f"Inserted {len(cafes)} test cafes")

    # LAP Coffee locations (concentrated in Mitte, Prenzlauer Berg)
    lap_shops = []
    for i in range(12):
        if i < 6:
            # Mitte cluster
            lap_shops.append({
                "osm_id": f"lap_{i}",
                "osm_type": "node",
                "lat": 52.52 + random.gauss(0, 0.02),
                "lon": 13.40 + random.gauss(0, 0.02),
                "name": "LAP Coffee",
                "query_tag": "name:LAP Coffee",
            })
        else:
            # Prenzlauer Berg cluster
            lap_shops.append({
                "osm_id": f"lap_{i}",
                "osm_type": "node",
                "lat": 52.55 + random.gauss(0, 0.02),
                "lon": 13.41 + random.gauss(0, 0.02),
                "name": "LAP Coffee",
                "query_tag": "name:LAP Coffee",
            })

    insert_shops(city_id, lap_shops)
    print(f"Inserted {len(lap_shops)} LAP Coffee locations")

if __name__ == "__main__":
    generate_test_data()
    print("Test data ready!")
