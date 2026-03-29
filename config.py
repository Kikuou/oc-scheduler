import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "oc_schedule.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"
# 本番環境では SECRET_KEY 環境変数を必ず設定すること
SECRET_KEY = os.environ.get("SECRET_KEY", "local-dev-only-change-in-production")
