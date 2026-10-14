"""Business meaning of tables/columns that the raw schema cannot express.

SQLite has no column comments, so these short notes are added to the LLM
prompt next to the discovered schema. They are hand-written definitions (a
tiny "data dictionary"), not retrieved documents - no RAG involved.
"""

TABLE_NOTES: dict[str, str] = {
    "customers": "One row per customer account.",
    "products": "Product catalogue. unit_price is the current list price in USD.",
    "orders": "One row per order placed by a customer.",
    "order_items": (
        "Line items of an order. unit_price is the price actually charged per unit "
        "at order time (USD); discount is a fraction between 0 and 1."
    ),
}

COLUMN_NOTES: dict[str, dict[str, str]] = {
    "orders": {
        "status": "Orders with status 'cancelled' or 'refunded' do not count as revenue.",
        "order_date": "ISO date string YYYY-MM-DD.",
    },
    "order_items": {
        "discount": "Line revenue = quantity * unit_price * (1 - discount).",
    },
    "customers": {"signup_date": "ISO date string YYYY-MM-DD."},
    "products": {"is_active": "1 = currently sold, 0 = discontinued."},
}

BUSINESS_RULES: list[str] = [
    "Revenue = SUM(order_items.quantity * order_items.unit_price * (1 - order_items.discount)) "
    "over orders whose status is NOT 'cancelled' or 'refunded'.",
    "Average order value = revenue / number of revenue-counting orders.",
    "All money values are USD; round money to 2 decimals.",
]
