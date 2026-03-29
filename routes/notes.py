"""備考（PrintNoteRow）CRUD API"""
from flask import Blueprint, request, jsonify
from db.database import SessionLocal
from db.models import PrintNoteRow, PrintNoteSet
from services.schedule_matrix import _to_minutes, _from_minutes

bp = Blueprint("notes", __name__)


def get_db():
    return SessionLocal()


def _ensure_default_set(db, occasion_id: int, note_set_id=None) -> int:
    """note_set_id が指定されていない場合、'備考' デフォルトセットを取得または作成"""
    if note_set_id:
        return int(note_set_id)
    ns = db.query(PrintNoteSet).filter_by(occasion_id=occasion_id, name="備考").first()
    if not ns:
        ns = PrintNoteSet(occasion_id=occasion_id, name="備考", sort_order=0)
        db.add(ns)
        db.flush()
    return ns.id


def _ensure_remark_lane_set(db, occasion_id: int, program_lane_id: int) -> int:
    """備考枠専用の PrintNoteSet を取得または作成する"""
    ns = db.query(PrintNoteSet).filter_by(
        occasion_id=occasion_id,
        program_lane_id=program_lane_id
    ).first()
    if not ns:
        from db.models import ProgramLane
        pl = db.get(ProgramLane, program_lane_id)
        name = pl.name if pl else "備考"
        count = db.query(PrintNoteSet).filter_by(occasion_id=occasion_id).count()
        ns = PrintNoteSet(
            occasion_id=occasion_id,
            program_lane_id=program_lane_id,
            name=name,
            sort_order=count,
        )
        db.add(ns)
        db.flush()
    return ns.id


@bp.route("/api/note/create", methods=["POST"])
def create_note():
    data = request.get_json() or {}
    occasion_id     = data.get("occasion_id")
    start_time      = (data.get("start_time") or "").strip()
    end_time        = (data.get("end_time")   or "").strip()
    content         = (data.get("content")    or "").strip()
    note_set_id     = data.get("note_set_id")
    program_lane_id = data.get("program_lane_id")

    if not occasion_id or not start_time or not end_time or not content:
        return jsonify({"ok": False, "error": "occasion_id / start_time / end_time / content が必要です"})
    if _to_minutes(end_time) <= _to_minutes(start_time):
        return jsonify({"ok": False, "error": "終了時刻は開始時刻より後にしてください"})

    db = get_db()
    if program_lane_id:
        nsid = _ensure_remark_lane_set(db, int(occasion_id), int(program_lane_id))
    else:
        nsid = _ensure_default_set(db, occasion_id, note_set_id)
    note = PrintNoteRow(
        note_set_id=nsid,
        occasion_id=int(occasion_id),
        start_time=start_time,
        end_time=end_time,
        content=content,
    )
    db.add(note)
    db.commit()
    result = {"ok": True, "id": note.id}
    db.close()
    return jsonify(result)


@bp.route("/api/note/<int:note_id>/update", methods=["POST"])
def update_note(note_id):
    data = request.get_json() or {}
    db = get_db()
    note = db.get(PrintNoteRow, note_id)
    if not note:
        db.close()
        return jsonify({"ok": False, "error": "not found"})

    if "start_time" in data:
        note.start_time = data["start_time"]
    if "end_time" in data:
        note.end_time = data["end_time"]
    if "duration_min" in data:
        note.end_time = _from_minutes(_to_minutes(note.start_time) + int(data["duration_min"]))
    if "content" in data:
        ct = data["content"].strip()
        if ct:
            note.content = ct
    if "note_set_id" in data and data["note_set_id"]:
        note.note_set_id = int(data["note_set_id"])

    db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.route("/api/note/<int:note_id>/delete", methods=["POST"])
def delete_note(note_id):
    db = get_db()
    note = db.get(PrintNoteRow, note_id)
    if not note:
        db.close()
        return jsonify({"ok": False, "error": "not found"})
    db.delete(note)
    db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.route("/api/note-set/create", methods=["POST"])
def create_note_set():
    data = request.get_json() or {}
    occasion_id = data.get("occasion_id")
    name = (data.get("name") or "").strip()
    if not occasion_id or not name:
        return jsonify({"ok": False, "error": "occasion_id と name が必要です"})
    db = get_db()
    # 既存チェック
    existing = db.query(PrintNoteSet).filter_by(occasion_id=int(occasion_id), name=name).first()
    if existing:
        db.close()
        return jsonify({"ok": True, "id": existing.id, "name": existing.name})
    count = db.query(PrintNoteSet).filter_by(occasion_id=int(occasion_id)).count()
    ns = PrintNoteSet(occasion_id=int(occasion_id), name=name, sort_order=count)
    db.add(ns)
    db.commit()
    result = {"ok": True, "id": ns.id, "name": ns.name}
    db.close()
    return jsonify(result)
