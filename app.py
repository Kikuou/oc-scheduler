import os
from flask import Flask
from config import SECRET_KEY
from db.database import init_db

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Blueprint登録
from routes.occasions import bp as occasions_bp
from routes.events import bp as events_bp
from routes.master import bp as master_bp
from routes.year_update import bp as year_update_bp
from routes.reports import bp as reports_bp
from routes.notes import bp as notes_bp

app.register_blueprint(occasions_bp)
app.register_blueprint(events_bp)
app.register_blueprint(master_bp)
app.register_blueprint(year_update_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(notes_bp)

# gunicorn / python app.py 両方で確実にDB初期化を実行する
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5100))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", debug=debug, port=port)
