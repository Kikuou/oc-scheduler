from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from db.database import SessionLocal
from db.models import Staff, Venue, Role, ContentTemplate, ProgramLane, EventAssignment, Event, OccasionProgramLane
import csv
import io
import json
import os
import uuid
import tempfile

bp = Blueprint("master", __name__)

STAFF_TYPES = ["教員", "職員", "学生"]
DEPARTMENTS = ["食物栄養学科", "こども地域学科"]

# CSV取込用の定数
_VALID_STAFF_TYPES = {"教員", "職員", "学生"}
_VALID_TEACHER_DEPTS = {"食物栄養学科", "こども地域学科"}
_AFFILIATION_PARSE = {
    "食物栄養学科1年":   ("食物栄養学科", 1),
    "食物栄養学科2年":   ("食物栄養学科", 2),
    "こども地域学科1年": ("こども地域学科", 1),
    "こども地域学科2年": ("こども地域学科", 2),
    "食物栄養学科":      ("食物栄養学科", None),
    "こども地域学科":    ("こども地域学科", None),
}


def _parse_csv_row(row_num, row, existing_names, csv_seen):
    """1行をパースしてステータス付き辞書を返す"""
    name        = (row.get("氏名")    or "").strip()
    staff_type  = (row.get("区分")    or "").strip()
    affiliation = (row.get("所属詳細") or "").strip()
    note        = (row.get("備考")    or "").strip()

    errors = []
    department = None
    grade = None

    # ── バリデーション ──────────────────────────────────────
    if not name:
        errors.append("氏名が空欄です")

    if not staff_type:
        errors.append("区分が空欄です")
    elif staff_type not in _VALID_STAFF_TYPES:
        errors.append(f"区分「{staff_type}」は無効です（教員 / 職員 / 学生）")

    if staff_type in _VALID_STAFF_TYPES:
        if staff_type == "学生":
            if affiliation not in _AFFILIATION_PARSE:
                errors.append(
                    f"所属詳細「{affiliation}」は無効です"
                    "（食物栄養学科1年 / 食物栄養学科2年 / こども地域学科1年 / こども地域学科2年）"
                )
            else:
                department, grade = _AFFILIATION_PARSE[affiliation]
        elif staff_type == "教員":
            if affiliation and affiliation not in _VALID_TEACHER_DEPTS:
                errors.append(f"所属詳細「{affiliation}」は無効です（食物栄養学科 / こども地域学科 / 空欄）")
            else:
                department = affiliation or None
        else:  # 職員
            department = affiliation or None  # 職員は所属詳細を柔軟に受け入れ

    # CSV内重複チェック
    csv_key = (name, staff_type)
    is_dup_csv = csv_key in csv_seen
    if name and staff_type in _VALID_STAFF_TYPES:
        if is_dup_csv:
            errors.append("このCSV内に同じ氏名＋区分の行が重複しています")
        else:
            csv_seen.add(csv_key)

    # DB既存チェック
    is_existing = bool(name) and name in existing_names

    if errors:
        status = "error"
    elif is_existing:
        status = "existing"
    else:
        status = "ok"

    return {
        "row_num":    row_num,
        "name":       name,
        "staff_type": staff_type,
        "affiliation": affiliation,
        "department": department,
        "grade":      grade,
        "note":       note,
        "errors":     errors,
        "is_existing": is_existing,
        "status":     status,
    }


def get_db():
    return SessionLocal()


# ─── メイン画面 ───────────────────────────────────────────────
@bp.route("/master")
def index():
    db = get_db()
    tab = request.args.get("tab", "staff")
    staff_list = db.query(Staff).order_by(Staff.sort_order, Staff.id).all()
    venues = db.query(Venue).order_by(Venue.sort_order, Venue.id).all()
    roles = db.query(Role).order_by(Role.sort_order, Role.id).all()
    templates = db.query(ContentTemplate).order_by(ContentTemplate.sort_order, ContentTemplate.id).all()
    program_lanes = db.query(ProgramLane).order_by(ProgramLane.sort_order, ProgramLane.id).all()
    db.close()
    return render_template("master/index.html",
                           staff_list=staff_list, venues=venues,
                           roles=roles, templates=templates,
                           program_lanes=program_lanes,
                           active_tab=tab,
                           staff_types=STAFF_TYPES,
                           departments=DEPARTMENTS)


# ─── 担当者 CRUD ──────────────────────────────────────────────
@bp.route("/master/staff/add", methods=["POST"])
def staff_add():
    db = get_db()
    grade = request.form.get("grade") or None
    s = Staff(
        name=request.form["name"].strip(),
        staff_type=request.form["staff_type"],
        department=request.form.get("department") or None,
        grade=int(grade) if grade else None,
        note=request.form.get("note", "").strip() or None,
    )
    db.add(s)
    db.commit()
    db.close()
    flash("担当者を追加しました", "success")
    return redirect(url_for("master.index", tab="staff"))


@bp.route("/master/staff/<int:sid>/edit", methods=["POST"])
def staff_edit(sid):
    db = get_db()
    s = db.get(Staff, sid)
    if not s:
        db.close()
        flash("担当者が見つかりません", "error")
        return redirect(url_for("master.index", tab="staff"))
    grade = request.form.get("grade") or None
    s.name = request.form["name"].strip()
    s.staff_type = request.form["staff_type"]
    s.department = request.form.get("department") or None
    s.grade = int(grade) if grade else None
    s.note = request.form.get("note", "").strip() or None
    db.commit()
    db.close()
    flash("担当者を更新しました", "success")
    return redirect(url_for("master.index", tab="staff"))


@bp.route("/master/staff/<int:sid>/toggle", methods=["POST"])
def staff_toggle(sid):
    db = get_db()
    s = db.get(Staff, sid)
    if s:
        s.is_active = not s.is_active
        db.commit()
    db.close()
    return redirect(url_for("master.index", tab="staff"))


@bp.route("/master/staff/<int:sid>/delete", methods=["POST"])
def staff_delete(sid):
    db = get_db()
    s = db.get(Staff, sid)
    if s:
        db.delete(s)
        db.commit()
    db.close()
    flash("担当者を削除しました", "success")
    return redirect(url_for("master.index", tab="staff"))


# ─── 会場 CRUD ────────────────────────────────────────────────
@bp.route("/master/venue/add", methods=["POST"])
def venue_add():
    db = get_db()
    max_order = db.query(Venue).count()
    v = Venue(
        name=request.form["name"].strip(),
        capacity=int(request.form["capacity"]) if request.form.get("capacity") else None,
        sort_order=max_order,
    )
    db.add(v)
    db.commit()
    db.close()
    flash("会場を追加しました", "success")
    return redirect(url_for("master.index", tab="venue"))


@bp.route("/master/venue/<int:vid>/edit", methods=["POST"])
def venue_edit(vid):
    db = get_db()
    v = db.get(Venue, vid)
    if v:
        v.name = request.form["name"].strip()
        v.capacity = int(request.form["capacity"]) if request.form.get("capacity") else None
        db.commit()
    db.close()
    flash("会場を更新しました", "success")
    return redirect(url_for("master.index", tab="venue"))


@bp.route("/master/venue/<int:vid>/toggle", methods=["POST"])
def venue_toggle(vid):
    db = get_db()
    v = db.get(Venue, vid)
    if v:
        v.is_active = not v.is_active
        db.commit()
    db.close()
    return redirect(url_for("master.index", tab="venue"))


@bp.route("/master/venue/<int:vid>/delete", methods=["POST"])
def venue_delete(vid):
    db = get_db()
    v = db.get(Venue, vid)
    if v:
        db.delete(v)
        db.commit()
    db.close()
    flash("会場を削除しました", "success")
    return redirect(url_for("master.index", tab="venue"))


# ─── 役割 CRUD ────────────────────────────────────────────────
@bp.route("/master/role/add", methods=["POST"])
def role_add():
    db = get_db()
    r = Role(name=request.form["name"].strip())
    db.add(r)
    db.commit()
    db.close()
    flash("役割を追加しました", "success")
    return redirect(url_for("master.index", tab="role"))


@bp.route("/master/role/<int:rid>/edit", methods=["POST"])
def role_edit(rid):
    db = get_db()
    r = db.get(Role, rid)
    if r:
        r.name = request.form["name"].strip()
        db.commit()
    db.close()
    flash("役割を更新しました", "success")
    return redirect(url_for("master.index", tab="role"))


@bp.route("/master/role/<int:rid>/delete", methods=["POST"])
def role_delete(rid):
    db = get_db()
    r = db.get(Role, rid)
    if r:
        db.delete(r)
        db.commit()
    db.close()
    flash("役割を削除しました", "success")
    return redirect(url_for("master.index", tab="role"))


# ─── テンプレート CRUD ────────────────────────────────────────
@bp.route("/master/template/add", methods=["POST"])
def template_add():
    db = get_db()
    t = ContentTemplate(
        title=request.form["title"].strip(),
        duration_min=int(request.form["duration_min"]) if request.form.get("duration_min") else None,
        note=request.form.get("note", "").strip() or None,
    )
    db.add(t)
    db.commit()
    db.close()
    flash("テンプレートを追加しました", "success")
    return redirect(url_for("master.index", tab="template"))


@bp.route("/master/template/<int:tid>/edit", methods=["POST"])
def template_edit(tid):
    db = get_db()
    t = db.get(ContentTemplate, tid)
    if t:
        t.title = request.form["title"].strip()
        t.duration_min = int(request.form["duration_min"]) if request.form.get("duration_min") else None
        t.note = request.form.get("note", "").strip() or None
        db.commit()
    db.close()
    flash("テンプレートを更新しました", "success")
    return redirect(url_for("master.index", tab="template"))


@bp.route("/master/template/<int:tid>/delete", methods=["POST"])
def template_delete(tid):
    db = get_db()
    t = db.get(ContentTemplate, tid)
    if t:
        db.delete(t)
        db.commit()
    db.close()
    flash("テンプレートを削除しました", "success")
    return redirect(url_for("master.index", tab="template"))


# ─── 実施枠 CRUD ──────────────────────────────────────────────
@bp.route("/master/lane/add", methods=["POST"])
def lane_add():
    db = get_db()
    max_order = db.query(ProgramLane).count()
    lane_type = request.form.get("lane_type", "normal")
    if lane_type not in ("normal", "remark"):
        lane_type = "normal"
    pl = ProgramLane(
        name=request.form["name"].strip(),
        sort_order=max_order,
        lane_type=lane_type,
    )
    db.add(pl)
    db.commit()
    db.close()
    flash("実施枠を追加しました", "success")
    return redirect(url_for("master.index", tab="lane"))


@bp.route("/master/lane/<int:lid>/edit", methods=["POST"])
def lane_edit(lid):
    db = get_db()
    pl = db.get(ProgramLane, lid)
    if not pl:
        db.close()
        flash("実施枠が見つかりません", "error")
        return redirect(url_for("master.index", tab="lane"))
    try:
        pl.name = request.form["name"].strip()
        if "lane_type" in request.form:
            lt = request.form["lane_type"]
            if lt in ("normal", "remark"):
                pl.lane_type = lt
        db.commit()
        flash("実施枠を更新しました", "success")
    except Exception as e:
        db.rollback()
        err = str(e)
        if "unique" in err.lower() or "duplicate" in err.lower():
            flash("同じ名前の実施枠がすでに存在します", "error")
        else:
            flash(f"更新に失敗しました: {err}", "error")
    finally:
        db.close()
    return redirect(url_for("master.index", tab="lane"))


@bp.route("/master/lane/<int:lid>/toggle", methods=["POST"])
def lane_toggle(lid):
    db = get_db()
    pl = db.get(ProgramLane, lid)
    if pl:
        pl.is_active = not pl.is_active
        db.commit()
    db.close()
    return redirect(url_for("master.index", tab="lane"))


@bp.route("/master/lane/<int:lid>/delete", methods=["POST"])
def lane_delete(lid):
    db = get_db()
    pl = db.get(ProgramLane, lid)
    if pl:
        db.delete(pl)
        db.commit()
    db.close()
    flash("実施枠を削除しました", "success")
    return redirect(url_for("master.index", tab="lane"))


# ─── 並び替えAPI（全マスタ共通） ───────────────────────────────
_SORTABLE_MODELS = {
    "staff": Staff,
    "venue": Venue,
    "role": Role,
    "template": ContentTemplate,
    "lane": ProgramLane,
}


@bp.route("/api/master/reorder", methods=["POST"])
def reorder():
    """並び順を更新する。{ "model": "staff", "ids": [3, 1, 2, ...] }"""
    data = request.get_json()
    model_key = data.get("model")
    ids = data.get("ids", [])
    if model_key not in _SORTABLE_MODELS:
        return jsonify({"error": "invalid model"}), 400
    Model = _SORTABLE_MODELS[model_key]
    db = get_db()
    for i, item_id in enumerate(ids):
        obj = db.get(Model, int(item_id))
        if obj:
            obj.sort_order = i
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ─── 参照チェック関数群（一括削除用） ───────────────────────────
def check_staff_references(db, staff_id: int) -> dict:
    """Staff削除前の参照チェック"""
    count = db.query(EventAssignment).filter(
        EventAssignment.staff_id == staff_id
    ).count()
    return {
        "can_delete": count == 0,
        "reason": "has_assignments" if count > 0 else None,
        "related_count": count,
        "details": f"{count}件のイベント割当で使用されています" if count > 0 else ""
    }


def check_venue_references(db, venue_id: int) -> dict:
    """Venue削除前の参照チェック"""
    count = db.query(Event).filter(Event.venue_id == venue_id).count()
    return {
        "can_delete": count == 0,
        "reason": "has_events" if count > 0 else None,
        "related_count": count,
        "details": f"{count}件のイベントで使用されています" if count > 0 else ""
    }


def check_role_references(db, role_id: int) -> dict:
    """Role削除前の参照チェック"""
    count = db.query(EventAssignment).filter(
        EventAssignment.role_id == role_id
    ).count()
    return {
        "can_delete": count == 0,
        "reason": "has_assignments" if count > 0 else None,
        "related_count": count,
        "details": f"{count}件のイベント割当で使用されています" if count > 0 else ""
    }


def check_programlane_references(db, lane_id: int) -> dict:
    """ProgramLane削除前の参照チェック"""
    # OccasionProgramLane で参照されている場合は削除不可
    occasion_count = db.query(OccasionProgramLane).filter(
        OccasionProgramLane.program_lane_id == lane_id
    ).count()
    if occasion_count > 0:
        return {
            "can_delete": False,
            "reason": "has_occasions",
            "related_count": occasion_count,
            "details": f"{occasion_count}件の開催で使用されています"
        }
    return {
        "can_delete": True,
        "reason": None,
        "related_count": 0,
        "details": ""
    }


def check_template_references(db, template_id: int) -> dict:
    """ContentTemplate削除前の参照チェック（参照なし、常に削除可）"""
    return {
        "can_delete": True,
        "reason": None,
        "related_count": 0,
        "details": ""
    }


# チェック関数のマッピング
_REFERENCE_CHECKERS = {
    "staff": check_staff_references,
    "venue": check_venue_references,
    "role": check_role_references,
    "lane": check_programlane_references,
    "template": check_template_references,
}


# ─── 一括削除エンドポイント ───────────────────────────────────────
@bp.route("/api/master/<model>/delete-multiple", methods=["POST"])
def delete_multiple(model):
    """複数IDを一括削除。参照制約をチェックして返す"""
    # バリデーション
    if model not in _SORTABLE_MODELS or model not in _REFERENCE_CHECKERS:
        return jsonify({"success": False, "error": "Invalid model type"}), 400

    data = request.get_json() or {}
    ids = data.get("ids", [])

    if not ids:
        return jsonify({"success": False, "error": "No IDs provided"}), 400

    try:
        ids = [int(id) for id in ids]
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid ID format"}), 400

    # DB接続
    db = get_db()
    Model = _SORTABLE_MODELS[model]
    checker_func = _REFERENCE_CHECKERS[model]

    deleted_ids = []
    failed = []

    # 各IDをチェック・削除
    for item_id in ids:
        item = db.get(Model, item_id)
        if not item:
            failed.append({
                "id": item_id,
                "name": f"ID:{item_id}",
                "reason": "not_found",
                "details": "レコードが見つかりません"
            })
            continue

        # 参照チェック
        ref_check = checker_func(db, item_id)

        if not ref_check["can_delete"]:
            failed.append({
                "id": item_id,
                "name": getattr(item, "name", f"ID:{item_id}"),
                "reason": ref_check["reason"],
                "details": ref_check["details"],
                "related_count": ref_check["related_count"]
            })
            continue

        # 削除実行
        try:
            db.delete(item)
            deleted_ids.append(item_id)
        except Exception as e:
            failed.append({
                "id": item_id,
                "name": getattr(item, "name", f"ID:{item_id}"),
                "reason": "delete_error",
                "details": f"削除エラー: {str(e)}"
            })

    # コミット
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        db.close()
        return jsonify({
            "success": False,
            "error": "Database commit failed",
            "details": str(e)
        }), 500
    finally:
        db.close()

    return jsonify({
        "success": True,
        "summary": {
            "total_selected": len(ids),
            "deleted": len(deleted_ids),
            "failed": len(failed),
            "message": f"{len(deleted_ids)}件削除、{len(failed)}件削除不可"
        },
        "results": {
            "deleted_ids": deleted_ids,
            "failed": failed
        }
    })


# ─── CSV テンプレートダウンロード ────────────────────────────
@bp.route("/master/staff/csv-template")
def staff_csv_template():
    header = ["氏名", "区分", "所属詳細", "備考"]
    samples = [
        ["田中太郎", "教員", "食物栄養学科", ""],
        ["鈴木花子", "教員", "こども地域学科", ""],
        ["佐藤一郎", "職員", "", ""],
        ["高橋あい", "学生", "食物栄養学科1年", ""],
        ["渡辺けい", "学生", "食物栄養学科2年", ""],
        ["伊藤みな", "学生", "こども地域学科1年", ""],
        ["小林さく", "学生", "こども地域学科2年", ""],
    ]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(samples)
    # BOM付きUTF-8（Excelで文字化けしない）
    csv_bytes = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''staff_template.csv"},
    )


# ─── CSV アップロード → プレビュー ───────────────────────────
@bp.route("/master/staff/csv-upload", methods=["POST"])
def staff_csv_upload():
    f = request.files.get("csv_file")
    if not f or f.filename == "":
        flash("CSVファイルを選択してください", "error")
        return redirect(url_for("master.index", tab="staff"))

    # 文字コード自動判別（UTF-8 BOM → UTF-8 → Shift-JIS）
    raw = f.read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "shift_jis", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        flash("文字コードを読み取れません。UTF-8またはShift-JISで保存してください", "error")
        return redirect(url_for("master.index", tab="staff"))

    reader = csv.DictReader(io.StringIO(text))

    # 必須列チェック
    required_cols = {"氏名", "区分", "所属詳細"}
    fieldnames = set(reader.fieldnames or [])
    missing = required_cols - fieldnames
    if missing:
        flash(f"必須列が不足しています: {', '.join(sorted(missing))}", "error")
        return redirect(url_for("master.index", tab="staff"))

    # DB既存名を取得
    db = get_db()
    existing_names = {s.name for s in db.query(Staff).all()}
    db.close()

    csv_seen = set()
    parsed_rows = []
    for i, row in enumerate(reader, start=2):
        parsed_rows.append(_parse_csv_row(i, row, existing_names, csv_seen))

    if not parsed_rows:
        flash("CSVにデータ行がありません", "error")
        return redirect(url_for("master.index", tab="staff"))

    # 一時ファイルに保存してトークンで管理
    token = str(uuid.uuid4())
    tmp_path = os.path.join(tempfile.gettempdir(), f"oc_csv_{token}.json")
    with open(tmp_path, "w", encoding="utf-8") as fp:
        json.dump(parsed_rows, fp, ensure_ascii=False)

    return redirect(url_for("master.staff_csv_preview", token=token))


# ─── CSV プレビュー画面 ───────────────────────────────────────
@bp.route("/master/staff/csv-preview")
def staff_csv_preview():
    token = request.args.get("token", "")
    tmp_path = os.path.join(tempfile.gettempdir(), f"oc_csv_{token}.json")

    if not token or not os.path.exists(tmp_path):
        flash("プレビューデータが見つかりません。再度CSVを選択してください", "error")
        return redirect(url_for("master.index", tab="staff"))

    with open(tmp_path, "r", encoding="utf-8") as fp:
        rows = json.load(fp)

    ok_count       = sum(1 for r in rows if r["status"] == "ok")
    error_count    = sum(1 for r in rows if r["status"] == "error")
    existing_count = sum(1 for r in rows if r["status"] == "existing")

    return render_template(
        "master/csv_preview.html",
        rows=rows, token=token,
        ok_count=ok_count,
        error_count=error_count,
        existing_count=existing_count,
    )


# ─── CSV 取込実行 ─────────────────────────────────────────────
@bp.route("/master/staff/csv-import", methods=["POST"])
def staff_csv_import():
    token = request.form.get("token", "")
    mode  = request.form.get("mode", "ok_only")  # "ok_only" | "cancel"
    tmp_path = os.path.join(tempfile.gettempdir(), f"oc_csv_{token}.json")

    if not token or not os.path.exists(tmp_path):
        flash("取込データが見つかりません", "error")
        return redirect(url_for("master.index", tab="staff"))

    if mode == "cancel":
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        flash("CSV取込をキャンセルしました", "info")
        return redirect(url_for("master.index", tab="staff"))

    with open(tmp_path, "r", encoding="utf-8") as fp:
        rows = json.load(fp)

    include_existing = request.form.get("include_existing") == "1"

    db = get_db()
    imported = skipped = 0
    for row in rows:
        if row["status"] == "error":
            skipped += 1
            continue
        if row["status"] == "existing" and not include_existing:
            skipped += 1
            continue
        s = Staff(
            name=row["name"],
            staff_type=row["staff_type"],
            department=row["department"],
            grade=row["grade"],
            note=row["note"] or None,
        )
        db.add(s)
        imported += 1
    db.commit()
    db.close()

    try:
        os.remove(tmp_path)
    except OSError:
        pass

    flash(f"{imported}件を取り込みました（{skipped}件スキップ）", "success")
    return redirect(url_for("master.index", tab="staff"))


# ─── API: 担当者一覧（イベントフォーム用） ──────────────────
@bp.route("/api/staff")
def api_staff():
    db = get_db()
    staff = db.query(Staff).filter(Staff.is_active == True).order_by(Staff.staff_type, Staff.name).all()
    db.close()
    return jsonify([{
        "id": s.id, "name": s.name,
        "staff_type": s.staff_type,
        "department": s.department,
        "grade": s.grade,
    } for s in staff])


# ─── API: 役割一覧（イベントフォーム用） ────────────────────
@bp.route("/api/roles")
def api_roles():
    db = get_db()
    roles = db.query(Role).order_by(Role.name).all()
    db.close()
    return jsonify([{"id": r.id, "name": r.name} for r in roles])


# ─── クイック登録API（イベント編集パネルから直接呼び出し） ───
@bp.route("/api/master/venue/quick-add", methods=["POST"])
def api_venue_quick_add():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "名前を入力してください"})
    db = get_db()
    try:
        count = db.query(Venue).count()
        v = Venue(name=name, capacity=data.get("capacity"), sort_order=count)
        db.add(v)
        db.commit()
        result = {"ok": True, "id": v.id, "name": v.name}
    except Exception:
        db.rollback()
        result = {"ok": False, "error": "既に同じ名前の会場が存在します"}
    finally:
        db.close()
    return jsonify(result)


@bp.route("/api/master/role/quick-add", methods=["POST"])
def api_role_quick_add():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "名前を入力してください"})
    db = get_db()
    try:
        count = db.query(Role).count()
        r = Role(name=name, sort_order=count)
        db.add(r)
        db.commit()
        result = {"ok": True, "id": r.id, "name": r.name}
    except Exception:
        db.rollback()
        result = {"ok": False, "error": "既に同じ名前の役割が存在します"}
    finally:
        db.close()
    return jsonify(result)


@bp.route("/api/master/template/quick-add", methods=["POST"])
def api_template_quick_add():
    data = request.get_json()
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "タイトルを入力してください"})
    db = get_db()
    try:
        count = db.query(ContentTemplate).count()
        duration = data.get("duration_min")
        t = ContentTemplate(
            title=title,
            duration_min=int(duration) if duration else None,
            note=(data.get("note") or "").strip() or None,
            sort_order=count,
        )
        db.add(t)
        db.commit()
        result = {"ok": True, "id": t.id, "title": t.title, "duration_min": t.duration_min, "note": t.note or ""}
    except Exception:
        db.rollback()
        result = {"ok": False, "error": "テンプレートを追加できませんでした"}
    finally:
        db.close()
    return jsonify(result)


@bp.route("/api/master/lane/quick-add", methods=["POST"])
def api_lane_quick_add():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "名前を入力してください"})
    db = get_db()
    try:
        count = db.query(ProgramLane).count()
        pl = ProgramLane(name=name, sort_order=count)
        db.add(pl)
        db.commit()
        result = {"ok": True, "id": pl.id, "name": pl.name}
    except Exception:
        db.rollback()
        result = {"ok": False, "error": "既に同じ名前の実施枠が存在します"}
    finally:
        db.close()
    return jsonify(result)
