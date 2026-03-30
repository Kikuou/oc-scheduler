#!/usr/bin/env python3
"""
SQLite → Neon PostgreSQL データ移行スクリプト

使い方:
    DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py          # 差分投入
    DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py --clean  # 全削除→再投入

オプション:
    --clean   移行前に全対象テーブルをTRUNCATEしてから投入（確実にやり直したい場合）
    --dry-run SQLite側の件数確認とFK整合チェックだけ行い、Postgresには何も書かない
"""

import os
import sys
import sqlite3
import argparse

# ── .env 読み込み ─────────────────────────────────────────────────────────
def load_dotenv(path=".env"):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_dotenv()

# ── 引数処理 ──────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="SQLite → Neon PostgreSQL 移行スクリプト")
parser.add_argument("--clean",   action="store_true", help="移行前に全テーブルをTRUNCATEする")
parser.add_argument("--dry-run", action="store_true", help="SQLite側の確認のみ、Postgresへは書き込まない")
args = parser.parse_args()

# ── 設定 ──────────────────────────────────────────────────────────────────
SQLITE_PATH  = os.environ.get("SQLITE_PATH", "data/oc_schedule.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not args.dry_run:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL 環境変数が設定されていません")
        sys.exit(1)
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not os.path.exists(SQLITE_PATH):
    print(f"ERROR: SQLiteファイルが見つかりません: {SQLITE_PATH}")
    sys.exit(1)

# ── ユーティリティ ────────────────────────────────────────────────────────
def to_bool(v):
    """SQLiteの 0/1 整数 → Python bool"""
    return None if v is None else bool(v)

def check_fk(src_cur, child_table, child_col, parent_table, parent_col="id"):
    """SQLite側でFK整合チェック。孤立した行を返す"""
    src_cur.execute(f"""
        SELECT c.{child_col}
        FROM "{child_table}" c
        LEFT JOIN "{parent_table}" p ON c.{child_col} = p.{parent_col}
        WHERE c.{child_col} IS NOT NULL AND p.{parent_col} IS NULL
    """)
    return [r[0] for r in src_cur.fetchall()]

def insert_pg(dst_cur, table, cols, rows):
    """
    PostgreSQLへIDを明示指定して一括INSERT。
    OVERRIDING SYSTEM VALUE を使い GENERATED AS IDENTITY にも対応。
    ON CONFLICT (id) DO NOTHING で重複をスキップ。
    """
    if not rows:
        return 0
    col_str      = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    sql = (f"INSERT INTO {table} ({col_str}) "
           f"OVERRIDING SYSTEM VALUE "
           f"VALUES ({placeholders}) "
           f"ON CONFLICT (id) DO NOTHING")
    dst_cur.executemany(sql, rows)
    return len(rows)

def reset_seq(dst_cur, table, id_col="id"):
    """シーケンスを現在の最大IDへリセット"""
    dst_cur.execute(f"""
        SELECT setval(
            pg_get_serial_sequence('{table}', '{id_col}'),
            COALESCE((SELECT MAX({id_col}) FROM {table}), 0) + 1,
            false
        )
    """)

# ── SQLite接続 ────────────────────────────────────────────────────────────
src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row
sc  = src.cursor()

print("=" * 60)
print("  SQLite → Neon PostgreSQL 移行スクリプト")
if args.dry_run: print("  【DRY-RUN モード：Postgresへの書き込みなし】")
if args.clean:   print("  【CLEANモード：全テーブルをTRUNCATEしてから投入】")
print("=" * 60)
print(f"  SQLite  : {SQLITE_PATH}")
if not args.dry_run:
    print(f"  Postgres: {DATABASE_URL[:50]}...")
print()

# ── FK整合チェック（SQLite側） ────────────────────────────────────────────
print("── FK整合チェック（SQLite側） ──────────────────────────")
fk_issues = {
    "occasion_venues.venue_id":              check_fk(sc, "occasion_venues",       "venue_id",       "venues"),
    "occasion_venues.occasion_id":           check_fk(sc, "occasion_venues",       "occasion_id",    "occasions"),
    "occasion_program_lanes.program_lane_id":check_fk(sc, "occasion_program_lanes","program_lane_id","program_lanes"),
    "occasion_program_lanes.occasion_id":    check_fk(sc, "occasion_program_lanes","occasion_id",    "occasions"),
    "events.occasion_id":                    check_fk(sc, "events",                "occasion_id",    "occasions"),
    "events.venue_id":                       check_fk(sc, "events",                "venue_id",       "venues"),
    "events.program_lane_id":                check_fk(sc, "events",                "program_lane_id","program_lanes"),
    "event_assignments.event_id":            check_fk(sc, "event_assignments",     "event_id",       "events"),
    "event_assignments.staff_id":            check_fk(sc, "event_assignments",     "staff_id",       "staff"),
    "event_assignments.role_id":             check_fk(sc, "event_assignments",     "role_id",        "roles"),
    "print_note_sets.occasion_id":           check_fk(sc, "print_note_sets",       "occasion_id",    "occasions"),
    "print_note_rows.note_set_id":           check_fk(sc, "print_note_rows",       "note_set_id",    "print_note_sets"),
}

has_issues = False
for key, bad_ids in fk_issues.items():
    if bad_ids:
        print(f"  ⚠ {key} → 孤立ID: {bad_ids}  ← この行はスキップします")
        has_issues = True

if not has_issues:
    print("  ✓ FK整合に問題なし")
print()

if args.dry_run:
    print("DRY-RUN完了。Postgresへの書き込みはしていません。")
    src.close()
    sys.exit(0)

# ── PostgreSQL接続・移行 ──────────────────────────────────────────────────
try:
    import psycopg2
except ImportError:
    print("ERROR: psycopg2-binary が未インストールです\n  pip3 install psycopg2-binary")
    sys.exit(1)

dst     = psycopg2.connect(DATABASE_URL)
dst.autocommit = False
dc      = dst.cursor()

try:
    # ── CLEANモード：依存関係の逆順でTRUNCATEしてからリセット ───────────
    if args.clean:
        print("── TRUNCATE（全データ削除） ────────────────────────────")
        # FK依存の逆順で削除
        clean_tables = [
            "print_note_rows", "print_note_sets",
            "event_assignments", "events",
            "occasion_program_lanes", "occasion_venues",
            "occasions",
            "content_templates", "program_lanes", "staff", "venues", "roles",
        ]
        for t in clean_tables:
            dc.execute(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE")
            print(f"  TRUNCATE {t}")
        dst.commit()
        print()

    # ── 1. roles ─────────────────────────────────────────────────────────
    sc.execute("SELECT id, name, sort_order FROM roles ORDER BY id")
    rows = [(r["id"], r["name"], r["sort_order"] or 0) for r in sc.fetchall()]
    n = insert_pg(dc, "roles", ["id","name","sort_order"], rows)
    reset_seq(dc, "roles")
    print(f"  roles               : {n}件")

    # ── 2. venues ────────────────────────────────────────────────────────
    sc.execute("SELECT id, name, capacity, is_active, sort_order FROM venues ORDER BY id")
    rows = [(r["id"], r["name"], r["capacity"], to_bool(r["is_active"]), r["sort_order"] or 0)
            for r in sc.fetchall()]
    n = insert_pg(dc, "venues", ["id","name","capacity","is_active","sort_order"], rows)
    reset_seq(dc, "venues")
    print(f"  venues              : {n}件")

    # ── 3. staff ─────────────────────────────────────────────────────────
    sc.execute("SELECT id, name, staff_type, department, grade, is_active, note, sort_order "
               "FROM staff ORDER BY id")
    rows = [(r["id"], r["name"], r["staff_type"], r["department"], r["grade"],
             to_bool(r["is_active"]), r["note"], r["sort_order"] or 0)
            for r in sc.fetchall()]
    n = insert_pg(dc, "staff",
                  ["id","name","staff_type","department","grade","is_active","note","sort_order"], rows)
    reset_seq(dc, "staff")
    print(f"  staff               : {n}件")

    # ── 4. program_lanes ─────────────────────────────────────────────────
    sc.execute("SELECT id, name, is_active, sort_order, lane_type FROM program_lanes ORDER BY id")
    rows = [(r["id"], r["name"], to_bool(r["is_active"]), r["sort_order"] or 0,
             r["lane_type"] or "normal")
            for r in sc.fetchall()]
    n = insert_pg(dc, "program_lanes",
                  ["id","name","is_active","sort_order","lane_type"], rows)
    reset_seq(dc, "program_lanes")
    print(f"  program_lanes       : {n}件")

    # ── 5. content_templates ─────────────────────────────────────────────
    sc.execute("SELECT id, title, duration_min, note, sort_order FROM content_templates ORDER BY id")
    rows = [(r["id"], r["title"], r["duration_min"], r["note"], r["sort_order"] or 0)
            for r in sc.fetchall()]
    n = insert_pg(dc, "content_templates",
                  ["id","title","duration_min","note","sort_order"], rows)
    reset_seq(dc, "content_templates")
    print(f"  content_templates   : {n}件")

    # ── 6. occasions ─────────────────────────────────────────────────────
    sc.execute("SELECT id, year, date, name, note, created_at, day_start_time, day_end_time "
               "FROM occasions ORDER BY id")
    rows = [(r["id"], r["year"], r["date"], r["name"], r["note"],
             r["created_at"], r["day_start_time"] or "09:00", r["day_end_time"] or "17:00")
            for r in sc.fetchall()]
    n = insert_pg(dc, "occasions",
                  ["id","year","date","name","note","created_at","day_start_time","day_end_time"], rows)
    reset_seq(dc, "occasions")
    print(f"  occasions           : {n}件")

    # ── 7. occasion_venues（孤立FK行をスキップ） ─────────────────────────
    sc.execute("""
        SELECT ov.id, ov.occasion_id, ov.venue_id, ov.sort_order
        FROM occasion_venues ov
        INNER JOIN occasions  o ON ov.occasion_id = o.id
        INNER JOIN venues     v ON ov.venue_id    = v.id
        ORDER BY ov.id
    """)
    rows = [(r["id"], r["occasion_id"], r["venue_id"], r["sort_order"] or 0)
            for r in sc.fetchall()]
    n = insert_pg(dc, "occasion_venues",
                  ["id","occasion_id","venue_id","sort_order"], rows)
    reset_seq(dc, "occasion_venues")
    print(f"  occasion_venues     : {n}件"
          + (" ← FK不整合行をスキップ済" if fk_issues["occasion_venues.venue_id"] else ""))

    # ── 8. occasion_program_lanes（孤立FK行をスキップ） ──────────────────
    sc.execute("""
        SELECT opl.id, opl.occasion_id, opl.program_lane_id, opl.sort_order, opl.is_visible
        FROM occasion_program_lanes opl
        INNER JOIN occasions     o  ON opl.occasion_id    = o.id
        INNER JOIN program_lanes pl ON opl.program_lane_id = pl.id
        ORDER BY opl.id
    """)
    rows = [(r["id"], r["occasion_id"], r["program_lane_id"], r["sort_order"] or 0,
             to_bool(r["is_visible"]) if r["is_visible"] is not None else True)
            for r in sc.fetchall()]
    n = insert_pg(dc, "occasion_program_lanes",
                  ["id","occasion_id","program_lane_id","sort_order","is_visible"], rows)
    reset_seq(dc, "occasion_program_lanes")
    print(f"  occasion_prog_lanes : {n}件")

    # ── 9. events（孤立FK行をスキップ） ──────────────────────────────────
    sc.execute("""
        SELECT e.id, e.occasion_id, e.program_lane_id, e.venue_id,
               e.start_time, e.end_time, e.duration_min,
               e.title, e.note, e.event_group_id
        FROM events e
        INNER JOIN occasions o ON e.occasion_id = o.id
        INNER JOIN venues    v ON e.venue_id     = v.id
        ORDER BY e.id
    """)
    rows = [(r["id"], r["occasion_id"], r["program_lane_id"], r["venue_id"],
             r["start_time"], r["end_time"], r["duration_min"],
             r["title"], r["note"], r["event_group_id"])
            for r in sc.fetchall()]
    n = insert_pg(dc, "events",
                  ["id","occasion_id","program_lane_id","venue_id",
                   "start_time","end_time","duration_min",
                   "title","note","event_group_id"], rows)
    reset_seq(dc, "events")
    print(f"  events              : {n}件")

    # ── 10. event_assignments（孤立FK行をスキップ） ───────────────────────
    sc.execute("""
        SELECT ea.id, ea.event_id, ea.staff_id, ea.role_id
        FROM event_assignments ea
        INNER JOIN events e ON ea.event_id = e.id
        INNER JOIN staff  s ON ea.staff_id = s.id
        INNER JOIN roles  r ON ea.role_id  = r.id
        ORDER BY ea.id
    """)
    rows = [(r["id"], r["event_id"], r["staff_id"], r["role_id"])
            for r in sc.fetchall()]
    n = insert_pg(dc, "event_assignments",
                  ["id","event_id","staff_id","role_id"], rows)
    reset_seq(dc, "event_assignments")
    print(f"  event_assignments   : {n}件")

    # ── 11. print_note_sets ───────────────────────────────────────────────
    sc.execute("""
        SELECT pns.id, pns.occasion_id, pns.name, pns.sort_order, pns.program_lane_id
        FROM print_note_sets pns
        INNER JOIN occasions o ON pns.occasion_id = o.id
        ORDER BY pns.id
    """)
    rows = [(r["id"], r["occasion_id"], r["name"], r["sort_order"] or 0, r["program_lane_id"])
            for r in sc.fetchall()]
    n = insert_pg(dc, "print_note_sets",
                  ["id","occasion_id","name","sort_order","program_lane_id"], rows)
    reset_seq(dc, "print_note_sets")
    print(f"  print_note_sets     : {n}件")

    # ── 12. print_note_rows ───────────────────────────────────────────────
    sc.execute("""
        SELECT pnr.id, pnr.note_set_id, pnr.occasion_id,
               pnr.start_time, pnr.end_time, pnr.content
        FROM print_note_rows pnr
        INNER JOIN print_note_sets pns ON pnr.note_set_id  = pns.id
        INNER JOIN occasions       o   ON pnr.occasion_id  = o.id
        ORDER BY pnr.id
    """)
    rows = [(r["id"], r["note_set_id"], r["occasion_id"],
             r["start_time"], r["end_time"], r["content"])
            for r in sc.fetchall()]
    n = insert_pg(dc, "print_note_rows",
                  ["id","note_set_id","occasion_id","start_time","end_time","content"], rows)
    reset_seq(dc, "print_note_rows")
    print(f"  print_note_rows     : {n}件")

    # ── コミット ──────────────────────────────────────────────────────────
    dst.commit()
    print()
    print("=" * 60)
    print("  移行完了！")
    print("=" * 60)

    if has_issues:
        print()
        print("  ⚠ 以下のSQLite FK不整合行はスキップしました：")
        for key, bad_ids in fk_issues.items():
            if bad_ids:
                print(f"    {key} → ID {bad_ids}")
        print("  ※ 必要なら SQLite 側のデータを修正してから再実行してください")

except Exception as e:
    dst.rollback()
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

finally:
    src.close()
    dst.close()
