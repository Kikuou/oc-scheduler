# OCスケジューラ

旭川市立大学のオープンキャンパス（OC）スケジュール作成・管理Webアプリケーション

---

## 開発前提（重要）

> **このプロジェクトの全開発は `docs/dev_rules.md` の方針に従うこと。**
> 明示的な指示がない場合も以下を自動的に適用する。

| 項目 | 設定 |
|------|------|
| ローカルDB | SQLite（`data/oc_schedule.db`）|
| 本番DB | PostgreSQL（Neon）|
| デプロイ先 | Render |
| バージョン管理 | GitHub |
| DB切替方法 | `DATABASE_URL` 環境変数 |

**設計上の大原則**
- 空DB（テーブルが全て空）でも動作すること
- NULL・空配列・未登録データで落ちないこと
- PostgreSQLのFK・UNIQUE制約を常に意識すること

---

## 主な機能

### スケジューラ
- ドラッグ&ドロップでイベントを配置・移動・リサイズ
- 複数実施枠（学科）を列として管理
- 列の表示/非表示・ドラッグで表示順変更
- 10分グリッド・30分・60分で視覚的に区別された罫線
- イベントに教室・時間・所要時間・担当者を表示

### マスタ管理
- 実施枠・会場・スタッフ・役割・内容テンプレートを一元管理
- CSVインポート対応（スタッフ）

### 帳票出力
- スケジュール表・担当者一覧をPDF出力
- スケジューラで選択中の実施枠が帳票にそのまま反映

---

## 技術スタック

| カテゴリ | 技術 |
|----------|------|
| Backend | Flask（Python） |
| ORM | SQLAlchemy 2.0 |
| ローカルDB | SQLite |
| 本番DB | PostgreSQL（Neon） |
| デプロイ | Render（gunicorn） |
| Frontend | Bootstrap 5, SortableJS |
| PDF生成 | ReportLab |

---

## ローカル起動手順

```bash
# 1. リポジトリをクローン
git clone https://github.com/Kikuou/oc-scheduler.git
cd oc-scheduler

# 2. 仮想環境を作成・有効化
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# 3. 依存関係をインストール
pip install -r requirements.txt

# 4. 起動（DBは自動作成）
python app.py
# → http://localhost:5100
```

環境変数を設定しない場合、SQLiteが自動的に使用されます。

---

## 本番（Render）デプロイ設定

| 項目 | 値 |
|------|----|
| Environment | Python |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app` |

**Environment Variables（Render の設定画面で登録）**

| 変数名 | 内容 |
|--------|------|
| `DATABASE_URL` | Neon の Connection String |
| `SECRET_KEY` | ランダムな長い文字列（`python3 -c "import secrets; print(secrets.token_hex(32))"` で生成） |

---

## マスタデータ移行（初回のみ）

ローカルSQLiteのマスタデータをNeonへ投入する場合：

```bash
# 確認のみ（書き込みなし）
DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py --dry-run

# 投入
DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py

# やり直し（全削除→再投入）
DATABASE_URL="postgresql://..." python3 migrate_to_postgres.py --clean
```

移行対象：`roles` / `venues` / `staff` / `program_lanes` / `content_templates`

---

## ファイル構成

```
.
├── app.py                      # Flask アプリ・Blueprint登録・init_db()
├── config.py                   # DATABASE_URL / SECRET_KEY の解決
├── requirements.txt
├── Procfile                    # gunicorn app:app
├── migrate_to_postgres.py      # マスタ移行スクリプト
├── db/
│   ├── database.py             # engine, SessionLocal, init_db()
│   └── models.py               # SQLAlchemy モデル
├── routes/                     # Blueprint
│   ├── occasions.py
│   ├── events.py
│   ├── master.py
│   ├── reports.py
│   ├── notes.py
│   └── year_update.py
├── services/
│   ├── schedule_matrix.py      # スケジュールマトリクス生成
│   ├── pdf_generator.py
│   └── year_update_svc.py
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── schedule/
│   ├── reports/
│   ├── master/
│   └── year_update/
├── static/
│   ├── css/main.css
│   └── js/event_form.js
└── docs/
    └── dev_rules.md            # 開発ルール（必読）
```

---

## 開発ルール

詳細は [`docs/dev_rules.md`](docs/dev_rules.md) を参照。

主なルール：
- `DATABASE_URL` がある場合はPostgres、ない場合はSQLiteを自動選択
- `pool_pre_ping=True` でNeon接続断に対応
- テンプレートの `tojson` には `(value or [])` フォールバックを付ける
- 早期リターンは正常ルートと同じキーセットを返す

---

**作成**: 旭川市立大学
**最終更新**: 2026年3月
