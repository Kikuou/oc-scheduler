from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from db.database import SessionLocal
from db.models import (Occasion, OccasionProgramLane, OccasionVenue,
                       Venue, Staff, Role, ContentTemplate, ProgramLane, PrintNoteSet)
from sqlalchemy.orm import selectinload
from datetime import date

bp = Blueprint("occasions", __name__)


def get_db():
    return SessionLocal()


@bp.route("/")
def index():
    db = get_db()
    # occasion_program_lanes と program_lane を事前ロード
    occasions = (db.query(Occasion)
                 .options(selectinload(Occasion.occasion_program_lanes)
                          .selectinload(OccasionProgramLane.program_lane))
                 .order_by(Occasion.year.desc(), Occasion.date.desc()).all())
    program_lanes = (db.query(ProgramLane)
                     .filter(ProgramLane.is_active == True)
                     .order_by(ProgramLane.sort_order, ProgramLane.id).all())
    db.close()
    return render_template("index.html", occasions=occasions,
                           program_lanes=program_lanes,
                           current_year=date.today().year)


@bp.route("/occasion/new", methods=["POST"])
def new():
    db = get_db()
    o = Occasion(
        year=int(request.form["year"]),
        date=request.form["date"],
        name=request.form["name"].strip(),
        note=request.form.get("note", "").strip() or None,
        day_start_time=request.form.get("day_start_time", "09:00"),
        day_end_time=request.form.get("day_end_time", "17:00"),
    )
    db.add(o)
    db.flush()

    lane_ids = request.form.getlist("program_lane_ids")
    for i, lid in enumerate(lane_ids):
        db.add(OccasionProgramLane(occasion_id=o.id, program_lane_id=int(lid), sort_order=i))

    db.commit()
    oid = o.id
    db.close()
    flash("開催を作成しました", "success")
    return redirect(url_for("occasions.detail", occasion_id=oid))


@bp.route("/occasion/<int:occasion_id>")
def detail(occasion_id):
    db = get_db()
    # occasion_program_lanes と program_lane を事前ロード（テンプレートで occasion.program_lane_ids 参照のため）
    o = (db.query(Occasion)
         .options(selectinload(Occasion.occasion_program_lanes)
                  .selectinload(OccasionProgramLane.program_lane))
         .filter(Occasion.id == occasion_id)
         .first())
    if not o:
        db.close()
        flash("開催が見つかりません", "error")
        return redirect(url_for("occasions.index"))

    from services.schedule_matrix import build_occasion_matrix
    period = request.args.get("period", "all")
    matrix = build_occasion_matrix(occasion_id, period)

    staff_list = db.query(Staff).filter(Staff.is_active == True).order_by(Staff.sort_order, Staff.id).all()
    roles = db.query(Role).order_by(Role.sort_order, Role.id).all()
    templates = db.query(ContentTemplate).order_by(ContentTemplate.sort_order, ContentTemplate.id).all()
    all_venues = db.query(Venue).filter(Venue.is_active == True).order_by(Venue.sort_order, Venue.id).all()
    all_lanes = (db.query(ProgramLane)
                 .filter(ProgramLane.is_active == True)
                 .order_by(ProgramLane.sort_order, ProgramLane.id).all())

    # 備考セット一覧（note panel のドロップダウン用）
    note_sets_raw = (db.query(PrintNoteSet)
                     .filter_by(occasion_id=occasion_id)
                     .order_by(PrintNoteSet.sort_order).all())
    note_sets = [{"id": ns.id, "name": ns.name} for ns in note_sets_raw]

    # 開催の全実施枠（表示/非表示フラグ付き）― トグルUI用
    all_occasion_lanes = [
        {
            "id": opl.program_lane_id,
            "name": opl.program_lane.name,
            "is_visible": opl.is_visible,
            "lane_type": opl.program_lane.lane_type,
        }
        for opl in sorted(o.occasion_program_lanes, key=lambda x: x.sort_order)
    ]

    db.close()
    return render_template("schedule/matrix.html",
                           occasion=o, matrix=matrix, period=period,
                           staff_list=staff_list, roles=roles,
                           templates=templates,
                           all_venues=all_venues,
                           all_lanes=all_lanes,
                           note_sets=note_sets,
                           all_occasion_lanes=all_occasion_lanes)


@bp.route("/occasion/<int:occasion_id>/edit", methods=["POST"])
def edit(occasion_id):
    db = get_db()
    o = db.get(Occasion, occasion_id)
    if o:
        o.year = int(request.form["year"])
        o.date = request.form["date"]
        o.name = request.form["name"].strip()
        o.note = request.form.get("note", "").strip() or None
        o.day_start_time = request.form.get("day_start_time", o.day_start_time)
        o.day_end_time = request.form.get("day_end_time", o.day_end_time)

        lane_ids = request.form.getlist("program_lane_ids")
        if lane_ids:
            db.query(OccasionProgramLane).filter(OccasionProgramLane.occasion_id == occasion_id).delete()
            for i, lid in enumerate(lane_ids):
                db.add(OccasionProgramLane(occasion_id=occasion_id, program_lane_id=int(lid), sort_order=i))

        db.commit()
        flash("開催情報を更新しました", "success")
    db.close()
    return redirect(url_for("occasions.detail", occasion_id=occasion_id))


@bp.route("/occasion/<int:occasion_id>/delete", methods=["POST"])
def delete(occasion_id):
    db = get_db()
    o = db.get(Occasion, occasion_id)
    if o:
        db.delete(o)
        db.commit()
        flash("開催を削除しました", "success")
    db.close()
    return redirect(url_for("occasions.index"))


@bp.route("/api/occasion/<int:occasion_id>/lanes/reorder", methods=["POST"])
def api_reorder_lanes(occasion_id):
    """実施枠の表示順序を変更する。{"lane_ids": [3, 1, 2, ...]}"""
    data = request.get_json()
    lane_ids = data.get("lane_ids", [])
    db = get_db()
    for i, lid in enumerate(lane_ids):
        opl = db.query(OccasionProgramLane).filter_by(
            occasion_id=occasion_id, program_lane_id=int(lid)
        ).first()
        if opl:
            opl.sort_order = i
    db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.route("/api/occasion/<int:occasion_id>/lane/<int:lane_id>/toggle", methods=["POST"])
def api_toggle_lane(occasion_id, lane_id):
    """実施枠の表示/非表示を切り替える"""
    db = get_db()
    opl = db.query(OccasionProgramLane).filter_by(
        occasion_id=occasion_id, program_lane_id=lane_id
    ).first()
    if not opl:
        db.close()
        return jsonify({"ok": False, "error": "not found"}), 404
    opl.is_visible = not opl.is_visible
    db.commit()
    result = {"ok": True, "is_visible": opl.is_visible}
    db.close()
    return jsonify(result)


@bp.route("/api/occasion/<int:occasion_id>/settings", methods=["POST"])
def api_update_settings(occasion_id):
    data = request.get_json()
    db = get_db()
    o = db.get(Occasion, occasion_id)
    if not o:
        db.close()
        return jsonify({"ok": False}), 404

    if "day_start_time" in data:
        o.day_start_time = data["day_start_time"]
    if "day_end_time" in data:
        o.day_end_time = data["day_end_time"]
    if "program_lane_ids" in data:
        db.query(OccasionProgramLane).filter(OccasionProgramLane.occasion_id == occasion_id).delete()
        for i, lid in enumerate(data["program_lane_ids"]):
            db.add(OccasionProgramLane(occasion_id=occasion_id, program_lane_id=int(lid), sort_order=i))

    db.commit()
    db.close()
    return jsonify({"ok": True})
