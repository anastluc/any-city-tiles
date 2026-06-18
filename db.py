import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "shops.db"

def get_db_connection():
    """Create a thread-safe connection with foreign keys and WAL mode enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    # Enable SQLite features
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def init_db():
    """Initialize database schema."""
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            
            # Cities table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    osm_id TEXT,
                    osm_type TEXT,
                    min_lat REAL, max_lat REAL,
                    min_lon REAL, max_lon REAL,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Shops table with cascade delete on city_id
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city_id INTEGER REFERENCES cities(id) ON DELETE CASCADE,
                    osm_id TEXT,
                    osm_type TEXT,
                    name TEXT,
                    query_tag TEXT,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Geo features cache table (waterways, lakes, roads, etc.)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS geo_features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city_id INTEGER REFERENCES cities(id) ON DELETE CASCADE,
                    feature_type TEXT NOT NULL, -- 'water' or 'road'
                    geometry TEXT NOT NULL,     -- JSON encoded list of [lon, lat] coordinate pairs
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indices for quick lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_shops_city_tag ON shops(city_id, query_tag)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_geo_features_city_type ON geo_features(city_id, feature_type)
            """)
    finally:
        conn.close()

def get_or_create_city(name, osm_id, osm_type, min_lat, max_lat, min_lon, max_lon):
    """Get or create a city record. Returns city_id."""
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM cities WHERE name = ?", (name,))
            row = cursor.fetchone()

            if row:
                city_id = row[0]
            else:
                cursor.execute("""
                    INSERT INTO cities (name, osm_id, osm_type, min_lat, max_lat, min_lon, max_lon, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, osm_id, osm_type, min_lat, max_lat, min_lon, max_lon, datetime.now()))
                city_id = cursor.lastrowid
            return city_id
    finally:
        conn.close()

def get_city_bbox(city_name):
    """Fetch city bbox from DB. Returns {min_lat, max_lat, min_lon, max_lon, osm_id, osm_type} or None."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT min_lat, max_lat, min_lon, max_lon, osm_id, osm_type FROM cities WHERE name = ?",
            (city_name,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "min_lat": row[0], "max_lat": row[1],
                "min_lon": row[2], "max_lon": row[3],
                "osm_id": row[4], "osm_type": row[5]
            }
        return None
    finally:
        conn.close()

def insert_shops(city_id, shops_list):
    """Insert shops for a city. Overwrites existing entries for the same query_tag."""
    if not shops_list:
        return 0

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            # Get all query tags from this batch
            tags = set(s["query_tag"] for s in shops_list)

            # Delete existing shops for these tags
            for tag in tags:
                cursor.execute(
                    "DELETE FROM shops WHERE city_id = ? AND query_tag = ?",
                    (city_id, tag)
                )

            # Insert new shops
            for shop in shops_list:
                cursor.execute("""
                    INSERT INTO shops (city_id, osm_id, osm_type, name, query_tag, lat, lon, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    city_id,
                    shop.get("osm_id"),
                    shop.get("osm_type"),
                    shop.get("name"),
                    shop["query_tag"],
                    shop["lat"],
                    shop["lon"],
                    datetime.now()
                ))
            return len(shops_list)
    finally:
        conn.close()

def get_shops(city_name, query_tag):
    """Fetch shops for a city with specific query_tag. Returns list of {lat, lon, name}."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.lat, s.lon, s.name FROM shops s
            JOIN cities c ON s.city_id = c.id
            WHERE c.name = ? AND s.query_tag = ?
        """, (city_name, query_tag))

        rows = cursor.fetchall()
        return [{"lat": row[0], "lon": row[1], "name": row[2]} for row in rows]
    finally:
        conn.close()

def insert_geo_features(city_id, feature_type, features_list):
    """Insert geographic features (water, roads) for a city. Overwrites existing entries."""
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            
            # Delete existing features of this type for this city
            cursor.execute(
                "DELETE FROM geo_features WHERE city_id = ? AND feature_type = ?",
                (city_id, feature_type)
            )
            
            # Insert each feature as JSON string
            for feature in features_list:
                cursor.execute("""
                    INSERT INTO geo_features (city_id, feature_type, geometry, fetched_at)
                    VALUES (?, ?, ?, ?)
                """, (city_id, feature_type, json.dumps(feature), datetime.now()))
                
            return len(features_list)
    finally:
        conn.close()

def get_geo_features(city_name, feature_type):
    """Fetch cached geo features for a city. Returns list of lists of (lon, lat) tuples, or None if not cached."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Check if the city exists
        cursor.execute("SELECT id FROM cities WHERE name = ?", (city_name,))
        city_row = cursor.fetchone()
        if not city_row:
            return None
            
        city_id = city_row[0]
        
        # Check if we have features cached (even an empty list counts as cached if city exists)
        cursor.execute(
            "SELECT count(*) FROM geo_features WHERE city_id = ? AND feature_type = ?",
            (city_id, feature_type)
        )
        count = cursor.fetchone()[0]
        
        # If no features exist, but the city itself has been queried before, we check if we've cached this type
        # For simplicity, if count is 0, we return None to trigger fetch unless we know it's already fetched
        # Let's check the fetched_at timestamp for this type to see if we ever fetched it.
        cursor.execute(
            "SELECT geometry FROM geo_features WHERE city_id = ? AND feature_type = ?",
            (city_id, feature_type)
        )
        rows = cursor.fetchall()
        
        # If we have rows, parse JSON
        if rows:
            return [json.loads(row[0]) for row in rows]
            
        # We need a way to distinguish "not cached" from "cached but empty".
        # Let's check if the city has a record in cities, but no geo_features.
        # We will return None if never fetched. How to know if we fetched but it returned 0?
        # We can check a metadata or just treat count > 0 as cached.
        # If count == 0, we return None (which triggers Overpass query).
        # This is safe and robust.
        if count == 0:
            # Let's double check if we have a special entry or if we just fetch.
            # Returning None if 0 features are found will cause it to query Overpass,
            # which is fine because cities usually have water features, and if not, a query is fast or we cache an empty placeholder.
            # Let's allow returning an empty list if we can verify it was fetched.
            # To do that, we can insert a single placeholder feature when we fetch and get 0 features.
            # Or we can just return None. Let's return None if empty, which is a sensible fallback.
            return None
            
        return []
    finally:
        conn.close()

def get_db_stats():
    """Retrieve database stats (city name, shop types, geo features count)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Fetch cities
        cursor.execute("SELECT id, name, fetched_at FROM cities ORDER BY name")
        cities = cursor.fetchall()
        
        stats = {}
        for city_id, city_name, fetched_at in cities:
            # Shop tags
            cursor.execute(
                "SELECT query_tag, count(*) FROM shops WHERE city_id = ? GROUP BY query_tag",
                (city_id,)
            )
            tags = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Geo features
            cursor.execute(
                "SELECT feature_type, count(*) FROM geo_features WHERE city_id = ? GROUP BY feature_type",
                (city_id,)
            )
            geo = {row[0]: row[1] for row in cursor.fetchall()}
            
            stats[city_name] = {
                "fetched_at": fetched_at,
                "shops": tags,
                "geo_features": geo
            }
        return stats
    finally:
        conn.close()

def list_cities():
    """List all cities in the DB."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT name FROM cities ORDER BY name")
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()

def list_tags(city_name):
    """List all query_tags fetched for a city."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT s.query_tag FROM shops s
            JOIN cities c ON s.city_id = c.id
            WHERE c.name = ?
            ORDER BY s.query_tag
        """, (city_name,))
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
