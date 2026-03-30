# 開発ルール（dev_rules.md）

このプロジェクトの全開発において、このファイルに記載された方針を
**明示的な指示がない場合でも**デフォルトとして適用すること。

---

## 標準開発フロー

| フェーズ | 技術 |
|----------|------|
| ローカル開発 | SQLite |
| 本番DB | PostgreSQL（Neon） |
| デプロイ | Render |
| バージョン管理 | GitHub（必須） |

---

## 設計原則

### 1. 空DBでも動作すること
- 初回起動時、全テーブルが空でもクラッシュしない
- マスタ未登録・開催ゼロの状態で全画面が表示できること

### 2. NULL・空配列で落ちないこと
- テンプレート: `{{ (value or []) | tojson }}` 形式で安全処理
- Python: `.get()` / `or []` / `or {}` で防御的に記述
- 関数の戻り値は常に同じキーセットを返す（早期リターンも同様）

### 3. PostgreSQL前提で設計すること
- FK制約・UNIQUE制約を最初から意識する
- SQLiteはFK未チェックのため、制約エラーはPostgreSQLで初めて顕在化する
- `OVERRIDING SYSTEM VALUE` が必要な場面（ID明示INSERT）を考慮する

### 4. ローカルデータに依存しないこと
- 本番環境は常に空DBからスタートする前提
- ローカルのSQLiteデータは移行しない（マスタのみ必要に応じて投入）
- データ依存の初期化処理をコードに埋め込まない

### 5. DB切替はDATABASE_URL環境変数で行うこと
```python
# config.py の方針
if os.environ.get("DATABASE_URL"):
    DATABASE_URL = os.environ["DATABASE_URL"]  # Postgres（本番）
else:
    DATABASE_URL = f"sqlite:///{DB_PATH}"       # SQLite（ローカル）
```

---

## 実装ルール

### DB接続
- `pool_pre_ping=True` を必ず設定（Neon serverless の接続断対策）
- DB初期化（`init_db()`）はアプリ起動時のグローバルスコープで呼ぶ
- `if __name__ == "__main__":` の中ではなく、blueprint登録後に実行

### テンプレート
- `tojson` を使う変数は必ず `(value or [])` でフォールバックを付ける
- `{% if items %}` で空配列をガードしてから `{% for %}` を回す
- 関連データ（FKリレーション）は事前ロード（`selectinload`）する

### ルート関数
- 早期リターンは正常ルートと同じキーセットを返すこと
- DB操作後は必ず `db.close()` する（`try/finally` を推奨）
- ユーザー入力は `.strip()` で前後の空白を除去する

### シーケンス（PostgreSQL）
- ID明示INSERTの後は必ず `setval(pg_get_serial_sequence(...))` でリセット
- そうしないと次の自動採番が重複してエラーになる

---

## ディレクトリ構成の規約

```
project/
├── app.py                  # Flask アプリ本体・Blueprint登録・init_db()
├── config.py               # DATABASE_URL・SECRET_KEY の解決
├── requirements.txt        # flask, sqlalchemy, gunicorn, psycopg2-binary, reportlab
├── Procfile                # web: gunicorn app:app
├── db/
│   ├── database.py         # engine, SessionLocal, Base, init_db()
│   └── models.py           # SQLAlchemy モデル定義
├── routes/                 # Blueprint ごとのルート
├── services/               # ビジネスロジック（DBに直接触れる）
├── templates/              # Jinja2 テンプレート
├── static/                 # CSS / JS
├── migrate_to_postgres.py  # マスタ移行スクリプト（必要時のみ実行）
└── docs/
    └── dev_rules.md        # このファイル
```

---

## Render デプロイ設定

| 項目 | 値 |
|------|----|
| Environment | Python |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app` |
| 環境変数 `DATABASE_URL` | Neon の Connection String |
| 環境変数 `SECRET_KEY` | ランダムな長い文字列 |

---

## マスタ移行（必要な場合のみ）

```bash
# 確認のみ（Postgresへの書き込みなし）
DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py --dry-run

# 初回投入（Neonが空の場合）
DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py

# やり直し（全削除→再投入）
DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py --clean
```

---

## よくある問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| `tojson` で 500 エラー | 戻り値の dict に期待するキーがない | 早期リターンにも全キーを含める |
| FK 制約エラー（PostgreSQL） | SQLite でチェックされなかった不整合 | INNER JOIN で孤立行をスキップ |
| `unable to open database file` | SQLite のパスが存在しない | `os.makedirs(exist_ok=True)` でディレクトリ自動作成 |
| Neon 接続断 | Serverless の非アクティブ切断 | `pool_pre_ping=True` を設定 |
| ID の重複エラー（PostgreSQL） | シーケンスが最大ID未満を指している | `setval` でシーケンスをリセット |
| `GENERATED ALWAYS` へのID INSERT | PostgreSQL の IDENTITY 制約 | `OVERRIDING SYSTEM VALUE` を追加 |
