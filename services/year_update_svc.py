"""年度更新サービス：前年度複製・学年繰上げ"""
from db.database import SessionLocal
from db.models import Occasion, OccasionVenue, Event, EventAssignment, Staff


def get_preview(src_occasion_id: int) -> dict:
    """年度更新プレビュー情報を返す"""
    db = SessionLocal()
    src = db.get(Occasion, src_occasion_id)
    events = db.query(Event).filter(Event.occasion_id == src_occasion_id).order_by(Event.start_time).all()

    students_grade2 = (db.query(Staff)
                       .filter(Staff.staff_type == "学生", Staff.grade == 2, Staff.is_active == True)
                       .order_by(Staff.department, Staff.name).all())
    students_grade1 = (db.query(Staff)
                       .filter(Staff.staff_type == "学生", Staff.grade == 1, Staff.is_active == True)
                       .order_by(Staff.department, Staff.name).all())
    db.close()
    return {
        "src": {"id": src.id, "year": src.year, "name": src.name, "date": src.date},
        "events": [{"id": e.id, "title": e.title, "start_time": e.start_time,
                    "end_time": e.end_time, "venue_name": e.venue.name} for e in events],
        "graduating": [{"id": s.id, "name": s.name, "department": s.department} for s in students_grade2],
        "promoting": [{"id": s.id, "name": s.name, "department": s.department} for s in students_grade1],
    }


def execute_year_update(src_occasion_id: int, new_year: int, new_date: str, new_name: str,
                         keep_student_ids: list[int]) -> int:
    """
    年度更新を実行。
    - 開催をコピー（新年度・日付・名称で新規作成）
    - イベント・担当割当をコピー
    - 学生: grade 1→2, grade 2→is_active=False（keep_student_idsに含まれる場合は残す）
    Returns: 新しいoccasion_id
    """
    db = SessionLocal()

    # 1. 元の開催情報を取得
    src_occ = db.get(Occasion, src_occasion_id)

    # 2. 新開催作成（時間設定もコピー）
    new_occ = Occasion(
        year=new_year,
        date=new_date,
        name=new_name,
        day_start_time=src_occ.day_start_time if src_occ else "09:00",
        day_end_time=src_occ.day_end_time if src_occ else "17:00",
    )
    db.add(new_occ)
    db.flush()

    # 3. 使用会場をコピー
    src_venues = (db.query(OccasionVenue)
                  .filter(OccasionVenue.occasion_id == src_occasion_id)
                  .order_by(OccasionVenue.sort_order).all())
    for ov in src_venues:
        db.add(OccasionVenue(
            occasion_id=new_occ.id,
            venue_id=ov.venue_id,
            sort_order=ov.sort_order,
        ))

    # 4. イベント・担当割当をコピー
    src_events = db.query(Event).filter(Event.occasion_id == src_occasion_id).all()
    for ev in src_events:
        new_ev = Event(
            occasion_id=new_occ.id,
            venue_id=ev.venue_id,
            start_time=ev.start_time,
            end_time=ev.end_time,
            duration_min=ev.duration_min,
            title=ev.title,
            note=ev.note,
        )
        db.add(new_ev)
        db.flush()
        for a in ev.assignments:
            new_a = EventAssignment(
                event_id=new_ev.id,
                staff_id=a.staff_id,
                role_id=a.role_id,
            )
            db.add(new_a)

    # 5. 学生学年繰上げ
    students2 = db.query(Staff).filter(Staff.staff_type == "学生", Staff.grade == 2).all()
    for s in students2:
        if s.id in keep_student_ids:
            pass  # 残留（学年はそのまま or 維持）
        else:
            s.is_active = False  # 卒業候補→無効化

    students1 = db.query(Staff).filter(Staff.staff_type == "学生", Staff.grade == 1).all()
    for s in students1:
        s.grade = 2

    db.commit()
    new_id = new_occ.id
    db.close()
    return new_id
