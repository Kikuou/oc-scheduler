from sqlalchemy import (
    Column, Integer, String, Text, Boolean, ForeignKey,
    UniqueConstraint, Index, func
)
from sqlalchemy.orm import relationship
from db.database import Base


class Occasion(Base):
    """開催（年度・日付・名称）"""
    __tablename__ = "occasions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False)
    date = Column(String(10), nullable=False)   # ISO8601 "2025-08-03"
    name = Column(String(100), nullable=False)  # "8月OC"
    note = Column(Text)
    day_start_time = Column(String(5), nullable=False, default="09:00")
    day_end_time = Column(String(5), nullable=False, default="17:00")
    created_at = Column(String(20), default=lambda: _now())

    events = relationship("Event", back_populates="occasion", cascade="all, delete-orphan")
    occasion_venues = relationship("OccasionVenue", back_populates="occasion",
                                   cascade="all, delete-orphan",
                                   order_by="OccasionVenue.sort_order")
    occasion_program_lanes = relationship("OccasionProgramLane", back_populates="occasion",
                                          cascade="all, delete-orphan",
                                          order_by="OccasionProgramLane.sort_order")

    __table_args__ = (
        UniqueConstraint("year", "date", "name"),
    )

    @property
    def venue_ids(self):
        return [ov.venue_id for ov in self.occasion_venues]

    @property
    def program_lane_ids(self):
        return [opl.program_lane_id for opl in self.occasion_program_lanes]


class OccasionVenue(Base):
    """開催ごとの使用会場（参考用・後方互換）"""
    __tablename__ = "occasion_venues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    occasion_id = Column(Integer, ForeignKey("occasions.id", ondelete="CASCADE"), nullable=False)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)

    occasion = relationship("Occasion", back_populates="occasion_venues")
    venue = relationship("Venue")

    __table_args__ = (
        UniqueConstraint("occasion_id", "venue_id"),
        Index("idx_ov_occasion", "occasion_id"),
    )


class ProgramLane(Base):
    """実施枠マスタ（スケジュール表の列単位）
    例：食物栄養学科 / こども地域学科 / ちょこっとOC / 備考（食物栄養学科）
    lane_type: "normal"（通常実施枠）or "remark"（備考枠）
    """
    __tablename__ = "program_lanes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    lane_type = Column(String(20), nullable=False, default="normal")  # "normal" or "remark"

    events = relationship("Event", back_populates="program_lane")
    occasion_program_lanes = relationship("OccasionProgramLane", back_populates="program_lane")


class OccasionProgramLane(Base):
    """開催ごとの使用実施枠（中間テーブル）"""
    __tablename__ = "occasion_program_lanes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    occasion_id = Column(Integer, ForeignKey("occasions.id", ondelete="CASCADE"), nullable=False)
    program_lane_id = Column(Integer, ForeignKey("program_lanes.id"), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    is_visible = Column(Boolean, nullable=False, default=True)  # 表示/非表示フラグ

    occasion = relationship("Occasion", back_populates="occasion_program_lanes")
    program_lane = relationship("ProgramLane", back_populates="occasion_program_lanes")

    __table_args__ = (
        UniqueConstraint("occasion_id", "program_lane_id"),
        Index("idx_opl_occasion", "occasion_id"),
    )


class Venue(Base):
    """会場マスタ（物理的な部屋・教室）"""
    __tablename__ = "venues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    capacity = Column(Integer)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)

    events = relationship("Event", back_populates="venue")


class Staff(Base):
    """担当者マスタ"""
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    staff_type = Column(String(20), nullable=False)  # "教員" "職員" "学生"
    department = Column(String(50))
    grade = Column(Integer)
    is_active = Column(Boolean, nullable=False, default=True)
    note = Column(Text)
    sort_order = Column(Integer, nullable=False, default=0)

    assignments = relationship("EventAssignment", back_populates="staff")


class Role(Base):
    """役割マスタ"""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)
    sort_order = Column(Integer, nullable=False, default=0)

    assignments = relationship("EventAssignment", back_populates="role")


class ContentTemplate(Base):
    """内容テンプレート"""
    __tablename__ = "content_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(100), nullable=False)
    duration_min = Column(Integer)
    note = Column(Text)
    sort_order = Column(Integer, nullable=False, default=0)


class Event(Base):
    """イベント（スケジュール本体）"""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    occasion_id = Column(Integer, ForeignKey("occasions.id", ondelete="CASCADE"), nullable=False)
    program_lane_id = Column(Integer, ForeignKey("program_lanes.id"), nullable=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False)
    start_time = Column(String(5), nullable=False)   # "09:20"
    end_time = Column(String(5), nullable=False)     # "10:00"
    duration_min = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    note = Column(Text)
    event_group_id = Column(String(36), nullable=True, index=True)  # 複数実施枠一括登録グループID

    occasion = relationship("Occasion", back_populates="events")
    program_lane = relationship("ProgramLane", back_populates="events")
    venue = relationship("Venue", back_populates="events")
    assignments = relationship("EventAssignment", back_populates="event", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_events_occasion", "occasion_id"),
        Index("idx_events_lane_time", "program_lane_id", "start_time"),
        Index("idx_events_venue_time", "venue_id", "start_time"),
    )


class EventAssignment(Base):
    """イベント担当割当"""
    __tablename__ = "event_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)

    event = relationship("Event", back_populates="assignments")
    staff = relationship("Staff", back_populates="assignments")
    role = relationship("Role", back_populates="assignments")

    __table_args__ = (
        UniqueConstraint("event_id", "staff_id"),
        Index("idx_assignments_staff", "staff_id"),
    )


class PrintNoteSet(Base):
    """備考セット（"学生用" / "教員用" など、または備考枠に紐づくセット）
    program_lane_id が設定されている場合は、その備考枠（lane_type="remark"）専用のセット
    """
    __tablename__ = "print_note_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    occasion_id = Column(Integer, ForeignKey("occasions.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(50), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    program_lane_id = Column(Integer, ForeignKey("program_lanes.id"), nullable=True)  # 備考枠リンク

    notes = relationship("PrintNoteRow", back_populates="note_set",
                         cascade="all, delete-orphan",
                         order_by="PrintNoteRow.start_time")

    __table_args__ = (
        UniqueConstraint("occasion_id", "name"),
        Index("idx_pns_occasion", "occasion_id"),
    )


class PrintNoteRow(Base):
    """備考 — スケジュール上の時間帯に紐づくメモ"""
    __tablename__ = "print_note_rows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    note_set_id = Column(Integer, ForeignKey("print_note_sets.id", ondelete="CASCADE"), nullable=False)
    occasion_id = Column(Integer, ForeignKey("occasions.id", ondelete="CASCADE"), nullable=False)
    start_time = Column(String(5), nullable=False)   # "09:00"
    end_time   = Column(String(5), nullable=False)   # "10:30"
    content    = Column(Text, nullable=False)

    note_set = relationship("PrintNoteSet", back_populates="notes")

    __table_args__ = (
        Index("idx_pnr_noteset", "note_set_id"),
        Index("idx_pnr_occasion", "occasion_id"),
    )


def _now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
