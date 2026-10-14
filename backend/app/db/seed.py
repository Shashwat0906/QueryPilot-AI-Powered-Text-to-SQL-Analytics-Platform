"""Create and populate the sample business database.

The data is generated with a fixed random seed, so every run produces exactly
the same rows. That reproducibility matters: the evaluation suite compares
LLM answers against expected results computed from this data.

This is the ONLY code that writes to the business database, and it does so
through its own short-lived writable connection - the application itself only
ever opens the file read-only.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    first_name    TEXT    NOT NULL,
    last_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    city          TEXT    NOT NULL,
    state         TEXT    NOT NULL,
    country       TEXT    NOT NULL,
    segment       TEXT    NOT NULL CHECK (segment IN ('Consumer', 'Small Business', 'Enterprise')),
    signup_date   DATE    NOT NULL
);

CREATE TABLE products (
    product_id     INTEGER PRIMARY KEY,
    name           TEXT    NOT NULL UNIQUE,
    category       TEXT    NOT NULL,
    unit_price     NUMERIC(10, 2) NOT NULL CHECK (unit_price > 0),
    unit_cost      NUMERIC(10, 2) NOT NULL CHECK (unit_cost > 0),
    stock_quantity INTEGER NOT NULL CHECK (stock_quantity >= 0),
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at     DATE    NOT NULL
);

CREATE TABLE orders (
    order_id       INTEGER PRIMARY KEY,
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date     DATE    NOT NULL,
    status         TEXT    NOT NULL CHECK (status IN ('pending', 'shipped', 'completed', 'cancelled', 'refunded')),
    payment_method TEXT    NOT NULL CHECK (payment_method IN ('card', 'upi', 'paypal', 'bank_transfer')),
    shipping_fee   NUMERIC(10, 2) NOT NULL DEFAULT 0
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    unit_price    NUMERIC(10, 2) NOT NULL CHECK (unit_price > 0),
    discount      NUMERIC(4, 2)  NOT NULL DEFAULT 0 CHECK (discount >= 0 AND discount < 1)
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
"""

# (name, category, price, cost, is_active)
PRODUCTS: list[tuple[str, str, float, float, int]] = [
    ("Aurora Wireless Earbuds", "Electronics", 79.99, 38.00, 1),
    ("Nimbus Bluetooth Speaker", "Electronics", 129.00, 61.50, 1),
    ("Pulse Fitness Tracker", "Electronics", 99.50, 44.00, 1),
    ("Vertex 27\" 4K Monitor", "Electronics", 349.00, 228.00, 1),
    ("Orbit USB-C Hub", "Electronics", 45.00, 17.25, 1),
    ("Lumen Mechanical Keyboard", "Electronics", 119.00, 55.00, 1),
    ("Glide Wireless Mouse", "Electronics", 34.99, 12.40, 1),
    ("Halo Noise-Cancelling Headphones", "Electronics", 249.00, 132.00, 1),
    ("Ember Smart Kettle", "Home & Kitchen", 89.00, 41.00, 1),
    ("Brew Master Coffee Grinder", "Home & Kitchen", 64.50, 27.80, 1),
    ("Cast Iron Skillet 12\"", "Home & Kitchen", 42.00, 16.00, 1),
    ("Chef's Knife Pro 8\"", "Home & Kitchen", 75.00, 29.00, 1),
    ("Bamboo Cutting Board Set", "Home & Kitchen", 29.99, 9.50, 1),
    ("Glass Meal Prep Containers (10)", "Home & Kitchen", 36.00, 13.20, 1),
    ("AeroCrisp Air Fryer", "Home & Kitchen", 139.00, 72.00, 1),
    ("Linen Throw Blanket", "Home & Kitchen", 54.00, 21.00, 1),
    ("ErgoFlex Office Chair", "Office", 289.00, 151.00, 1),
    ("Standing Desk Converter", "Office", 199.00, 104.00, 1),
    ("Hardcover Dotted Notebook", "Office", 18.50, 5.10, 1),
    ("Gel Pen Set (12)", "Office", 12.99, 3.80, 1),
    ("Desk Organizer Tray", "Office", 24.00, 8.60, 1),
    ("LED Desk Lamp", "Office", 48.00, 19.90, 1),
    ("Monitor Arm Single", "Office", 69.00, 31.00, 1),
    ("TrailRunner Shoes", "Sports & Outdoors", 119.99, 58.00, 1),
    ("Yoga Mat Premium", "Sports & Outdoors", 39.00, 14.00, 1),
    ("Adjustable Dumbbells 20kg", "Sports & Outdoors", 179.00, 96.00, 1),
    ("Insulated Water Bottle 1L", "Sports & Outdoors", 27.50, 9.00, 1),
    ("Camping Tent 2-Person", "Sports & Outdoors", 159.00, 82.00, 1),
    ("Resistance Bands Kit", "Sports & Outdoors", 22.00, 6.50, 1),
    ("Cycling Helmet", "Sports & Outdoors", 64.00, 28.00, 1),
    ("The Data-Driven Manager", "Books", 24.99, 8.00, 1),
    ("SQL for Humans", "Books", 32.00, 10.50, 1),
    ("Designing Calm Systems", "Books", 28.50, 9.20, 1),
    ("Cooking With Seasons", "Books", 35.00, 12.00, 1),
    ("Field Guide to Birds", "Books", 21.00, 7.00, 1),
    ("Midnight Atlas (Novel)", "Books", 16.99, 5.00, 1),
    # The last four are never ordered (used by "products never ordered" questions).
    ("Retro Film Camera", "Electronics", 189.00, 97.00, 0),
    ("Ceramic Fondue Set", "Home & Kitchen", 58.00, 24.00, 0),
    ("Fountain Pen Classic", "Office", 85.00, 33.00, 1),
    ("Snowshoe Pair", "Sports & Outdoors", 145.00, 70.00, 0),
]
NEVER_ORDERED = 4

FIRST_NAMES = [
    "Aarav", "Ananya", "Rohan", "Priya", "Vikram", "Isha", "Kabir", "Meera", "Arjun", "Diya",
    "Liam", "Olivia", "Noah", "Emma", "Lucas", "Sofia", "Ethan", "Mia", "Mateo", "Chloe",
    "Hiro", "Yuki", "Chen", "Lena", "Omar", "Zara", "Felix", "Nora", "Ravi", "Tara",
]
LAST_NAMES = [
    "Sharma", "Patel", "Iyer", "Khan", "Gupta", "Reddy", "Singh", "Das", "Nair", "Mehta",
    "Smith", "Johnson", "Brown", "Garcia", "Miller", "Wilson", "Lopez", "Clark", "Lee", "Young",
    "Tanaka", "Wang", "Muller", "Rossi", "Haddad", "Novak", "Silva", "Kim", "Cohen", "Ahmed",
]
LOCATIONS = [  # (city, state, country, weight)
    ("Bengaluru", "Karnataka", "India", 8), ("Mumbai", "Maharashtra", "India", 8),
    ("Delhi", "Delhi", "India", 7), ("Pune", "Maharashtra", "India", 5),
    ("Hyderabad", "Telangana", "India", 5), ("Chennai", "Tamil Nadu", "India", 4),
    ("Austin", "Texas", "USA", 4), ("Seattle", "Washington", "USA", 3),
    ("New York", "New York", "USA", 4), ("London", "England", "UK", 3),
    ("Toronto", "Ontario", "Canada", 3), ("Berlin", "Berlin", "Germany", 2),
]
SEGMENTS = [("Consumer", 6), ("Small Business", 3), ("Enterprise", 1)]
STATUSES = [("completed", 70), ("shipped", 12), ("pending", 6), ("cancelled", 7), ("refunded", 5)]
PAYMENTS = [("card", 45), ("upi", 30), ("paypal", 15), ("bank_transfer", 10)]

DATA_START = date(2025, 1, 1)
DATA_END = date(2026, 9, 30)  # reference date: newest possible order
N_CUSTOMERS = 150
N_ORDERS = 1600


def _weighted(rng: random.Random, options: list[tuple]) -> tuple:
    return rng.choices(options, weights=[o[-1] for o in options], k=1)[0]


def _random_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def build_database(path: Path, *, seed: int = 42, overwrite: bool = True) -> dict[str, int]:
    """Create the database file at `path` and fill it. Returns row counts."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not overwrite:
            raise FileExistsError(path)
        path.unlink()

    rng = random.Random(seed)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)

        # --- products ---
        product_rows = []
        for pid, (name, category, price, cost, active) in enumerate(PRODUCTS, start=1):
            created = _random_date(rng, date(2024, 6, 1), date(2024, 12, 31))
            product_rows.append(
                (pid, name, category, price, cost, rng.randint(0, 400), active, created.isoformat())
            )
        conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?)", product_rows)
        orderable = [r for r in product_rows[: len(product_rows) - NEVER_ORDERED]]
        # Popularity weights so rankings are meaningful (not uniform noise).
        popularity = [rng.uniform(0.3, 3.0) for _ in orderable]

        # --- customers ---
        customer_rows = []
        used_emails: set[str] = set()
        for cid in range(1, N_CUSTOMERS + 1):
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            email = f"{first}.{last}{cid}@example.com".lower()
            used_emails.add(email)
            city, state, country, _ = _weighted(rng, LOCATIONS)
            segment = _weighted(rng, SEGMENTS)[0]
            signup = _random_date(rng, date(2024, 1, 1), date(2026, 6, 30))
            customer_rows.append(
                (cid, first, last, email, city, state, country, segment, signup.isoformat())
            )
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?)", customer_rows)
        # Some customers order far more often than others.
        activity = [min(rng.paretovariate(1.6), 12.0) for _ in customer_rows]

        # --- orders + order_items ---
        order_rows, item_rows = [], []
        item_id = 1
        for oid in range(1, N_ORDERS + 1):
            cust = rng.choices(customer_rows, weights=activity, k=1)[0]
            signup = date.fromisoformat(cust[8])
            start = max(DATA_START, signup)
            # Gentle growth trend: later dates are more likely.
            span = (DATA_END - start).days
            order_date = start + timedelta(days=int(span * (rng.random() ** 0.8)))
            status = _weighted(rng, STATUSES)[0]
            if (DATA_END - order_date).days > 30 and status in ("pending", "shipped"):
                status = "completed"  # old orders have been delivered
            payment = _weighted(rng, PAYMENTS)[0]
            shipping = rng.choice([0.0, 0.0, 4.99, 7.99, 12.5])
            order_rows.append((oid, cust[0], order_date.isoformat(), status, payment, shipping))

            chosen = rng.choices(orderable, weights=popularity, k=rng.choice([1, 1, 2, 2, 3, 4]))
            for product in {p[0]: p for p in chosen}.values():  # de-duplicate products per order
                list_price = product[3]
                price_change = rng.choice([1.0, 1.0, 1.0, 0.95, 1.05])
                discount = rng.choice([0, 0, 0, 0, 0.05, 0.1, 0.15, 0.2])
                item_rows.append(
                    (item_id, oid, product[0], rng.choice([1, 1, 1, 2, 2, 3, 5]),
                     round(list_price * price_change, 2), discount)
                )
                item_id += 1
        conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", order_rows)
        conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", item_rows)
        conn.commit()
        return {
            "customers": len(customer_rows),
            "products": len(product_rows),
            "orders": len(order_rows),
            "order_items": len(item_rows),
        }
    finally:
        conn.close()
