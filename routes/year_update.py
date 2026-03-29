from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from db.database import SessionLocal
from db.models import Occasion
from services.year_update_svc import get_preview, execute_year_update
from datetime import date

bp = Blueprint("year_update", __name__)


def get_db():
    return SessionLocal()


@bp.route("/year-update")
def index():
    db = get_db()
    occasions = db.query(Occasion).order_by(Occasion.year.desc(), Occasion.date.desc()).all()
    db.close()
    return render_template("year_update/wizard.html",
                           step=1, occasions=occasions,
                           preview=None, current_year=date.today().year)


@bp.route("/year-update/preview", methods=["POST"])
def preview():
    src_id = int(request.form["src_occasion_id"])
    db = get_db()
    occasions = db.query(Occasion).order_by(Occasion.year.desc(), Occasion.date.desc()).all()
    db.close()
    preview_data = get_preview(src_id)
    return render_template("year_update/wizard.html",
                           step=2, occasions=occasions,
                           preview=preview_data,
                           src_id=src_id,
                           current_year=date.today().year + 1)


@bp.route("/year-update/execute", methods=["POST"])
def execute():
    src_id = int(request.form["src_occasion_id"])
    new_year = int(request.form["new_year"])
    new_date = request.form["new_date"]
    new_name = request.form["new_name"].strip()
    keep_ids = [int(x) for x in request.form.getlist("keep_student_id")]

    if not new_name:
        flash("新しい名称を入力してください", "error")
        return redirect(url_for("year_update.index"))

    new_id = execute_year_update(src_id, new_year, new_date, new_name, keep_ids)
    flash(f"年度更新が完了しました。新しい開催：{new_name}", "success")
    return redirect(url_for("occasions.detail", occasion_id=new_id))
