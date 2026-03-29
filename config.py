import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Render環境では /tmp にDBを配置（アプリディレクトリは書き込み不可）
# ローカルでは従来通り data/ ディレクトリを使用
if os.environ.get("RENDER"):
    DATA_DIR = "/tmp"
else:
    DATA_DIR = os.path.join(BASE_DIR, "data")
    os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "oc_schedule.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"
# 本番環境では SECRET_KEY 環境変数を必ず設定すること
SECRET_KEY = os.environ.get("SECRET_KEY", "local-dev-only-change-in-production")
