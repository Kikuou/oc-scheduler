"""重複警告チェッカー（保存は妨げない）"""
from db.database import SessionLocal
from db.models import Event, EventAssignment


def check_staff_conflict(occasion_id: int, start_time: str, end_time: str,
                         staff_id: int, exclude_event_id: int | None = None) -> list[dict]:
    """指定担当者の同一開催内時間重複を検出"""
    db = SessionLocal()
    q = (db.query(Event)
         .join(EventAssignment)
         .filter(
             EventAssignment.staff_id == staff_id,
             Event.occasion_id == occasion_id,
             Event.start_time < end_time,
             Event.end_time > start_time,
         ))
    if exclude_event_id:
        q = q.filter(Event.id != exclude_event_id)
    conflicts = q.all()
    result = [{"event_id": e.id, "title": e.title,
               "start": e.start_time, "end": e.end_time} for e in conflicts]
    db.close()
    return result


def check_venue_conflict(occasion_id: int, start_time: str, end_time: str,
                         venue_id: int, exclude_event_id: int | None = None) -> list[dict]:
    """同一会場の時間重複を検出"""
    db = SessionLocal()
    q = db.query(Event).filter(
        Event.occasion_id == occasion_id,
        Event.venue_id == venue_id,
        Event.start_time < end_time,
        Event.end_time > start_time,
    )
    if exclude_event_id:
        q = q.filter(Event.id != exclude_event_id)
    conflicts = q.all()
    result = [{"event_id": e.id, "title": e.title,
               "start": e.start_time, "end": e.end_time} for e in conflicts]
    db.close()
    return result


def check_lane_conflict(occasion_id: int, start_time: str, end_time: str,
                        program_lane_id: int, exclude_event_id: int | None = None,
                        exclude_event_ids: set | None = None) -> list[dict]:
    """同一実施枠内の時間重複を検出"""
    db = SessionLocal()
    q = db.query(Event).filter(
        Event.occasion_id == occasion_id,
        Event.program_lane_id == program_lane_id,
        Event.start_time < end_time,
        Event.end_time > start_time,
    )
    if exclude_event_id:
        q = q.filter(Event.id != exclude_event_id)
    if exclude_event_ids:
        q = q.filter(~Event.id.in_(exclude_event_ids))
    conflicts = q.all()
    result = [{"event_id": e.id, "title": e.title,
               "start": e.start_time, "end": e.end_time} for e in conflicts]
    db.close()
    return result
