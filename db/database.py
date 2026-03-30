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
    # events に event_type カラムを追加（移動イベント対応）
    if insp.has_table("events"):
        cols = {c["name"] for c in insp.get_columns("events")}
        if "event_type" not in cols:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE events "
                    "ADD COLUMN event_type VARCHAR(20) NOT NULL DEFAULT 'normal'"
                ))
                conn.commit()
    # events.venue_id の NOT NULL 制約を外す（移動イベントは会場なし）
    # PostgreSQL: ALTER TABLE events ALTER COLUMN venue_id DROP NOT NULL
    # SQLite  : nullable 変更は再作成が必要だが、新規DBは既に nullable なのでスキップ
    if insp.has_table("events") and DATABASE_URL.startswith("postgresql"):
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE events ALTER COLUMN venue_id DROP NOT NULL"
                ))
                conn.commit()
        except Exception:
            pass  # すでに nullable の場合は無視
    # 「移動引率」ロールが存在しない場合は自動作成
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT id FROM roles WHERE name = '移動引率' LIMIT 1")
            ).fetchone()
            if not exists:
                conn.execute(
                    text("INSERT INTO roles (name, sort_order) VALUES ('移動引率', 999)")
                )
                conn.commit()
    except Exception:
        pass  # roles テーブルがまだない場合は create_all 後に対応
    Base.metadata.create_all(bind=engine)
    # create_all 後に再試行（テーブル新規作成直後の場合）
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT id FROM roles WHERE name = '移動引率' LIMIT 1")
            ).fetchone()
            if not exists:
                conn.execute(
                    text("INSERT INTO roles (name, sort_order) VALUES ('移動引率', 999)")
                )
                conn.commit()
    except Exception:
        pass
