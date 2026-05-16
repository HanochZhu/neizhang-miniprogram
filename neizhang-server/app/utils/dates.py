from datetime import datetime, timedelta


def parse_start_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD as start of that day (inclusive)."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def parse_end_date_exclusive(date_str: str) -> datetime:
    """Parse YYYY-MM-DD as exclusive upper bound (includes entire end day)."""
    return parse_start_date(date_str) + timedelta(days=1)
