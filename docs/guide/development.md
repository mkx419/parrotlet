# 開発

コードの構成と動作原理は[内部設計](../internals/index.md)を参照してください。

```bash
uv sync --all-groups
```

| 作業 | コマンド |
|---|---|
| テスト | `uv run pytest` |
| lint | `uvx ruff check src tests scripts` |
| 型チェック | `uvx pyright src tests scripts` と `uvx ty check src tests scripts` |
| ドキュメントのプレビュー | `uv run --group docs zensical serve` |
| ドキュメントのビルド | `uv run --group docs zensical build --strict`（出力先は `site/`） |
| 関数モジュールの再生成 | `uv run python scripts/generate_functions.py` |

## 型チェックのテスト

`tests/typing_checks.py` は、pyright と ty で検査するためのファイルです（実行はしません）。

- `assert_type` で、推論される型を固定しています。
- 型エラーになるべき行には `# pyright: ignore[...]` と `# ty: ignore[...]` を付けています。
- `pyproject.toml` で、pyright の `reportUnnecessaryTypeIgnoreComment` と ty の `unused-ignore-comment` をエラーにしているので、本来エラーになるべき行がエラーにならなくなると、どちらの型チェッカーも失敗します。

## 関数モジュールの生成

`scripts/generate_functions.py` は、DuckDB の `duckdb_functions()` を読み、次のモジュールを生成します。

- `src/parrotlet/functions/_core.py`：core の関数
- `src/parrotlet/functions/table.py`：テーブル関数
- `src/parrotlet/functions/spatial.py`：spatial 拡張の関数

カタログの型（`T`、`T[]`、`MAP(K, V)`、`LAMBDA` など）を `Expr[...]` の型に対応付けます。オーバーロードは、狭い型を先に並べます。結果の型が引数の型で決まる関数は、`functions/_generic.py` に手書きしています。生成するモジュールでは、関数を頭文字ごとに `# region` / `# endregion` で囲むので、VS Code などのエディタで折りたためます。
