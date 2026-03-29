"""DBマイグレーション
- v1: 会場区分削除 + sort_order追加
- v2: 開催に day_start_time/day_end_time + occasion_venues テーブル
- v3: 実施枠マスタ(program_lanes) + 開催×実施枠(occasion_program_lanes) + events.program_lane_id
"""
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH


def migrate():
    if not os.path.exists(DB_PATH):
        print("DBファイルが存在しません。init_data.pyで初期化してください。")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # --- v1: 会場テーブルから department カラム削除 ---
    cur.execute("PRAGMA table_info(venues)")
    venue_cols = {row[1] for row in cur.fetchall()}
    if "department" in venue_cols:
        print("venues: department カラムを削除します...")
        try:
            cur.execute("ALTER TABLE venues DROP COLUMN department")
            print("  -> DROP COLUMN 成功")
        except Exception:
            print("  -> DROP COLUMN 未対応。テーブル再作成で対応...")
            cur.execute("ALTER TABLE venues RENAME TO _venues_old")
            cur.execute("""
                CREATE TABLE venues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    capacity INTEGER,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0
                )
            """)
            cur.execute("""
                INSERT INTO venues (id, name, capacity, is_active, sort_order)
                SELECT id, name, capacity, is_active, 0 FROM _venues_old
            """)
            cur.execute("DROP TABLE _venues_old")
    else:
        print("venues: department は既に削除済み")

    # --- v1: sort_order カラム追加 ---
    for tname in ["venues", "staff", "roles", "content_templates"]:
        cur.execute(f"PRAGMA table_info({tname})")
        cols = {row[1] for row in cur.fetchall()}
        if "sort_order" not in cols:
            print(f"{tname}: sort_order カラムを追加...")
            cur.execute(f"ALTER TABLE {tname} ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            cur.execute(f"SELECT id FROM {tname} ORDER BY id")
            ids = [row[0] for row in cur.fetchall()]
            for i, rid in enumerate(ids):
                cur.execute(f"UPDATE {tname} SET sort_order = ? WHERE id = ?", (i, rid))
            print(f"  -> {len(ids)}件に連番を振りました")
        else:
            print(f"{tname}: sort_order は既に存在")

    # --- v2: occasions に day_start_time / day_end_time 追加 ---
    cur.execute("PRAGMA table_info(occasions)")
    occ_cols = {row[1] for row in cur.fetchall()}

    if "day_start_time" not in occ_cols:
        print("occasions: day_start_time / day_end_time を追加...")
        cur.execute("ALTER TABLE occasions ADD COLUMN day_start_time VARCHAR(5) NOT NULL DEFAULT '09:00'")
        cur.execute("ALTER TABLE occasions ADD COLUMN day_end_time VARCHAR(5) NOT NULL DEFAULT '17:00'")
        print("  -> 追加完了（デフォルト 09:00-17:00）")
    else:
        print("occasions: day_start_time は既に存在")

    # --- v2: occasion_venues テーブル作成 ---
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='occasion_venues'")
    if not cur.fetchone():
        print("occasion_venues テーブルを作成...")
        cur.execute("""
            CREATE TABLE occasion_venues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occasion_id INTEGER NOT NULL REFERENCES occasions(id) ON DELETE CASCADE,
                venue_id INTEGER NOT NULL REFERENCES venues(id),
                sort_order INTEGER NOT NULL DEFAULT 0,
                UNIQUE(occasion_id, venue_id)
            )
        """)
        cur.execute("CREATE INDEX idx_ov_occasion ON occasion_venues(occasion_id)")

        # 既存の開催について、使用中の会場を自動登録
        cur.execute("SELECT id FROM occasions")
        occ_ids = [row[0] for row in cur.fetchall()]
        for oid in occ_ids:
            cur.execute("""
                SELECT DISTINCT venue_id FROM events WHERE occasion_id = ?
                ORDER BY venue_id
            """, (oid,))
            vids = [row[0] for row in cur.fetchall()]
            if not vids:
                # イベントがない場合は全有効会場を割り当て
                cur.execute("SELECT id FROM venues WHERE is_active = 1 ORDER BY sort_order, id")
                vids = [row[0] for row in cur.fetchall()]
            for i, vid in enumerate(vids):
                cur.execute("""
                    INSERT OR IGNORE INTO occasion_venues (occasion_id, venue_id, sort_order)
                    VALUES (?, ?, ?)
                """, (oid, vid, i))
            print(f"  -> 開催ID={oid}: {len(vids)}会場を登録")
        print("  -> occasion_venues 作成完了")
    else:
        print("occasion_venues テーブルは既に存在")

    # --- v3: program_lanes テーブル ---
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='program_lanes'")
    if not cur.fetchone():
        print("program_lanes テーブルを作成...")
        cur.execute("""
            CREATE TABLE program_lanes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL UNIQUE,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0
            )
        """)
        default_lanes = ["食物栄養学科", "こども地域学科", "ちょこっとOC"]
        for i, lname in enumerate(default_lanes):
            cur.execute("INSERT INTO program_lanes (name, sort_order) VALUES (?, ?)", (lname, i))
        print(f"  -> デフォルト実施枠 {len(default_lanes)}件を作成")
    else:
        print("program_lanes テーブルは既に存在")

    # --- v3: occasion_program_lanes テーブル ---
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='occasion_program_lanes'")
    if not cur.fetchone():
        print("occasion_program_lanes テーブルを作成...")
        cur.execute("""
            CREATE TABLE occasion_program_lanes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occasion_id INTEGER NOT NULL REFERENCES occasions(id) ON DELETE CASCADE,
                program_lane_id INTEGER NOT NULL REFERENCES program_lanes(id),
                sort_order INTEGER NOT NULL DEFAULT 0,
                UNIQUE(occasion_id, program_lane_id)
            )
        """)
        cur.execute("CREATE INDEX idx_opl_occasion ON occasion_program_lanes(occasion_id)")

        # 既存の開催に全実施枠を割り当て
        cur.execute("SELECT id FROM occasions")
        occ_ids = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT id FROM program_lanes ORDER BY sort_order")
        lane_ids = [row[0] for row in cur.fetchall()]
        for oid in occ_ids:
            for i, lid in enumerate(lane_ids):
                cur.execute("""
                    INSERT OR IGNORE INTO occasion_program_lanes (occasion_id, program_lane_id, sort_order)
                    VALUES (?, ?, ?)
                """, (oid, lid, i))
            print(f"  -> 開催ID={oid}: {len(lane_ids)}実施枠を登録")
        print("  -> occasion_program_lanes 作成完了")
    else:
        print("occasion_program_lanes テーブルは既に存在")

    # --- v3: events に program_lane_id を追加 ---
    cur.execute("PRAGMA table_info(events)")
    ev_cols = {row[1] for row in cur.fetchall()}
    if "program_lane_id" not in ev_cols:
        print("events: program_lane_id を追加...")
        cur.execute("ALTER TABLE events ADD COLUMN program_lane_id INTEGER REFERENCES program_lanes(id)")

        # department → 実施枠 の自動マッピング
        cur.execute("SELECT id, name FROM program_lanes")
        lane_map = {row[1]: row[0] for row in cur.fetchall()}

        if lane_map.get("食物栄養学科"):
            cur.execute("UPDATE events SET program_lane_id = ? WHERE department = '食物'",
                        (lane_map["食物栄養学科"],))
            print(f"  -> 食物区分 {cur.rowcount}件 → 食物栄養学科")
        if lane_map.get("こども地域学科"):
            cur.execute("UPDATE events SET program_lane_id = ? WHERE department = '幼教'",
                        (lane_map["こども地域学科"],))
            print(f"  -> 幼教区分 {cur.rowcount}件 → こども地域学科")

        # NULL 残り（共通など）→ 先頭実施枠
        cur.execute("SELECT id FROM program_lanes ORDER BY sort_order LIMIT 1")
        first = cur.fetchone()
        if first:
            cur.execute("UPDATE events SET program_lane_id = ? WHERE program_lane_id IS NULL",
                        (first[0],))
            if cur.rowcount:
                print(f"  -> その他 {cur.rowcount}件 → 先頭実施枠に割り当て")
        print("  -> program_lane_id 追加完了")
    else:
        print("events: program_lane_id は既に存在")

    # --- v4: events.department カラム削除 ---
    cur.execute("PRAGMA table_info(events)")
    ev_cols = {row[1] for row in cur.fetchall()}
    if "department" in ev_cols:
        print("events: department カラムを削除します...")
        cur.execute("ALTER TABLE events RENAME TO _events_old")
        cur.execute("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occasion_id INTEGER NOT NULL REFERENCES occasions(id) ON DELETE CASCADE,
                program_lane_id INTEGER REFERENCES program_lanes(id),
                venue_id INTEGER NOT NULL REFERENCES venues(id),
                start_time VARCHAR(5) NOT NULL,
                end_time VARCHAR(5) NOT NULL,
                duration_min INTEGER NOT NULL,
                title VARCHAR(200) NOT NULL,
                note TEXT
            )
        """)
        cur.execute("""INSERT INTO events
            SELECT id, occasion_id, program_lane_id, venue_id,
                   start_time, end_time, duration_min, title, note
            FROM _events_old""")
        cur.execute("DROP TABLE _events_old")
        cur.execute("CREATE INDEX idx_events_occasion ON events(occasion_id)")
        cur.execute("CREATE INDEX idx_events_lane_time ON events(program_lane_id, start_time)")
        cur.execute("CREATE INDEX idx_events_venue_time ON events(venue_id, start_time)")
        print("  -> 完了")
    else:
        print("events: department は既に削除済み")

    # --- v4: content_templates.department カラム削除 ---
    cur.execute("PRAGMA table_info(content_templates)")
    tmpl_cols = {row[1] for row in cur.fetchall()}
    if "department" in tmpl_cols:
        print("content_templates: department カラムを削除します...")
        cur.execute("ALTER TABLE content_templates RENAME TO _tmpl_old")
        cur.execute("""
            CREATE TABLE content_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title VARCHAR(100) NOT NULL,
                duration_min INTEGER,
                note TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""INSERT INTO content_templates
            SELECT id, title, duration_min, note, sort_order FROM _tmpl_old""")
        cur.execute("DROP TABLE _tmpl_old")
        print("  -> 完了")
    else:
        print("content_templates: department は既に削除済み")

    # --- v5: events に event_group_id カラム追加（複数実施枠一括登録用） ---
    cur.execute("PRAGMA table_info(events)")
    ev_cols = {row[1] for row in cur.fetchall()}
    if "event_group_id" not in ev_cols:
        print("events: event_group_id カラムを追加...")
        cur.execute("ALTER TABLE events ADD COLUMN event_group_id VARCHAR(36)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_group ON events(event_group_id)")
        print("  -> 追加完了")
    else:
        print("events: event_group_id は既に存在")

    conn.commit()
    conn.close()
    print("\nマイグレーション完了!")


if __name__ == "__main__":
    migrate()
