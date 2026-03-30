#!/usr/bin/env python3
"""
SQLite → Neon PostgreSQL データ移行スクリプト

使い方:
    DATABASE_URL="postgresql://user:pass@host/dbname?sslmode=require" python3 migrate_to_postgres.py

または .env に DATABASE_URL を書いて:
    python3 migrate_to_postgres.py

注意:
    - 既存データがある行は ON CONFLICT DO NOTHING でスキップします（重複安全）
    - 移行後にシーケンス（autoincrement）を正しい最大値に更新します
    - SQLiteの is_active / is_visible（0/1整数）は Python bool に変換して投入します
"""

import os
import sys
import sqlite3

# .env ファイルが存在すれば読み込む
def load_dotenv(path=".env"):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_dotenv()

# ── 設定 ──────────────────────────────────────────────────────────────────
SQLITE_PATH = os.environ.get("SQLITE_PATH", "data/oc_schedule.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL 環境変数が設定されていません")
    print("  例: DATABASE_URL='postgresql://...' python3 migrate_to_postgres.py")
    sys.exit(1)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not os.path.exists(SQLITE_PATH):
    print(f"ERROR: SQLiteファイルが見つかりません: {SQLITE_PATH}")
    sys.exit(1)

# ── ユーティリティ ─────────────────────────────────────────────────────────
def to_bool(v):
    """SQLiteの 0/1 整数 → Python bool（Postgresのbooleanに対応）"""
    if v is None:
        return None
    return bool(v)

def insert_rows(cur, table, cols, rows, *, conflict_cols=None):
    """
    指定テーブルへ行を一括挿入。ON CONFLICT DO NOTHING で重複をスキップ。
    """
    if not rows:
        return 0

    col_str = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    conflict_clause = "ON CONFLICT DO NOTHING"

    sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) {conflict_clause}"
    cur.executemany(sql, rows)
    return len(rows)

def reset_sequence(cur, table, id_col="id"):
    """
    PostgreSQLのシーケンスを現在の最大ID値にリセットする。
    （IDを明示指定してINSERTした後に必須）
    """
    cur.execute(f"""
        SELECT setval(
            pg_get_serial_sequence('{table}', '{id_col}'),
            COALESCE((SELECT MAX({id_col}) FROM {table}), 0) + 1,
            false
        )
    """)

# ── メイン処理 ────────────────────────────────────────────────────────────
def main():
    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2-binary が未インストールです")
        print("  pip install psycopg2-binary")
        sys.exit(1)

    print("=" * 55)
    print("  SQLite → Neon PostgreSQL 移行スクリプト")
    print("=" * 55)
    print(f"  SQLite  : {SQLITE_PATH}")
    print(f"  Postgres: {DATABASE_URL[:40]}...")
    print()

    # SQLite接続
    src = sqlite3.connect(SQLITE_PATH)
    src.row_factory = sqlite3.Row

    # PostgreSQL接続
    dst = psycopg2.connect(DATABASE_URL)
    dst.autocommit = False
    dst_cur = dst.cursor()

    try:
        src_cur = src.cursor()

        # ── 1. roles ────────────────────────────────────────────────
        src_cur.execute("SELECT id, name, sort_order FROM roles ORDER BY id")
        rows = [(r["id"], r["name"], r["id"] if r["sort_order"] is None else r["sort_order"])
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "roles", ["id", "name", "sort_order"], rows)
        reset_sequence(dst_cur, "roles")
        print(f"  roles              : {n}件")

        # ── 2. venues ───────────────────────────────────────────────
        src_cur.execute("SELECT id, name, capacity, is_active, sort_order FROM venues ORDER BY id")
        rows = [(r["id"], r["name"], r["capacity"], to_bool(r["is_active"]),
                 r["sort_order"] or 0)
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "venues",
                        ["id", "name", "capacity", "is_active", "sort_order"], rows)
        reset_sequence(dst_cur, "venues")
        print(f"  venues             : {n}件")

        # ── 3. staff ────────────────────────────────────────────────
        src_cur.execute("SELECT id, name, staff_type, department, grade, is_active, note, sort_order "
                        "FROM staff ORDER BY id")
        rows = [(r["id"], r["name"], r["staff_type"], r["department"], r["grade"],
                 to_bool(r["is_active"]), r["note"], r["sort_order"] or 0)
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "staff",
                        ["id", "name", "staff_type", "department", "grade",
                         "is_active", "note", "sort_order"], rows)
        reset_sequence(dst_cur, "staff")
        print(f"  staff              : {n}件")

        # ── 4. program_lanes ────────────────────────────────────────
        src_cur.execute("SELECT id, name, is_active, sort_order, lane_type FROM program_lanes ORDER BY id")
        rows = [(r["id"], r["name"], to_bool(r["is_active"]),
                 r["sort_order"] or 0, r["lane_type"] or "normal")
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "program_lanes",
                        ["id", "name", "is_active", "sort_order", "lane_type"], rows)
        reset_sequence(dst_cur, "program_lanes")
        print(f"  program_lanes      : {n}件")

        # ── 5. content_templates ────────────────────────────────────
        src_cur.execute("SELECT id, title, duration_min, note, sort_order FROM content_templates ORDER BY id")
        rows = [(r["id"], r["title"], r["duration_min"], r["note"], r["sort_order"] or 0)
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "content_templates",
                        ["id", "title", "duration_min", "note", "sort_order"], rows)
        reset_sequence(dst_cur, "content_templates")
        print(f"  content_templates  : {n}件")

        # ── 6. occasions ────────────────────────────────────────────
        src_cur.execute("SELECT id, year, date, name, note, created_at, day_start_time, day_end_time "
                        "FROM occasions ORDER BY id")
        rows = [(r["id"], r["year"], r["date"], r["name"], r["note"],
                 r["created_at"], r["day_start_time"] or "09:00", r["day_end_time"] or "17:00")
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "occasions",
                        ["id", "year", "date", "name", "note", "created_at",
                         "day_start_time", "day_end_time"], rows)
        reset_sequence(dst_cur, "occasions")
        print(f"  occasions          : {n}件")

        # ── 7. occasion_venues ──────────────────────────────────────
        src_cur.execute("SELECT id, occasion_id, venue_id, sort_order FROM occasion_venues ORDER BY id")
        rows = [(r["id"], r["occasion_id"], r["venue_id"], r["sort_order"] or 0)
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "occasion_venues",
                        ["id", "occasion_id", "venue_id", "sort_order"], rows)
        reset_sequence(dst_cur, "occasion_venues")
        print(f"  occasion_venues    : {n}件")

        # ── 8. occasion_program_lanes ───────────────────────────────
        src_cur.execute("SELECT id, occasion_id, program_lane_id, sort_order, is_visible "
                        "FROM occasion_program_lanes ORDER BY id")
        rows = [(r["id"], r["occasion_id"], r["program_lane_id"],
                 r["sort_order"] or 0, to_bool(r["is_visible"]) if r["is_visible"] is not None else True)
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "occasion_program_lanes",
                        ["id", "occasion_id", "program_lane_id", "sort_order", "is_visible"], rows)
        reset_sequence(dst_cur, "occasion_program_lanes")
        print(f"  occasion_prog_lanes: {n}件")

        # ── 9. events ───────────────────────────────────────────────
        src_cur.execute("SELECT id, occasion_id, program_lane_id, venue_id, "
                        "start_time, end_time, duration_min, title, note, event_group_id "
                        "FROM events ORDER BY id")
        rows = [(r["id"], r["occasion_id"], r["program_lane_id"], r["venue_id"],
                 r["start_time"], r["end_time"], r["duration_min"],
                 r["title"], r["note"], r["event_group_id"])
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "events",
                        ["id", "occasion_id", "program_lane_id", "venue_id",
                         "start_time", "end_time", "duration_min",
                         "title", "note", "event_group_id"], rows)
        reset_sequence(dst_cur, "events")
        print(f"  events             : {n}件")

        # ── 10. event_assignments ───────────────────────────────────
        src_cur.execute("SELECT id, event_id, staff_id, role_id FROM event_assignments ORDER BY id")
        rows = [(r["id"], r["event_id"], r["staff_id"], r["role_id"])
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "event_assignments",
                        ["id", "event_id", "staff_id", "role_id"], rows)
        reset_sequence(dst_cur, "event_assignments")
        print(f"  event_assignments  : {n}件")

        # ── 11. print_note_sets ─────────────────────────────────────
        src_cur.execute("SELECT id, occasion_id, name, sort_order, program_lane_id "
                        "FROM print_note_sets ORDER BY id")
        rows = [(r["id"], r["occasion_id"], r["name"],
                 r["sort_order"] or 0, r["program_lane_id"])
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "print_note_sets",
                        ["id", "occasion_id", "name", "sort_order", "program_lane_id"], rows)
        reset_sequence(dst_cur, "print_note_sets")
        print(f"  print_note_sets    : {n}件")

        # ── 12. print_note_rows ─────────────────────────────────────
        src_cur.execute("SELECT id, note_set_id, occasion_id, start_time, end_time, content "
                        "FROM print_note_rows ORDER BY id")
        rows = [(r["id"], r["note_set_id"], r["occasion_id"],
                 r["start_time"], r["end_time"], r["content"])
                for r in src_cur.fetchall()]
        n = insert_rows(dst_cur, "print_note_rows",
                        ["id", "note_set_id", "occasion_id", "start_time", "end_time", "content"], rows)
        reset_sequence(dst_cur, "print_note_rows")
        print(f"  print_note_rows    : {n}件")

        # ── コミット ────────────────────────────────────────────────
        dst.commit()
        print()
        print("=" * 55)
        print("  移行完了！")
        print("=" * 55)

    except Exception as e:
        dst.rollback()
        print()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        src.close()
        dst.close()

if __name__ == "__main__":
    main()
