from datetime import date
from flask import Blueprint, render_template, send_file, abort, request, jsonify
from db.database import SessionLocal
from db.models import Occasion, Staff, PrintNoteSet, PrintNoteRow
from services.schedule_matrix import build_matrix, _to_minutes, _from_minutes
from services.pdf_generator import generate_stafflist_pdf
from collections import defaultdict

bp = Blueprint("reports", __name__)


def get_db():
    return SessionLocal()


# ─────────────────────────────────────────────
# 内部ユーティリティ
# ─────────────────────────────────────────────

def _build_groups(assignments):
    """EventAssignment リストをセッション内で dict 化（lazy load 対策）"""
    groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    staff_info = {}
    for a in assignments:
        s = a.staff
        if s.id not in staff_info:
            staff_info[s.id] = {
                "id": s.id, "name": s.name,
                "staff_type": s.staff_type,
                "department": s.department,
                "grade": s.grade,
            }
        key = (s.department or "", s.grade or 0)
        groups[s.staff_type][key][s.id].append({
            "event": {
                "start_time": a.event.start_time,
                "end_time": a.event.end_time,
                "title": a.event.title,
                "note": a.event.note,
                "venue": {"name": a.event.venue.name},
            },
            "role": {"name": a.role.name},
        })
    return groups, staff_info


def _gen_30min_slots(start: str, end: str) -> list:
    """開催時間帯から30分刻みのスロットリストを生成"""
    s = (_to_minutes(start) // 30) * 30
    e = (_to_minutes(end) // 30) * 30 + 30
    slots, t = [], s
    while t <= e:
        slots.append(_from_minutes(t))
        t += 30
    return slots


def _build_note_col(notes: list, slots: list) -> tuple:
    """
    備考データ（新構造: start_time/end_time）をrowspan込みで構築する。

    Parameters:
        notes: list of {"start_time": "HH:MM", "end_time": "HH:MM", "content": str}
        slots: 全スロットのリスト（順序付き、5分刻み）

    Returns:
        note_col:  {anchor_slot: {"content": str, "rowspan": int}}
        note_skip: set of slot strings covered by a rowspan above
    """
    note_col, note_skip = {}, set()
    if not slots or not notes:
        return note_col, note_skip

    for note in sorted(notes, key=lambda n: _to_minutes(n["start_time"])):
        n_start = _to_minutes(note["start_time"])
        n_end   = _to_minutes(note["end_time"])

        # このノートがカバーするスロットを特定
        covered = [s for s in slots if n_start <= _to_minutes(s) < n_end]
        if not covered:
            continue

        anchor = covered[0]
        note_col[anchor] = {"content": note["content"], "rowspan": len(covered)}
        for s in covered[1:]:
            note_skip.add(s)

    return note_col, note_skip


# ─────────────────────────────────────────────
# ルート: 帳票出力トップ（選択画面）
# ─────────────────────────────────────────────

@bp.route("/report/<int:occasion_id>")
def preview(occasion_id):
    db = get_db()
    o = db.get(Occasion, occasion_id)
    if not o:
        db.close()
        abort(404)

    # 実施枠リスト（is_visible を含める：帳票では全列を選択肢に表示しデフォルトチェックを visible のみに）
    lanes = [
        {
            "id": opl.program_lane_id,
            "name": opl.program_lane.name,
            "is_visible": opl.is_visible,
        }
        for opl in sorted(o.occasion_program_lanes, key=lambda x: x.sort_order)
    ]

    # 備考セット（セッション内でdict化）
    raw_sets = db.query(PrintNoteSet).filter_by(occasion_id=occasion_id)\
                 .order_by(PrintNoteSet.sort_order).all()
    note_sets = []
    for ns in raw_sets:
        note_sets.append({
            "id": ns.id, "name": ns.name,
            "notes": [
                {"id": n.id, "start_time": n.start_time,
                 "end_time": n.end_time, "content": n.content}
                for n in ns.notes
            ],
        })

    time_slots_30 = _gen_30min_slots(o.day_start_time, o.day_end_time)

    db.close()
    return render_template(
        "reports/preview.html",
        occasion=o,
        lanes=lanes,
        note_sets=note_sets,
        time_slots_30=time_slots_30,
    )


# ─────────────────────────────────────────────
# ルート: スケジュール表印刷（新版）
#   /report/<id>/print?lanes=1,2&noteset=3
# ─────────────────────────────────────────────

@bp.route("/report/<int:occasion_id>/print")
def print_schedule(occasion_id):
    db = get_db()
    o = db.get(Occasion, occasion_id)
    if not o:
        db.close()
        abort(404)

    # ── 実施枠フィルタ ──
    lanes_param = request.args.get("lanes", "")
    if lanes_param:
        selected_ids = [int(x) for x in lanes_param.split(",") if x.strip().isdigit()]
    else:
        selected_ids = o.program_lane_ids

    db.close()

    # ── マトリクス生成（選択列のみ・期間フィルタなし） ──
    matrix = build_matrix(occasion_id, "all", lane_ids=selected_ids)

    # ── 列を最大4列ずつページ分割 ──
    all_lanes = matrix["lanes"]
    lane_pages = [all_lanes[i:i+4] for i in range(0, max(len(all_lanes), 1), 4)]

    return render_template(
        "reports/print_schedule.html",
        occasion=o,
        matrix=matrix,
        lane_pages=lane_pages,
        today=date.today().strftime("%Y-%m-%d"),
    )


# 旧URLとの後方互換（リダイレクト的に処理）
@bp.route("/report/<int:occasion_id>/print/schedule")
def print_schedule_legacy(occasion_id):
    return print_schedule(occasion_id)


# ─────────────────────────────────────────────
# ルート: 担当者一覧印刷（既存・維持）
# ─────────────────────────────────────────────

@bp.route("/report/<int:occasion_id>/print/stafflist")
def print_stafflist(occasion_id):
    db = get_db()
    o = db.get(Occasion, occasion_id)
    if not o:
        db.close()
        abort(404)
    from db.models import EventAssignment, Event
    assignments = (db.query(EventAssignment)
                   .join(Event)
                   .filter(Event.occasion_id == occasion_id)
                   .order_by(Event.start_time)
                   .all())
    groups, staff_info = _build_groups(assignments)
    db.close()
    return render_template("reports/print_stafflist.html",
                           occasion=o, groups=groups,
                           staff_info=staff_info,
                           staff_order=["教員", "職員", "学生"])


# ─────────────────────────────────────────────
# ルート: PDFダウンロード（既存・維持）
# ─────────────────────────────────────────────

@bp.route("/report/<int:occasion_id>/pdf/schedule")
def pdf_schedule(occasion_id):
    from services.pdf_generator import generate_schedule_pdf
    db = get_db()
    o = db.get(Occasion, occasion_id)
    if not o:
        db.close()
        abort(404)
    db.close()
    buf = generate_schedule_pdf(occasion_id)
    filename = f"OC_schedule_{o.year}_{o.name}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


@bp.route("/report/<int:occasion_id>/pdf/stafflist")
def pdf_stafflist(occasion_id):
    db = get_db()
    o = db.get(Occasion, occasion_id)
    if not o:
        db.close()
        abort(404)
    db.close()
    buf = generate_stafflist_pdf(occasion_id)
    filename = f"OC_stafflist_{o.year}_{o.name}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)
