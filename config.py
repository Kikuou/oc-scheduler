import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Render環境では /tmp にDBを配置（アプリディレクトリは書き込み不可）
# ローカルでは data/ ディレクトリを使用
if os.environ.get("RENDER"):
    DB_PATH = "/tmp/oc_schedule.db"
else:
    DATA_DIR = os.path.join(BASE_DIR, "data")
    os.makedirs(DATA_DIR, exist_ok=True)
    DB_PATH = os.path.join(DATA_DIR, "oc_schedule.db")

SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"
DATABASE_URL = SQLALCHEMY_DATABASE_URI  # db/database.py との互換用

# 本番環境では SECRET_KEY 環境変数を必ず設定すること
SECRET_KEY = os.environ.get("SECRET_KEY", "local-dev-only-change-in-production")
