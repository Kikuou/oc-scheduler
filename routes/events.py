import uuid as _uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from db.database import SessionLocal
from db.models import Event, EventAssignment, Venue, Staff, Role, ContentTemplate, Occasion, ProgramLane, OccasionProgramLane
from datetime import datetime, timedelta
from services.conflict_checker import check_staff_conflict, check_venue_conflict, check_lane_conflict
from sqlalchemy.orm import selectinload

bp = Blueprint("events", __name__)

LANE_COLORS = [
    ("#d4edfc", "#4a9fd5"),   # 0: 青
    ("#ffe8cc", "#e69500"),   # 1: オレンジ
    ("#d8f0d8", "#3a9a3a"),   # 2: 緑
    ("#f0d8f0", "#9a3a9a"),   # 3: 紫
    ("#f0f0d8", "#9a9a3a"),   # 4: 黄緑
]


def get_db():
    return SessionLocal()


def calc_end_time(start_time: str, duration_min: int) -> str:
    h, m = map(int, start_time.split(":"))
    total = h * 60 + m + duration_min
    return f"{total // 60:02d}:{total % 60:02d}"


# ─── カレンダー画面 ──────────────────────────────────────────
@bp.route("/occasion/<int:occasion_id>/calendar")
def calendar(occasion_id):
    db = get_db()
    o = db.get(Occasion, occasion_id)
    if not o:
        db.close()
        flash("開催が見つかりません", "error")
        return redirect(url_for("occasions.index"))
    venues = db.query(Venue).filter(Venue.is_active == True).order_by(Venue.sort_order, Venue.id).all()
    lanes = db.query(ProgramLane).filter(ProgramLane.is_active == True).order_by(ProgramLane.sort_order, ProgramLane.id).all()
    staff_list = db.query(Staff).filter(Staff.is_active == True).order_by(Staff.sort_order, Staff.id).all()
    roles = db.query(Role).order_by(Role.sort_order, Role.id).all()
    templates = db.query(ContentTemplate).order_by(ContentTemplate.sort_order, ContentTemplate.id).all()
    db.close()
    return render_template("schedule/calendar.html",
                           occasion=o, venues=venues, lanes=lanes,
                           staff_list=staff_list, roles=roles,
                           templates=templates)


# ─── カレンダー用 JSON API ────────────────────────────────────
@bp.route("/api/occasion/<int:occasion_id>/events")
def api_events(occasion_id):
    """FullCalendar用のイベントJSON"""
    db = get_db()
    o = db.get(Occasion, occasion_id)
    if not o:
        db.close()
        return jsonify([])
    opl_list = db.query(OccasionProgramLane).filter_by(occasion_id=occasion_id).order_by(OccasionProgramLane.sort_order).all()
    lane_order = {opl.program_lane_id: i for i, opl in enumerate(opl_list)}
    events = (db.query(Event)
              .options(
                  selectinload(Event.assignments).selectinload(EventAssignment.staff),
                  selectinload(Event.assignments).selectinload(EventAssignment.role),
                  selectinload(Event.venue),
                  selectinload(Event.program_lane),
              )
              .filter(Event.occasion_id == occasion_id)
              .all())
    result = []
    for e in events:
        assignments = [{"staff_name": a.staff.name, "role_name": a.role.name,
                        "staff_id": a.staff_id, "role_id": a.role_id}
                       for a in e.assignments]
        idx = lane_order.get(e.program_lane_id, 0) % 5
        bg, border = LANE_COLORS[idx]
        result.append({
            "id": e.id,
            "title": e.title,
            "start": f"{o.date}T{e.start_time}:00",
            "end": f"{o.date}T{e.end_time}:00",
            "resourceId": e.program_lane_id,
            "extendedProps": {
                "program_lane_id": e.program_lane_id,
                "program_lane_name": e.program_lane.name if e.program_lane else None,
                "venue_id": e.venue_id,
                "venue_name": e.venue.name,
                "duration_min": e.duration_min,
                "note": e.note or "",
                "start_time": e.start_time,
                "end_time": e.end_time,
                "assignments": assignments,
            },
            "backgroundColor": bg,
            "borderColor": border,
            "textColor": "#333",
        })
    db.close()
    return jsonify(result)


@bp.route("/api/occasion/<int:occasion_id>/resources")
def api_resources(occasion_id):
    """FullCalendar リソース用（実施枠一覧）"""
    db = get_db()
    lanes = db.query(ProgramLane).filter(ProgramLane.is_active == True).order_by(ProgramLane.sort_order, ProgramLane.id).all()
    db.close()
    return jsonify([{"id": l.id, "title": l.name} for l in lanes])


# ─── JSON API（作成・更新・削除） ────────────────────────────
@bp.route("/api/event/create", methods=["POST"])
def api_create():
    data = request.get_json()
    db = get_db()
    duration = int(data["duration_min"])
    start = data["start_time"]
    end = calc_end_time(start, duration)
    occasion_id = int(data["occasion_id"])

    # 複数実施枠対応: program_lane_ids（配列）を優先、なければ program_lane_id（後方互換）
    lane_ids_raw = data.get("program_lane_ids") or []
    if not lane_ids_raw and data.get("program_lane_id"):
        lane_ids_raw = [data["program_lane_id"]]
    lane_ids = [int(lid) for lid in lane_ids_raw if lid]

    if not lane_ids:
        db.close()
        return jsonify({"ok": False, "error": "実施枠を1つ以上選択してください"}), 400

    event_type = data.get("event_type", "normal")
    if event_type not in ("normal", "movement"):
        event_type = "normal"

    # 各実施枠の時間重複チェック
    for lid in lane_ids:
        conflicts = check_lane_conflict(occasion_id, start, end, lid)
        if conflicts:
            lane_obj = db.get(ProgramLane, lid)
            lane_name = lane_obj.name if lane_obj else f"ID={lid}"
            c = conflicts[0]
            db.close()
            return jsonify({
                "ok": False,
                "error": f"【{lane_name}】この時間帯には「{c['title']}」（{c['start']}〜{c['end']}）がすでに登録されています。同じ実施枠内で時間が重複するイベントは登録できません。"
            }), 409

    # 複数実施枠の場合はグループIDを生成
    group_id = str(_uuid.uuid4()) if len(lane_ids) > 1 else None

    # 移動イベントの場合、担当者の役割を「移動引率」に固定
    assignments_data = data.get("assignments", [])
    if event_type == "movement":
        from sqlalchemy import text as _text
        with db.bind.connect() as _conn:
            row = _conn.execute(_text("SELECT id FROM roles WHERE name = '移動引率' LIMIT 1")).fetchone()
            movement_role_id = row[0] if row else None
        if movement_role_id:
            assignments_data = [
                {"staff_id": a["staff_id"], "role_id": movement_role_id}
                for a in assignments_data if a.get("staff_id")
            ]

    venue_id_raw = data.get("venue_id")
    venue_id = int(venue_id_raw) if venue_id_raw else None

    created_ids = []
    for lid in lane_ids:
        e = Event(
            occasion_id=occasion_id,
            program_lane_id=lid,
            venue_id=venue_id,
            start_time=start,
            end_time=end,
            duration_min=duration,
            title=data["title"].strip(),
            note=(data.get("note") or "").strip() or None,
            event_group_id=group_id,
            event_type=event_type,
        )
        db.add(e)
        db.flush()
        for a in assignments_data:
            if a.get("staff_id") and a.get("role_id"):
                db.add(EventAssignment(
                    event_id=e.id,
                    staff_id=int(a["staff_id"]),
                    role_id=int(a["role_id"]),
                ))
        created_ids.append(e.id)

    db.commit()
    db.close()
    return jsonify({"ok": True, "ids": created_ids})


@bp.route("/api/event/<int:event_id>/update", methods=["POST"])
def api_update(event_id):
    data = request.get_json()
    db = get_db()
    e = db.get(Event, event_id)
    if not e:
        db.close()
        return jsonify({"ok": False, "error": "not found"}), 404

    duration = int(data["duration_min"])
    start = data["start_time"]
    end = calc_end_time(start, duration)

    # グループ内の全イベントを取得
    if e.event_group_id:
        siblings = db.query(Event).filter(Event.event_group_id == e.event_group_id).all()
    else:
        siblings = [e]
    sibling_ids = {sib.id for sib in siblings}

    # 新しい実施枠リスト（複数実施枠対応）
    lane_ids_raw = data.get("program_lane_ids") or []
    if not lane_ids_raw and data.get("program_lane_id"):
        lane_ids_raw = [data["program_lane_id"]]
    new_lane_ids = [int(lid) for lid in lane_ids_raw if lid]

    if not new_lane_ids:
        db.close()
        return jsonify({"ok": False, "error": "実施枠を1つ以上選択してください"}), 400

    event_type = data.get("event_type", e.event_type or "normal")
    if event_type not in ("normal", "movement"):
        event_type = "normal"

    # 各実施枠の重複チェック（グループ内イベントを全て除外）
    for lid in new_lane_ids:
        conflicts = check_lane_conflict(
            e.occasion_id, start, end, lid, exclude_event_ids=sibling_ids
        )
        if conflicts:
            lane_obj = db.get(ProgramLane, lid)
            lane_name = lane_obj.name if lane_obj else f"ID={lid}"
            c = conflicts[0]
            db.close()
            return jsonify({
                "ok": False,
                "error": f"【{lane_name}】この時間帯には「{c['title']}」（{c['start']}〜{c['end']}）がすでに登録されています。同じ実施枠内で時間が重複するイベントは登録できません。"
            }), 409

    # 新グループID決定（複数→グループID維持 or 新規生成、単数→クリア）
    if len(new_lane_ids) > 1:
        new_group_id = e.event_group_id or str(_uuid.uuid4())
    else:
        new_group_id = None

    # 移動イベントの場合、担当者の役割を「移動引率」に固定
    assignments_data = data.get("assignments", [])
    if event_type == "movement":
        from sqlalchemy import text as _text
        with db.bind.connect() as _conn:
            row = _conn.execute(_text("SELECT id FROM roles WHERE name = '移動引率' LIMIT 1")).fetchone()
            movement_role_id = row[0] if row else None
        if movement_role_id:
            assignments_data = [
                {"staff_id": a["staff_id"], "role_id": movement_role_id}
                for a in assignments_data if a.get("staff_id")
            ]

    venue_id_raw = data.get("venue_id")
    venue_id = int(venue_id_raw) if venue_id_raw else None

    existing_lane_map = {sib.program_lane_id: sib for sib in siblings}

    # 削除された実施枠のイベントを削除
    for sib in siblings:
        if sib.program_lane_id not in new_lane_ids:
            db.delete(sib)
    db.flush()

    # 既存実施枠を更新、新規実施枠はイベントを作成
    for lid in new_lane_ids:
        common_fields = {
            "venue_id": venue_id,
            "start_time": start,
            "end_time": end,
            "duration_min": duration,
            "title": data["title"].strip(),
            "note": (data.get("note") or "").strip() or None,
            "event_group_id": new_group_id,
            "event_type": event_type,
        }
        if lid in existing_lane_map:
            sib = existing_lane_map[lid]
            for k, v in common_fields.items():
                setattr(sib, k, v)
            for a in sib.assignments:
                db.delete(a)
            db.flush()
            target_id = sib.id
        else:
            new_e = Event(occasion_id=e.occasion_id, program_lane_id=lid, **common_fields)
            db.add(new_e)
            db.flush()
            target_id = new_e.id

        for a in assignments_data:
            if a.get("staff_id") and a.get("role_id"):
                db.add(EventAssignment(
                    event_id=target_id,
                    staff_id=int(a["staff_id"]),
                    role_id=int(a["role_id"]),
                ))

    db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.route("/api/event/<int:event_id>/move", methods=["POST"])
def api_move(event_id):
    """ドラッグ＆ドロップによる移動・リサイズ"""
    data = request.get_json()
    db = get_db()
    e = db.get(Event, event_id)
    if not e:
        db.close()
        return jsonify({"ok": False}), 404

    if "start_time" in data:
        e.start_time = data["start_time"]
    if "end_time" in data:
        e.end_time = data["end_time"]
    if "venue_id" in data:
        e.venue_id = int(data["venue_id"])
    if data.get("program_lane_id"):
        e.program_lane_id = int(data["program_lane_id"])

    h1, m1 = map(int, e.start_time.split(":"))
    h2, m2 = map(int, e.end_time.split(":"))
    e.duration_min = (h2 * 60 + m2) - (h1 * 60 + m1)

    db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.route("/api/event/<int:event_id>/delete", methods=["POST"])
def api_delete(event_id):
    data = request.get_json() or {}
    scope = data.get("scope", "all")  # "all"=グループ全削除 / "this"=このイベントのみ
    db = get_db()
    e = db.get(Event, event_id)
    if not e:
        db.close()
        return jsonify({"ok": False}), 404

    if scope == "all" and e.event_group_id:
        # グループ内の全イベントを削除
        siblings = db.query(Event).filter(Event.event_group_id == e.event_group_id).all()
        for sib in siblings:
            db.delete(sib)
    else:
        # このイベントのみ削除。残り1件になる場合はグループIDをクリア
        if e.event_group_id:
            remaining = db.query(Event).filter(
                Event.event_group_id == e.event_group_id,
                Event.id != event_id
            ).all()
            if len(remaining) == 1:
                remaining[0].event_group_id = None
        db.delete(e)

    db.commit()
    db.close()
    return jsonify({"ok": True})


# ─── フォーム版 ────────────────────────────────────────────
@bp.route("/occasion/<int:occasion_id>/event/new")
def new(occasion_id):
    db = get_db()
    o = db.get(Occasion, occasion_id)
    venues = db.query(Venue).filter(Venue.is_active == True).order_by(Venue.sort_order, Venue.id).all()
    lanes = db.query(ProgramLane).filter(ProgramLane.is_active == True).order_by(ProgramLane.sort_order, ProgramLane.id).all()
    staff_list = db.query(Staff).filter(Staff.is_active == True).order_by(Staff.staff_type, Staff.name).all()
    roles = db.query(Role).order_by(Role.name).all()
    templates = db.query(ContentTemplate).order_by(ContentTemplate.title).all()
    db.close()
    return render_template("schedule/event_form.html",
                           occasion=o, event=None,
                           venues=venues, lanes=lanes,
                           staff_list=staff_list,
                           roles=roles, templates=templates,
                           assignments=[])


@bp.route("/occasion/<int:occasion_id>/event/new", methods=["POST"])
def create(occasion_id):
    db = get_db()
    duration = int(request.form["duration_min"])
    start = request.form["start_time"]
    end = calc_end_time(start, duration)

    e = Event(
        occasion_id=occasion_id,
        program_lane_id=int(request.form["program_lane_id"]) if request.form.get("program_lane_id") else None,
        venue_id=int(request.form["venue_id"]),
        start_time=start,
        end_time=end,
        duration_min=duration,
        title=request.form["title"].strip(),
        note=request.form.get("note", "").strip() or None,
    )
    db.add(e)
    db.flush()

    staff_ids = request.form.getlist("staff_id[]")
    role_ids = request.form.getlist("role_id[]")
    for sid, rid in zip(staff_ids, role_ids):
        if sid and rid:
            db.add(EventAssignment(event_id=e.id, staff_id=int(sid), role_id=int(rid)))

    db.commit()
    db.close()
    flash("イベントを登録しました", "success")
    return redirect(url_for("occasions.detail", occasion_id=occasion_id))


@bp.route("/event/<int:event_id>/edit")
def edit(event_id):
    db = get_db()
    e = db.get(Event, event_id)
    if not e:
        db.close()
        flash("イベントが見つかりません", "error")
        return redirect(url_for("occasions.index"))
    venues = db.query(Venue).filter(Venue.is_active == True).order_by(Venue.sort_order, Venue.id).all()
    lanes = db.query(ProgramLane).filter(ProgramLane.is_active == True).order_by(ProgramLane.sort_order, ProgramLane.id).all()
    staff_list = db.query(Staff).filter(Staff.is_active == True).order_by(Staff.staff_type, Staff.name).all()
    roles = db.query(Role).order_by(Role.name).all()
    templates = db.query(ContentTemplate).order_by(ContentTemplate.title).all()
    assignments = [{"staff_id": a.staff_id, "role_id": a.role_id,
                    "staff_name": a.staff.name, "role_name": a.role.name}
                   for a in e.assignments]
    occasion = e.occasion
    db.close()
    return render_template("schedule/event_form.html",
                           occasion=occasion, event=e,
                           venues=venues, lanes=lanes,
                           staff_list=staff_list,
                           roles=roles, templates=templates,
                           assignments=assignments)


@bp.route("/event/<int:event_id>/edit", methods=["POST"])
def update(event_id):
    db = get_db()
    e = db.get(Event, event_id)
    if not e:
        db.close()
        flash("イベントが見つかりません", "error")
        return redirect(url_for("occasions.index"))

    duration = int(request.form["duration_min"])
    start = request.form["start_time"]
    end = calc_end_time(start, duration)

    if request.form.get("program_lane_id"):
        e.program_lane_id = int(request.form["program_lane_id"])
    e.venue_id = int(request.form["venue_id"])
    e.start_time = start
    e.end_time = end
    e.duration_min = duration
    e.title = request.form["title"].strip()
    e.note = request.form.get("note", "").strip() or None

    for a in e.assignments:
        db.delete(a)
    db.flush()

    staff_ids = request.form.getlist("staff_id[]")
    role_ids = request.form.getlist("role_id[]")
    for sid, rid in zip(staff_ids, role_ids):
        if sid and rid:
            db.add(EventAssignment(event_id=e.id, staff_id=int(sid), role_id=int(rid)))

    db.commit()
    occasion_id = e.occasion_id
    db.close()
    flash("イベントを更新しました", "success")
    return redirect(url_for("occasions.detail", occasion_id=occasion_id))


@bp.route("/event/<int:event_id>/delete", methods=["POST"])
def delete(event_id):
    db = get_db()
    e = db.get(Event, event_id)
    if e:
        occasion_id = e.occasion_id
        db.delete(e)
        db.commit()
        db.close()
        flash("イベントを削除しました", "success")
        return redirect(url_for("occasions.detail", occasion_id=occasion_id))
    db.close()
    return redirect(url_for("occasions.index"))


# ─── 重複チェックAPI ─────────────────────────────────────────
@bp.route("/api/conflict/staff")
def api_conflict_staff():
    occasion_id = int(request.args["occasion_id"])
    start = request.args["start_time"]
    end = request.args["end_time"]
    staff_id = int(request.args["staff_id"])
    exclude = request.args.get("exclude_event_id")
    exclude_id = int(exclude) if exclude else None
    conflicts = check_staff_conflict(occasion_id, start, end, staff_id, exclude_id)
    return jsonify({"conflicts": conflicts})


@bp.route("/api/conflict/venue")
def api_conflict_venue():
    occasion_id = int(request.args["occasion_id"])
    start = request.args["start_time"]
    end = request.args["end_time"]
    venue_id = int(request.args["venue_id"])
    exclude = request.args.get("exclude_event_id")
    exclude_id = int(exclude) if exclude else None
    conflicts = check_venue_conflict(occasion_id, start, end, venue_id, exclude_id)
    return jsonify({"conflicts": conflicts})


@bp.route("/api/conflict/lane")
def api_conflict_lane():
    occasion_id = int(request.args["occasion_id"])
    start = request.args["start_time"]
    end = request.args["end_time"]
    lane_id = int(request.args["program_lane_id"])
    exclude = request.args.get("exclude_event_id")
    exclude_id = int(exclude) if exclude else None
    conflicts = check_lane_conflict(occasion_id, start, end, lane_id, exclude_id)
    return jsonify({"conflicts": conflicts})
