# 式

parrotlet の式は `Expr[T]` のオブジェクトです。Python の演算子やメソッドで組み立て、SQL に変換されます。式を作った時点では何も実行されません。

式だけを SQL にして確認することもできます。

```python
(User.age + 1).sql  # '("users"."age" + ?)'
(User.age + 1).params  # (1,)
```

## 値とカラム

| 書き方 | 意味 | SQL |
|---|---|---|
| `User.name` | モデルのカラム（型付き） | `"users"."name"` |
| `table("t").c.name` | テーブルのカラム（型なし） | `"t"."name"` |
| `col("name")` / `col("name", "t")` | カラム（型なし） | `"name"` / `"t"."name"` |
| `col("ts", type_=qlt.Timestamp)` | 型を付けたカラム | `"ts"` |
| `20`、`"JP"` などの Python の値 | パラメータ | `?` |
| `val(20)` | パラメータ（型付きの式にする） | `?` |
| `lit("x")` | リテラル（SQL に直接埋め込む） | `'x'` |
| `sql(t"...")` | 生の SQL | `(...)` |
| `keyword("CURRENT_DATE")` | キーワード | `CURRENT_DATE` |
| `NULL` / `TRUE` / `FALSE` / `DEFAULT` | 定数 | `NULL` / `true` / `false` / `DEFAULT` |

```python
from parrotlet import DEFAULT, FALSE, NULL, TRUE, col, keyword, lit, sql, val
```

### パラメータとリテラル

Python の値は、ふつうは `?` パラメータとして DuckDB に渡されます。SQL インジェクションの心配がなく、DuckDB がプリペアドステートメントを再利用できます。

`val(x)` は、値を明示的にパラメータの式にします。Python の型から SQL の型が決まるので（`val(1)` は `Param[Integer]`、`val("a")` は `Param[Varchar]`）、演算子や関数の左側に値を置きたいときに使います。

```python
val(10) - User.age  # (? - "users"."age")
fn.concat(val("ID-"), User.id.cast(qlt.Varchar))
```

`lit(x)` は、値をエスケープ済みのリテラルとして SQL に埋め込みます。定数でなければならない場所や、SQL を読みやすくしたいときに使います。

```python
lit("x")  # 'x'
lit(datetime.date(2024, 1, 2))  # '2024-01-02'::DATE
```

### 生の SQL

`sql()` は、t-string から式を作ります。parrotlet が対応していない構文に使います。埋め込んだ値はパラメータに、式はその SQL になります。結果は型なし（`Expr[Any]`）なので、必要なら `.cast()` で型を付けます。

```python
sql(t"date_trunc('day', {User.joined})")  # (date_trunc('day', "users"."joined"))
sql(t"{User.age} BETWEEN SYMMETRIC {60} AND {20}")
sql(t"strftime({User.joined}, '%Y')").cast(qlt.Integer)
```

## 比較

| Python | SQL |
|---|---|
| `a == b` / `a != b` | `a = b` / `a <> b` |
| `a < b` `a <= b` `a > b` `a >= b` | 同じ |
| `a == None` / `a != None` | `a IS NULL` / `a IS NOT NULL` |
| `a.is_null()` / `a.is_not_null()` | `a IS NULL` / `a IS NOT NULL` |
| `a.is_distinct_from(b)` / `a.is_not_distinct_from(b)` | `a IS DISTINCT FROM b` / `a IS NOT DISTINCT FROM b`（NULL どうしを等しいとみなす） |
| `a.between(x, y)` / `a.not_between(x, y)` | `a BETWEEN x AND y` |
| `a.in_([...])` / `a.not_in([...])` | `a IN (?, ?)` / `a NOT IN (...)` |
| `a.in_(subquery)` | `a IN (SELECT ...)` |

```python
User.country.in_(["JP", "US"])
# ("users"."country" IN (?, ?))

User.id.in_(select(Order.user_id).from_(Order))
# ("users"."id" IN (SELECT "orders"."user_id" FROM "orders"))

User.age.between(20, 29)
# ("users"."age" BETWEEN ? AND ?)
```

- `in_([])`（空のリスト）は `false` に、`not_in([])` は `true` になります。
- `in_("JP")` のように文字列を渡すと `TypeError` になります（1文字ずつのリストと誤解しないため）。
- リスト型のカラムに値が含まれるかは、`in_` ではなく `fn.list_contains(User.tags, "a")` や `lit("a") == any_(User.tags)` を使います。

## 論理演算 {#logic}

| Python | SQL |
|---|---|
| `a & b` | `a AND b` |
| <code>a &#124; b</code> | `a OR b` |
| `~a` | `NOT a` |
| `and_(a, b, c)` / `or_(a, b, c)` / `not_(a)` | 同じ（`and_()` は `true`、`or_()` は `false`） |
| `a.is_true()` / `a.is_false()` / `a.is_not_true()` / `a.is_not_false()` | `a IS TRUE` など |

```python
from parrotlet import and_, not_, or_

(User.age >= 20) & ~(User.country == "JP") | User.name.like("a%")
# ((("users"."age" >= ?) AND (NOT ("users"."country" = ?)))
#   OR ("users"."name" LIKE ?))
```

!!! warning "比較は必ず括弧で囲む"
    Python では `&` `|` の優先順位が比較演算子より高いので、`User.age > 20 & User.name == "a"` は `User.age > (20 & User.name) == "a"` と解釈されます。比較を `(User.age > 20) & (User.name == "a")` のように括弧で囲むか、`and_()` を使ってください。型チェッカーはこの間違いを検出します。

!!! warning "`and` / `or` / `not` は使えない"
    Python の `and` `or` `not` は、式の真偽値を必要とします。式は真偽値を持たないので、`TypeError: SQL expressions have no truth value` になります。`if User.age > 20:` のような書き方も同じエラーになります。

条件を動的に組み立てるときは、リストに集めて `and_()` に渡すか、`.where()` に展開します。

```python
conditions = []
if country is not None:
    conditions.append(User.country == country)
if min_age is not None:
    conditions.append(User.age >= min_age)
db.from_(User).where(*conditions)  # 条件が空なら WHERE は付かない
```

## 算術演算

| Python | SQL | 補足 |
|---|---|---|
| `a + b` `a - b` `a * b` | 同じ | 数値、日付・時刻と INTERVAL |
| `a / b` | `a / b` | DuckDB では浮動小数点の除算（結果は `Double`） |
| `a // b` | `a // b` | 整数の除算 |
| `a % b` | `a % b` | 剰余 |
| `a ** b` | `a ** b` | べき乗（結果は `Double`） |
| `-a` | `-a` | 符号反転 |
| `a.concat(b)` | <code>a &#124;&#124; b</code> | 文字列・リスト・BLOB の連結 |

日付と時刻の演算は、DuckDB の規則どおりに型が決まります。

```python
User.joined + datetime.timedelta(days=1)  # Expr[Timestamp]
User.joined - User.joined  # Expr[Interval]
col("d", type_=qlt.Date) + 1  # Expr[Date]（日数を足す）
col("d", type_=qlt.Date) - col("e", type_=qlt.Date)  # Expr[BigInt]（日数の差）
```

## 文字列

| メソッド | SQL |
|---|---|
| `.like(p)` / `.not_like(p)` | `LIKE` / `NOT LIKE` |
| `.ilike(p)` / `.not_ilike(p)` | `ILIKE`（大文字小文字を区別しない） |
| `.like(p, escape="\\")` | `LIKE ? ESCAPE '\'` |
| `.glob(p)` | `GLOB`（`*` と `?`） |
| `.similar_to(p)` | `SIMILAR TO`（正規表現） |
| `.concat(s)` | <code>&#124;&#124;</code> |
| `.collate("nocase")` | `COLLATE "nocase"` |
| `s[1:3]` | 部分文字列（1 始まり） |

それ以外の文字列関数（`fn.upper`、`fn.regexp_replace`、`fn.split` など）は[関数](functions.md)を参照してください。

## リスト・構造体・MAP {#nested}

| 書き方 | SQL | 型 |
|---|---|---|
| `User.tags[1]` | `("users"."tags")[1]` | 要素の型（1 始まり） |
| `User.tags[-1]` | `[-1]` | 最後の要素 |
| `User.tags[1:3]` / `User.tags[1:5:2]` | `[1:3]` / `[1:5:2]` | 同じリスト型 |
| `struct_col["field"]` | `(s)['field']` | `Expr[Any]` |
| `map_col["key"]` | `(m)['key']` | 値の型 |
| `User.tags.has_all(["a", "b"])` | `@>` | すべて含む |
| `User.tags.contained_by([...])` | `<@` | すべて含まれる |
| `User.tags.has_any([...])` | `&&` | どれかを含む |
| `struct_col.star()` | `s.*` | 構造体をカラムに展開 |

整数のインデックスと構造体のキーは、DuckDB が定数を要求するので、リテラルとして埋め込まれます。

## JSON

```python
doc = col("doc", type_=qlt.Json)
doc.json_get("$.user.name")  # ("doc" -> ?)：JSON を返す
doc.json_get_text("$.user.name")  # ("doc" ->> ?)：VARCHAR を返す
doc.json_get(0)  # 配列のインデックス
```

`fn.json_extract`、`fn.json_keys` などの関数も使えます。

## 日時

```python
User.joined.at_time_zone("Asia/Tokyo")  # TIMESTAMP → TIMESTAMPTZ
fn.date_trunc("month", User.joined)
fn.date_part("year", User.joined)  # または fn.year(User.joined)
fn.strftime(User.joined, "%Y-%m-%d")
```

## CAST

```python
User.age.cast(qlt.Varchar)  # CAST("users"."age" AS VARCHAR)
User.name.try_cast(qlt.Integer)  # TRY_CAST(...)：失敗すると NULL
```

詳しくは[データ型](datatypes.md#cast)を参照してください。

## CASE

```python
from parrotlet import case

case().when(User.age < 20, "minor").when(User.age < 65, "adult").else_("senior")
# (CASE WHEN ("users"."age" < ?) THEN ? WHEN ("users"."age" < ?) THEN ? ELSE ? END)

case(User.country).when("JP", "Japan").when("US", "USA").else_("other")
# (CASE "users"."country" WHEN ? THEN ? WHEN ? THEN ? ELSE ? END)
```

- 最初の `then` の型が、CASE 全体の型になります（上の例は `Case[Varchar]`）。以降の `then` と `else_` も同じ型でなければなりません。
- `else_()` を省略すると、どれにも当てはまらない行は NULL になります。
- `case()` のあとに `when()` を1つも呼ばずにビルドすると `ValueError` になります。

## サブクエリ {#subqueries}

```python
from parrotlet import all_, any_, exists, not_exists

avg_age = select(fn.avg(User.age)).from_(User).scalar()  # スカラーサブクエリ
db.from_(User).where(User.age > avg_age)
# WHERE ("users"."age" > (SELECT avg("users"."age") FROM "users"))

exists(select(1).from_(Order).where(Order.user_id == User.id))
# (EXISTS (SELECT ? FROM "orders" WHERE ("orders"."user_id" = "users"."id")))

User.age > all_(select(User.age).from_(User).where(User.country == "JP"))
# > ALL (SELECT ...)

User.age == any_(select(User.age).from_(User))  # = ANY (SELECT ...)
lit("admin") == any_(User.tags)  # リストのどれかと等しい
```

`.scalar()` を付けずにステートメントを式の位置に渡しても、自動でスカラーサブクエリになります。

## その他 {#misc}

```python
from parrotlet import positional, try_

try_(val("x").cast(qlt.Integer))  # TRY(CAST(? AS INTEGER))：エラーの代わりに NULL
positional(1)  # #1：FROM の1番目のカラム
```

## ラムダとリスト内包表記 {#lambdas}

Python のラムダは DuckDB のラムダになります。ラムダの引数にも型が付きます。

```python
fn.list_transform(User.tags, lambda t: fn.upper(t))
# list_transform("users"."tags", lambda "t": upper("t"))

fn.list_filter(User.tags, lambda t: t != "")
fn.list_reduce(col("xs", type_=qlt.List(qlt.Integer)), lambda acc, x: acc + x)

# 2つ目の引数は 1 始まりのインデックス
fn.list_transform(User.tags, lambda t, i: fn.concat(i, ":", t))
```

リスト内包表記は `list_comprehension()` で書きます。

```python
from parrotlet import list_comprehension

xs = col("xs", type_=qlt.List(qlt.Integer))
list_comprehension(xs, lambda x: x * 2, where=lambda x: x > 0)
# [("x" * ?) FOR "x" IN "xs" IF ("x" > ?)]
```

ラムダの引数名は、そのまま SQL のラムダの引数名になります。テーブルのカラムと同じ名前を付けると紛らわしいので避けてください。

## 別名と並び順

```python
User.name.as_("n")  # "users"."name" AS "n"
User.age.desc()  # "users"."age" DESC
User.age.asc(nulls="first")  # "users"."age" ASC NULLS FIRST
User.age.desc(nulls="last")  # "users"."age" DESC NULLS LAST
```

`.as_()` や `.desc()` の結果は式ではないので、さらに演算子をつなげられません。SELECT リストや ORDER BY に渡すときの最後に付けてください。

集約関数とウィンドウ関数は[集約とウィンドウ関数](aggregates.md)を参照してください。
