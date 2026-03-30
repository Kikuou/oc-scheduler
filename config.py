import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# DATABASE_URL 環境変数があればPostgres（本番）、なければSQLite（ローカル）
_db_url = os.environ.get("DATABASE_URL")

if _db_url:
    # Neonは "postgres://" で始まるURIを返すことがある → psycopg2用に変換
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    DATABASE_URL = _db_url
else:
    DATA_DIR = os.path.join(BASE_DIR, "data")
    os.makedirs(DATA_DIR, exist_ok=True)
    DB_PATH = os.path.join(DATA_DIR, "oc_schedule.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"

SQLALCHEMY_DATABASE_URI = DATABASE_URL

# 本番環境では SECRET_KEY 環境変数を必ず設定すること
SECRET_KEY = os.environ.get("SECRET_KEY", "local-dev-only-change-in-production")
