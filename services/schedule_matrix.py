"""時間×実施枠マトリクス生成サービス"""
from db.database import SessionLocal
from db.models import Event, EventAssignment, Occasion, OccasionProgramLane, ProgramLane, PrintNoteRow, PrintNoteSet


SLOT_MIN = 5  # スロット単位（分）


def _to_minutes(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _from_minutes(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


def build_occasion_matrix(occasion_id: int, period: str = "all", lane_ids_filter: list = None) -> dict:
    """
    開催設定（開始/終了時刻＋使用実施枠）に基づいてマトリクスを生成する。

    Returns:
        {
          "slots": ["09:00", "09:10", ...],
          "lanes": [{"id":1, "name":"食物栄養学科"}, ...],
          "cells": { "09:00": { 1: {"event":{...}, "rowspan":4} | None } },
          "events": [...],
        }
    """
    db = SessionLocal()
    o = db.get(Occasion, occasion_id)
    if not o:
        db.close()
        return {"slots": [], "lanes": [], "cells": {}, "events": []}

    # 開催の使用実施枠を取得
    opl_list = (db.query(OccasionProgramLane)
                .filter(OccasionProgramLane.occasion_id == occasion_id)
                .order_by(OccasionProgramLane.sort_order).all())
    all_lane_ids = [opl.program_lane_id for opl in opl_list]
    # lane_ids_filter が指定された場合は絞り込む（元の sort_order を維持）
    if lane_ids_filter:
        lane_ids = [lid for lid in all_lane_ids if lid in lane_ids_filter]
    else:
        # is_visible == True の列のみ表示（スケジューラ表示用）
        visible_ids = {opl.program_lane_id for opl in opl_list if opl.is_visible}
        lane_ids = [lid for lid in all_lane_ids if lid in visible_ids]
    lanes_map = {}
    for opl in opl_list:
        lanes_map[opl.program_lane_id] = opl.program_lane

    if not lane_ids:
        db.close()
        return {"slots": [], "lanes": [], "cells": {}, "events": []}

    lanes = [lanes_map[lid] for lid in lane_ids if lid in lanes_map]

    # 開催の時間範囲
    day_start = _to_minutes(o.day_start_time)
    day_end = _to_minutes(o.day_end_time)

    # 期間フィルタ
    if period == "am":
        day_end = min(day_end, _to_minutes("12:00"))
    elif period == "pm":
        day_start = max(day_start, _to_minutes("12:00"))

    # スロット生成
    day_start = (day_start // SLOT_MIN) * SLOT_MIN
    day_end = ((day_end + SLOT_MIN - 1) // SLOT_MIN) * SLOT_MIN

    slots = []
    slot_types = {}  # スロットタイプを記録
    t = day_start
    while t < day_end:
        slot_str = _from_minutes(t)
        slots.append(slot_str)
        # スロットタイプを決定
        if t % 60 == 0:  # 1時間単位
            slot_types[slot_str] = "hour"
        elif t % 30 == 0:  # 30分単位
            slot_types[slot_str] = "half"
        elif t % 10 == 0:  # 10分単位
            slot_types[slot_str] = "ten"
        else:  # 5分単位
            slot_types[slot_str] = "five"
        t += SLOT_MIN

    if not slots:
        db.close()
        return {"slots": [], "lanes": [{"id": l.id, "name": l.name} for l in lanes],
                "cells": {}, "events": [], "slot_types": {}}

    # イベント取得（開始時刻順に処理して先着イベントを優先）
    events = db.query(Event).filter(Event.occasion_id == occasion_id).order_by(Event.start_time).all()

    # イベント情報をまとめる
    event_map: dict[int, dict] = {}
    for e in events:
        assignments = []
        for a in e.assignments:
            assignments.append({
                "staff_id": a.staff_id,
                "staff_name": a.staff.name,
                "staff_type": a.staff.staff_type,
                "role_id": a.role_id,
                "role_name": a.role.name,
            })
        event_map[e.id] = {
            "id": e.id,
            "title": e.title,
            "start_time": e.start_time,
            "end_time": e.end_time,
            "duration_min": e.duration_min,
            "program_lane_id": e.program_lane_id,
            "program_lane_name": e.program_lane.name if e.program_lane else None,
            "venue_id": e.venue_id,
            "venue_name": e.venue.name,
            "note": e.note,
            "assignments": assignments,
            "event_group_id": e.event_group_id,
        }

    # セルマトリクス構築（列キー = program_lane_id）
    cells: dict[str, dict[int, dict | None]] = {
        s: {l.id: None for l in lanes} for s in slots
    }

    for e in events:
        if e.program_lane_id not in lane_ids:
            continue

        e_start = _to_minutes(e.start_time)
        e_end = _to_minutes(e.end_time)
        rowspan = max(1, (e_end - e_start + SLOT_MIN - 1) // SLOT_MIN)  # 切り上げで正確に計算

        slot_key = _from_minutes((e_start // SLOT_MIN) * SLOT_MIN)
        if slot_key not in cells:
            continue
        if e.program_lane_id not in cells[slot_key]:
            continue

        # skipセルに当たった場合、次の空きスロットへ移動
        # （例：10:45開始イベントは slot_key=10:40 → skipなら 10:50 へ）
        while slot_key in cells:
            existing = cells[slot_key].get(e.program_lane_id)
            if not (existing and existing.get("skip")):
                break
            slot_key = _from_minutes(_to_minutes(slot_key) + SLOT_MIN)

        if slot_key not in cells or e.program_lane_id not in cells[slot_key]:
            continue  # スケジュール範囲外に出た場合はスキップ

        # 実際の配置スロット位置からrowspanを再計算
        slot_start_min = _to_minutes(slot_key)
        rowspan = max(1, (e_end - slot_start_min + SLOT_MIN - 1) // SLOT_MIN)

        cells[slot_key][e.program_lane_id] = {
            "event": event_map[e.id],
            "rowspan": rowspan,
            "skip": False,
        }
        for i in range(1, rowspan):
            next_slot = _from_minutes(slot_start_min + i * SLOT_MIN)
            if next_slot in cells and e.program_lane_id in cells[next_slot]:
                cells[next_slot][e.program_lane_id] = {"skip": True}

    # ── 備考レーン構築（レガシー固定列用: program_lane_id が NULL のセットのみ）──
    legacy_ns_ids = [
        ns.id for ns in db.query(PrintNoteSet)
                           .filter(PrintNoteSet.occasion_id == occasion_id,
                                   PrintNoteSet.program_lane_id == None).all()
    ]
    if legacy_ns_ids:
        raw_notes = (db.query(PrintNoteRow)
                     .filter(PrintNoteRow.occasion_id == occasion_id,
                             PrintNoteRow.note_set_id.in_(legacy_ns_ids))
                     .order_by(PrintNoteRow.start_time).all())
    else:
        raw_notes = []

    note_column: dict[str, dict | None] = {s: None for s in slots}
    notes_list = []
    for n in raw_notes:
        ns_name = n.note_set.name if n.note_set else "備考"
        notes_list.append({
            "id": n.id,
            "start_time": n.start_time,
            "end_time": n.end_time,
            "content": n.content,
            "note_set_id": n.note_set_id,
            "note_set_name": ns_name,
            "program_lane_id": None,  # レガシーノート
        })
        n_start = _to_minutes(n.start_time)
        n_end   = _to_minutes(n.end_time)
        rowspan = max(1, (n_end - n_start + SLOT_MIN - 1) // SLOT_MIN)
        slot_key = _from_minutes((n_start // SLOT_MIN) * SLOT_MIN)
        if slot_key not in note_column:
            continue
        # すでに先着エントリがある場合はスキップ
        existing = note_column[slot_key]
        if existing is not None and not existing.get("skip"):
            continue
        note_column[slot_key] = {
            "note": notes_list[-1],
            "rowspan": rowspan,
            "skip": False,
        }
        for i in range(1, rowspan):
            next_slot = _from_minutes(n_start + i * SLOT_MIN)
            if next_slot in note_column:
                note_column[next_slot] = {"skip": True}

    # ── 備考枠レーン：セル構築 ────────────────────────────────
    # lane_type == "remark" のレーンは PrintNoteSet のノートをセルに配置
    for opl in opl_list:
        if opl.program_lane_id not in lane_ids:
            continue
        if opl.program_lane.lane_type != "remark":
            continue
        rl_id = opl.program_lane_id
        note_set = (db.query(PrintNoteSet)
                    .filter_by(occasion_id=occasion_id, program_lane_id=rl_id)
                    .first())
        if not note_set:
            continue
        for n in sorted(note_set.notes, key=lambda x: _to_minutes(x.start_time)):
            ns_name = note_set.name
            note_dict = {
                "id": n.id,
                "start_time": n.start_time,
                "end_time": n.end_time,
                "content": n.content,
                "note_set_id": n.note_set_id,
                "note_set_name": ns_name,
                "program_lane_id": rl_id,
            }
            notes_list.append(note_dict)
            n_start = _to_minutes(n.start_time)
            n_end   = _to_minutes(n.end_time)
            rowspan = max(1, (n_end - n_start + SLOT_MIN - 1) // SLOT_MIN)
            slot_key = _from_minutes((n_start // SLOT_MIN) * SLOT_MIN)
            if slot_key not in cells or rl_id not in cells[slot_key]:
                continue
            cells[slot_key][rl_id] = {"note": note_dict, "rowspan": rowspan, "skip": False}
            for i in range(1, rowspan):
                next_slot = _from_minutes(n_start + i * SLOT_MIN)
                if next_slot in cells and rl_id in cells[next_slot]:
                    cells[next_slot][rl_id] = {"skip": True}

    has_legacy_notes = any(v and v.get("note") for v in note_column.values())

    db.close()
    return {
        "slots": slots,
        "lanes": [{"id": l.id, "name": l.name, "lane_type": l.lane_type} for l in lanes],
        "lane_ids": lane_ids,
        "cells": cells,
        "events": list(event_map.values()),
        "slot_types": slot_types,
        "note_column": note_column,
        "notes": notes_list,
        "has_legacy_notes": has_legacy_notes,
    }


# 後方互換
def build_matrix(occasion_id: int, period: str = "all", lane_ids: list = None) -> dict:
    return build_occasion_matrix(occasion_id, period, lane_ids_filter=lane_ids)
