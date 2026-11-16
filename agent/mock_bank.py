"""Mocked bank backend: four fictional customers. Nothing here is real data."""

CUSTOMERS: dict[str, dict] = {
    # Balance well above ₹10,000: late fee applies.
    "C001": {
        "name": "Asha Mehta",
        "phone": "+91 90000 00001",
        "outstanding_balance": 48_500,
        "minimum_due": 2_425,
        "days_past_due": 12,
        "otp": "482913",
    },
    # Balance below ₹10,000: no late fee.
    "C002": {
        "name": "Vikram Nair",
        "phone": "+91 90000 00002",
        "outstanding_balance": 8_200,
        "minimum_due": 410,
        "days_past_due": 5,
        "otp": "170356",
    },
    # Balance exactly ₹10,000: the rule says "over", so no late fee.
    "C003": {
        "name": "Farah Sheikh",
        "phone": "+91 90000 00003",
        "outstanding_balance": 10_000,
        "minimum_due": 500,
        "days_past_due": 21,
        "otp": "905528",
    },
    # Large balance at the 30-day edge.
    "C004": {
        "name": "Joseph D'Souza",
        "phone": "+91 90000 00004",
        "outstanding_balance": 126_000,
        "minimum_due": 6_300,
        "days_past_due": 30,
        "otp": "664071",
    },
}


def get_customer(customer_id: str) -> dict:
    """Return one customer's record, or raise ValueError for an unknown ID."""
    if customer_id not in CUSTOMERS:
        known = ", ".join(CUSTOMERS)
        raise ValueError(f"Unknown customer '{customer_id}'. Known customers: {known}")
    return CUSTOMERS[customer_id]
