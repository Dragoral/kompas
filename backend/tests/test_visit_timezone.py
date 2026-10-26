from datetime import datetime, timezone

from app.api.doctor import VisitIn


def test_visit_datetime_with_offset_is_normalized_to_utc_naive():
    visit = VisitIn(next_visit_at="2026-10-19T17:45:00+03:00")

    assert visit.next_visit_at == datetime(2026, 10, 19, 14, 45, 0)
    assert visit.next_visit_at.tzinfo is None


def test_visit_datetime_z_is_normalized_to_utc_naive():
    visit = VisitIn(next_visit_at="2026-10-19T14:45:00Z")

    assert visit.next_visit_at == datetime(2026, 10, 19, 14, 45, 0)
    assert visit.next_visit_at.tzinfo is None
