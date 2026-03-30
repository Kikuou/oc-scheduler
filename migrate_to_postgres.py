#!/usr/bin/env python3
"""
SQLite → Neon PostgreSQL マスタデータ移行スクリプト

移行対象（マスタのみ）:
  roles / venues / staff / program_lanes / content_templates

使い方:
    DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py
    DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py --clean
    DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py --dry-run

オプション:
    --clean    移行前にマスタテーブルをTRUNCATEしてから投入
    --dry-run  SQLite件数確認のみ、Postgresには書き込まない
"""

import os, sys, sqlite3, argparse

def load_dotenv(path=".env"):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument("--clean",   action="store_true")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

SQLITE_PATH  = os.environ.get("SQLITE_PATH", "data/oc_schedule.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not args.dry_run and not DATABASE_URL:
    print("ERROR: DATABASE_URL が未設定です")
    sys.exit(1)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if not os.path.exists(SQLITE_PATH):
    print(f"ERROR: SQLiteファイルが見つかりません: {SQLITE_PATH}")
    sys.exit(1)

def to_bool(v):
    return None if v is None else bool(v)

def insert_pg(cur, table, cols, rows):
    if not rows:
        return 0
    col_str = ", ".join(cols)
    ph      = ", ".join(["%s"] * len(cols))
    sql = (f"INSERT INTO {table} ({col_str}) "
           f"OVERRIDING SYSTEM VALUE VALUES ({ph}) "
           f"ON CONFLICT (id) DO NOTHING")
    cur.executemany(sql, rows)
    return len(rows)

def reset_seq(cur, table):
    cur.execute(f"""
        SELECT setval(
            pg_get_serial_sequence('{table}', 'id'),
            COALESCE((SELECT MAX(id) FROM {table}), 0) + 1,
            false
        )
    """)

# ── 接続 ─────────────────────────────────────────────────────────────────
src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row
sc  = src.cursor()

print("=" * 55)
print("  マスタデータ移行スクリプト（SQLite → Neon）")
if args.dry_run: print("  【DRY-RUN: Postgresへの書き込みなし】")
if args.clean:   print("  【CLEAN: マスタテーブルをTRUNCATEしてから投入】")
print("=" * 55)

# ── DRY-RUN：SQLite件数確認のみ ──────────────────────────────────────────
MASTER_TABLES = ["roles", "venues", "staff", "program_lanes", "content_templates"]

print("── SQLite件数確認 ───────────────────────────────────")
for t in MASTER_TABLES:
    sc.execute(f"SELECT COUNT(*) FROM {t}")
    print(f"  {t:<22}: {sc.fetchone()[0]}件")

if args.dry_run:
    print("\nDRY-RUN完了。")
    src.close()
    sys.exit(0)

# ── PostgreSQL移行 ────────────────────────────────────────────────────────
try:
    import psycopg2
except ImportError:
    print("ERROR: pip3 install psycopg2-binary")
    sys.exit(1)

dst = psycopg2.connect(DATABASE_URL)
dst.autocommit = False
dc  = dst.cursor()

try:
    if args.clean:
        print("\n── TRUNCATE（マスタのみ） ──────────────────────────────")
        # 開催データはFK依存があるため先に削除してからマスタをクリア
        for t in ["event_assignments", "events", "occasion_program_lanes",
                  "occasion_venues", "occasions",
                  "print_note_rows", "print_note_sets",
                  "content_templates", "program_lanes", "staff", "venues", "roles"]:
            dc.execute(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE")
            print(f"  TRUNCATE {t}")
        dst.commit()

    print("\n── マスタ投入 ──────────────────────────────────────────")

    # 1. roles
    sc.execute("SELECT id, name, sort_order FROM roles ORDER BY id")
    rows = [(r["id"], r["name"], r["sort_order"] or 0) for r in sc.fetchall()]
    n = insert_pg(dc, "roles", ["id","name","sort_order"], rows)
    reset_seq(dc, "roles")
    print(f"  roles              : {n}件")

    # 2. venues
    sc.execute("SELECT id, name, capacity, is_active, sort_order FROM venues ORDER BY id")
    rows = [(r["id"], r["name"], r["capacity"], to_bool(r["is_active"]), r["sort_order"] or 0)
            for r in sc.fetchall()]
    n = insert_pg(dc, "venues", ["id","name","capacity","is_active","sort_order"], rows)
    reset_seq(dc, "venues")
    print(f"  venues             : {n}件")

    # 3. staff
    sc.execute("SELECT id, name, staff_type, department, grade, is_active, note, sort_order "
               "FROM staff ORDER BY id")
    rows = [(r["id"], r["name"], r["staff_type"], r["department"], r["grade"],
             to_bool(r["is_active"]), r["note"], r["sort_order"] or 0)
            for r in sc.fetchall()]
    n = insert_pg(dc, "staff",
                  ["id","name","staff_type","department","grade","is_active","note","sort_order"], rows)
    reset_seq(dc, "staff")
    print(f"  staff              : {n}件")

    # 4. program_lanes
    sc.execute("SELECT id, name, is_active, sort_order, lane_type FROM program_lanes ORDER BY id")
    rows = [(r["id"], r["name"], to_bool(r["is_active"]), r["sort_order"] or 0,
             r["lane_type"] or "normal")
            for r in sc.fetchall()]
    n = insert_pg(dc, "program_lanes", ["id","name","is_active","sort_order","lane_type"], rows)
    reset_seq(dc, "program_lanes")
    print(f"  program_lanes      : {n}件")

    # 5. content_templates
    sc.execute("SELECT id, title, duration_min, note, sort_order FROM content_templates ORDER BY id")
    rows = [(r["id"], r["title"], r["duration_min"], r["note"], r["sort_order"] or 0)
            for r in sc.fetchall()]
    n = insert_pg(dc, "content_templates", ["id","title","duration_min","note","sort_order"], rows)
    reset_seq(dc, "content_templates")
    print(f"  content_templates  : {n}件")

    dst.commit()
    print("\n" + "=" * 55)
    print("  移行完了！")
    print("=" * 55)

except Exception as e:
    dst.rollback()
    print(f"\nERROR: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)
finally:
    src.close()
    dst.close()
