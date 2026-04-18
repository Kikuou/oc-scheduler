# OCスケジューラ

旭川市立大学OC スケジュール管理 Web アプリ（Flask + SQLAlchemy 2.0）
ローカル: SQLite、本番: PostgreSQL（Neon）、デプロイ: Render（gunicorn）
起動: `python app.py` → <http://localhost:5100>

## 開発ルール
**すべての実装は `docs/dev_rules.md` に従うこと。** 明示的な指示がなくても自動適用。

## 最重要ルール（常に適用）
- DB切替: `DATABASE_URL` 環境変数の有無で自動選択（`config.py`）
- `pool_pre_ping=True` 必須（Neon接続断対策）
- テンプレート: `{{ (value or []) | tojson }}` で NULL 安全に
- 早期リターンも正常ルートと同じキーセットを返す
- FK・UNIQUE制約は PostgreSQL 前提で設計（SQLite ではチェックされない）

## 詳細参照
- 実装ルール・トラブル対処: `docs/dev_rules.md`
- プロジェクト概要・デプロイ手順: `README.md`
