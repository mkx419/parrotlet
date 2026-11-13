# AGENTS.md

AI コーディングエージェント向けの作業ガイドです。人間向けの説明は [README.md](README.md) と `docs/` にあります。

## プロジェクトの概要

parrotlet は、DuckDB 用の型安全で不変な SQL クエリビルダーです（Python 3.14 以上、依存は `duckdb` と `shapely`）。

- 式は `Expr[T]` で、`T` は `parrotlet.type` の型クラスです。型チェッカー（pyright / ty）が演算子や関数の引数の型を検査します。
- 式もステートメントも frozen な dataclass の木で、`build()` を呼ぶまで SQL を作りません。
- Python の値は常に `?` パラメータとして渡し、DuckDB がパラメータを受け付けない場所（DDL など）でだけリテラルにします。

設計の詳細は [docs/internals/](docs/internals/index.md) にあります。コードを大きく変える前に読んでください。

## コマンド

パッケージ管理は uv です。

| 作業 | コマンド |
|---|---|
| テスト | `uv run pytest` |
| 型チェック | `uv run --with pyright pyright src tests scripts` と `uvx ty check src tests scripts` |
| lint | `uv run --group docs ruff check src tests scripts`（`fix = true` なので自動で直す） |
| 整形 | `uv run --group docs ruff format src tests scripts` |
| ドキュメントのビルド | `uv run --group docs zensical build --strict` |
| ドキュメントのプレビュー | `uv run --group docs zensical serve` |
| 関数モジュールの再生成 | `uv run --group docs python scripts/generate_functions.py` |

変更を終える前に、テスト・pyright・ty・ruff check・ruff format --check をすべて通してください。ドキュメントを変えたときは strict ビルドも通します。

## ディレクトリ構成

| パス | 内容 |
|---|---|
| `src/parrotlet/query.py` | `Query`（コンパイル結果）、`Node`（すべての基底）、識別子のクォート、リテラル、パス |
| `src/parrotlet/execution.py` | DuckDB での実行：拡張機能の導入、パラメータを使えない文の再試行 |
| `src/parrotlet/type.py` | DuckDB の型クラス（`Integer`、`Decimal`、`List[T]` ...）。継承で暗黙の型変換を表す |
| `src/parrotlet/expr.py` | `Expr[T]` と式ノード、`func`、CASE、ウィンドウ、ラムダ |
| `src/parrotlet/source.py` | FROM に置けるもの（テーブル、サブクエリ、CTE、テーブル関数、VALUES、ファイル） |
| `src/parrotlet/model.py` | `Model` / `Column`：テーブル定義と行型を兼ねるクラス |
| `src/parrotlet/statement/` | SELECT / INSERT / UPDATE / DELETE / MERGE / PIVOT / COPY / DDL / ユーティリティ |
| `src/parrotlet/database.py` | `Database`：接続を持ち、ステートメントをバインドする |
| `src/parrotlet/functions/` | DuckDB の関数カタログから生成した型付き関数 |
| `tests/typing_checks.py` | 型チェッカーだけで検査するファイル（実行しない） |
| `docs/guide/`、`docs/internals/` | 日本語のドキュメント（Zensical / mkdocstrings） |

依存の向きは `query.py` → `type.py` → `expr.py` → `source.py` → `model.py` → `statement/` → `database.py` です。下の層から上の層を import しないでください。`expr.py` は `source.py` のテーブルを `Qualified` プロトコルとしてだけ扱います。

## 生成ファイル

`src/parrotlet/functions/_core.py`、`spatial.py`、`table.py` は `scripts/generate_functions.py` が生成します。直接編集しないでください。直すときは生成スクリプトを変えて再生成します。手書きの関数は `functions/_generic.py`、生成コードが呼ぶヘルパーは `functions/_runtime.py` です。

## コーディング規約

- **命名は PEP 8 を最優先**：ruff の pep8-naming（`N`）を有効にしています。組み込みと名前がぶつかるときは末尾に `_` を付けます（`from_`、`if_`、`any_`）。
- **型クラス**：引数のない型はクラスのまま（`qlt.Integer`）、引数のある型はインスタンス（`qlt.Decimal(10, 2)`）として受け付けます。型を受け取る引数は `TypeLike` にし、`to_type()` でそろえてください。
- **import の慣例**：`import parrotlet as ql`、`import parrotlet.type as qlt`、`import parrotlet.functions as fn`（`fn.spatial`、`fn.table`）。`from parrotlet import type` は組み込みの `type` を隠すので使わないでください。
- **不変性**：ステートメントは `@dataclass(frozen=True, slots=True, eq=False)` で、ビルダーメソッドは `self._replace(...)` で新しいインスタンスを返します。共通のフィールドは `BoundStatement` / `QueryStatement` / `DmlStatement` に、`where()` は `Filterable` にあります。
- **式の `eq=False`**：`Expr` の `==` は SQL の比較を返すので、dataclass が生成する `__eq__` で上書きしないでください。
- **値とリテラル**：値を SQL に埋め込むときは `param()` か `render_literal()` を通し、文字列を直接連結しないでください。識別子は `quote_ident()` / `ident_list()` でクォートします。
- **折りたたみ**：モジュールやクラスの節は `# region <名前>` / `# endregion` で囲みます（VS Code で折りたためます）。
- **書式**：1行は120字まで。docstring とコメントは英語（numpy スタイル）。
- **改行コード**：ファイルごとに CRLF と LF が混在しています。編集するときは、そのファイルの既存の改行コードを保ってください。

## テスト

- 動作のテストは `tests/test_*.py` に書きます。`conftest.py` に、サンプルのテーブルを入れた DuckDB 接続（`con`）があります。
- 型の規則は `tests/typing_checks.py` で検査します。推論される型は `assert_type` で固定し、型エラーになるべき行には `# pyright: ignore[...]` と `# ty: ignore[...]` の両方を付けます。どちらも不要な ignore をエラーにする設定なので、エラーにならなくなった行は型チェッカーが知らせます。
- 公開 API を変えたら、`typing_checks.py` にも型のテストを足してください。

## ドキュメント

- `docs/` は日本語です。結論を先に書き、元にない事実を足さない、自然な日本語にしてください。
- 公開 API の名前を変えたら、`docs/guide/`、`docs/internals/`、`docs/reference/`、README.md の例も直します。
- API リファレンス（`docs/reference/`）は docstring から生成します。新しい公開クラスを足したら、該当ページの `members` にも加えてください。

## やってはいけないこと

- 生成ファイル（`functions/_core.py` など）を手で編集する
- 型チェッカーのエラーを、理由なく `# type: ignore` で黙らせる
- ユーザーに頼まれていないのに、コミットや push をする
