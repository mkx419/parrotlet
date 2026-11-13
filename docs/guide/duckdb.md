# DuckDB 固有の機能

## star の修飾子

```python
from parrotlet import star

star(exclude=["password"])  # * EXCLUDE ("password")
star(replace={"name": F.upper(User.name)})  # * REPLACE (upper(...) AS "name")
star(rename={"id": "user_id"})  # * RENAME ("id" AS "user_id")
star(like="num_%")  # * LIKE 'num_%'（not_like / ilike / not_ilike / glob / similar_to も可）
star(exclude=["a"], like="num_%")  # 組み合わせ
table(User).star(exclude=["password"])  # "users".* EXCLUDE (...)
col("s", type_=dt.STRUCT(a=dt.INTEGER)).star()  # 構造体を展開: s.*
```

DuckDB の制約により、パターン（LIKE など）と RENAME は併用できません。

## COLUMNS(...)

```python
from parrotlet import columns

columns("num_.*")  # 正規表現
columns(["id", "name"])  # 列名のリスト
columns(lambda c: c.like("num_%"))  # 列名に対するラムダ
columns(star(exclude=["name"]))  # star 式
columns(User)  # COLUMNS("users".*)

select(F.max(columns("num_.*"))).from_(T)  # 各列に適用
select(columns("num_(.*)").as_(r"x_\1"))  # キャプチャグループで別名
select(F.coalesce(*columns("num_.*")))  # 関数の引数として展開: coalesce(*COLUMNS(...))
select().from_(T).where(columns(["a", "b"]) > 0)
```

## その他の構文

| 機能 | 書き方 |
|---|---|
| FROM 先頭構文 | `from_(User).where(...)` |
| GROUP BY ALL / ORDER BY ALL | `.group_by_all()`、`.order_by_all()` |
| QUALIFY | `.qualify(F.row_number().over(...) == 1)` |
| ASOF / POSITIONAL / SEMI / ANTI JOIN | `.asof_join(t, cond)`、`.positional_join(t)`、`.semi_join(...)`、`.anti_join(...)` |
| USING SAMPLE / TABLESAMPLE | `.using_sample(percent=10)`、`tablesample(T, rows=100)` |
| LIMIT n% | `.limit(10, percent=True)` |
| UNION BY NAME | `q1.union(q2, by_name=True)` |
| 再帰 CTE の USING KEY | `q.cte("r", using_key=["k"])` |
| ファイルの直接読み込み | `file("data/*.parquet")` |
| VALUES をテーブルとして使う | `values(..., alias="v", columns=[...])` |
| WITH ORDINALITY | `TF.unnest(xs).as_("u", ["x", "i"]).with_ordinality()` |
| リスト内包表記 | `list_comprehension(xs, lambda x: x * 2, where=lambda x: x > 0)` |
| ラムダ | `F.list_transform(xs, lambda x: x + 1)` |
| JSON 演算子 | `.json_get(path)`、`.json_get_text(path)` |
| リスト演算子 | `.has_all(xs)`、`.contained_by(xs)`、`.has_any(xs)` |
| スライスのステップ・負のインデックス | `xs[1:5:2]`、`xs[-1]` |
| `#n` | `positional(1)` |
| TRY | `try_(expr)` |
| ANY / ALL | `x > all_(subquery)`、`x == any_(list_expr)` |
| PIVOT / UNPIVOT | `pivot(...)`、`unpivot(...)`（[SELECT](select.md#pivot-unpivot)） |
| MERGE | `merge_into(...)`（[MERGE](dml.md#merge)） |
| INSERT OR REPLACE / BY NAME | `.or_replace()`、`.by_name()` |
| マクロ | `create_macro("f", lambda a, b=1: a + b)` |

## ユーティリティ文

```python
from parrotlet import (
    analyze,
    attach,
    begin,
    call,
    checkpoint,
    commit,
    describe,
    detach,
    explain,
    export_database,
    import_database,
    install,
    load,
    pragma,
    reset,
    rollback,
    set_,
    set_variable,
    show_databases,
    show_tables,
    summarize,
    use,
    vacuum,
)

describe(User)
describe(select(...))  # 列名と型
summarize(User)  # 列ごとの統計
show_tables()
show_tables(all=True)
show_databases()
explain(q)
explain(q, analyze=True)
attach("other.duckdb", "other", read_only=True)
use("other")
detach("other", if_exists=True)
set_("threads", 4)
set_("memory_limit", "4GB", scope="global")
reset("threads")
set_variable("cutoff", 100)  # F.getvariable("cutoff") で参照
pragma("table_info", "users")
pragma("threads", value=4)
install("spatial")
install("h3", from_="community")
load("spatial")
checkpoint()
vacuum(User, analyze=True)
analyze()
export_database("backup", format="parquet")
import_database("backup")
call(func.pragma_table_info("users"))
begin()
commit()
rollback()
```

## パラメータとリテラル

- 値は通常 `?` パラメータとしてバインドされます。
- DuckDB がパラメータを受け付けない場所では、エスケープ済みのリテラルとして描画されます。対象は、DDL、マクロ、COPY のオプション、star のパターン、`COLUMNS('...')`、インデックスの添字などです。
- 実行してみて初めてパラメータが使えないと分かる文もあります（IN リストのない PIVOT をサブクエリにした場合など）。このときは `execute()` が値をインライン展開して1回だけ再実行します。
- `q.sql_inline` で、値をインライン展開した SQL を確認できます。
