"""初期マスタデータ投入スクリプト
実行: python init_data.py
"""
from db.database import init_db, SessionLocal
from db.models import Venue, Staff, Role, ContentTemplate, ProgramLane


def seed():
    init_db()
    db = SessionLocal()

    # 会場
    venues = [
        Venue(name="224教室"),
        Venue(name="251教室"),
        Venue(name="実習室"),
        Venue(name="317教室"),
        Venue(name="図工室"),
        Venue(name="講堂"),
        Venue(name="受付"),
    ]
    for v in venues:
        existing = db.query(Venue).filter(Venue.name == v.name).first()
        if not existing:
            db.add(v)

    # 役割
    roles = ["進行", "担当", "サポーター", "説明", "受付", "誘導", "写真撮影", "会場準備"]
    for r in roles:
        existing = db.query(Role).filter(Role.name == r).first()
        if not existing:
            db.add(Role(name=r))

    # 内容テンプレート
    templates = [
        ContentTemplate(title="全体ミーティング", department=None, duration_min=20),
        ContentTemplate(title="学科説明", department="食物栄養学科", duration_min=40),
        ContentTemplate(title="学科説明", department="こども地域学科", duration_min=40),
        ContentTemplate(title="体験実習", department="食物栄養学科", duration_min=60),
        ContentTemplate(title="体験授業", department="こども地域学科", duration_min=60),
        ContentTemplate(title="施設見学", department=None, duration_min=30),
        ContentTemplate(title="個別相談", department=None, duration_min=60),
        ContentTemplate(title="受付・誘導", department=None, duration_min=30),
        ContentTemplate(title="アンケート記入", department=None, duration_min=10),
        ContentTemplate(title="記念撮影", department=None, duration_min=10),
    ]
    for t in templates:
        existing = db.query(ContentTemplate).filter(
            ContentTemplate.title == t.title,
            ContentTemplate.department == t.department
        ).first()
        if not existing:
            db.add(t)

    # 実施枠
    program_lanes = ["食物栄養学科", "こども地域学科", "ちょこっとOC"]
    for i, lname in enumerate(program_lanes):
        existing = db.query(ProgramLane).filter(ProgramLane.name == lname).first()
        if not existing:
            db.add(ProgramLane(name=lname, sort_order=i))

    db.commit()
    db.close()
    print("✓ 初期データ投入完了")
    print("  会場・役割・内容テンプレートを登録しました。")
    print("  担当者は「マスタ管理」画面から登録してください。")


if __name__ == "__main__":
    seed()
