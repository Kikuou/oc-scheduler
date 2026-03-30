from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from db import models  # noqa: F401
    # スキーマ変更時: print_note_rows が旧形式(time_slot列あり)なら再作成
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if insp.has_table("print_note_rows"):
        cols = {c["name"] for c in insp.get_columns("print_note_rows")}
        if "start_time" not in cols or "occasion_id" not in cols:
            with engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS print_note_rows"))
                conn.execute(text("DROP TABLE IF EXISTS print_note_sets"))
                conn.commit()
    # occasion_program_lanes に is_visible カラムを追加（既存DBの後方互換）
    if insp.has_table("occasion_program_lanes"):
        cols = {c["name"] for c in insp.get_columns("occasion_program_lanes")}
        if "is_visible" not in cols:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE occasion_program_lanes "
                    "ADD COLUMN is_visible BOOLEAN NOT NULL DEFAULT 1"
                ))
                conn.commit()
    # program_lanes に lane_type カラムを追加（備考枠対応）
    if insp.has_table("program_lanes"):
        cols = {c["name"] for c in insp.get_columns("program_lanes")}
        if "lane_type" not in cols:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE program_lanes "
                    "ADD COLUMN lane_type VARCHAR(20) NOT NULL DEFAULT 'normal'"
                ))
                conn.commit()
    # print_note_sets に program_lane_id カラムを追加（備考枠リンク）
    if insp.has_table("print_note_sets"):
        cols = {c["name"] for c in insp.get_columns("print_note_sets")}
        if "program_lane_id" not in cols:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE print_note_sets "
                    "ADD COLUMN program_lane_id INTEGER REFERENCES program_lanes(id)"
                ))
                conn.commit()
    Base.metadata.create_all(bind=engine)
