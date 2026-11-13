# 型安全

parrotlet の式はすべて `Expr[T]` です。`T` は `parrotlet.sqltypes` の SQL 型（`Integer`、`Varchar`、`Timestamp`、`List[T]`、`Geometry` など）で、静的な型チェックのためだけに存在します（実行時には使われません）。

## 暗黙キャストを表す型の階層

SQL 型のクラスは、DuckDB の暗黙キャストに合わせて継承関係を持っています。

```text
TinyInt ⊂ SmallInt ⊂ Integer ⊂ BigInt ⊂ HugeInt ⊂ Decimal ⊂ Double
Float ⊂ Double
Date ⊂ Timestamp ⊂ TimestampTz
Time ⊂ TimeTz
Json, Enum ⊂ Varchar
Array[T] ⊂ List[T]
```

そのため、DuckDB で通る組み合わせはそのまま型チェックも通ります（`Expr[Integer]` は `Expr[Double]` を取る関数に渡せます）。

## 演算子

```python
User.age + 1  # Expr[BigInt]
User.age + 1.5  # Expr[Double]
User.age / 2  # Expr[Double]（DuckDB の / は浮動小数点除算）
User.age // 2  # Expr[BigInt]
Order.ordered_at - Order.ordered_at  # Expr[Interval]
User.born + 1  # Expr[Date]
User.tags[1]  # List[Varchar] の要素 → Expr[Varchar]
(User.age > 20) & (User.name == "a")  # Expr[Boolean]
```

次のような書き方は型エラーになります。

```python
User.name > 3  # VARCHAR と数値は比較できない
User.age < User.name  # 型のファミリーが違う
User.name + 1  # 文字列に算術演算はできない
User.age & User.age  # & | ~ は Boolean のみ
User.age.like("a%")  # like は VARCHAR のみ
```

`==` と `!=` だけは注意が必要です。Python の仕様で、比較できない型の組み合わせ（`User.id == "1"`）は型エラーにならず、`bool` として扱われます。ただし `where()` などは `Expr[Boolean]` しか受け付けないので、実際に誤用すると検出されます。

## 条件

WHERE / HAVING / QUALIFY / JOIN ON / CHECK / CASE WHEN / FILTER には、`Expr[Boolean]` しか渡せません。

```python
select(User.id).from_(User).where(User.name)  # 型エラー
select(User.id).from_(User).join(Order, Order.id)  # 型エラー
```

## 関数

生成された関数は、引数と戻り値に型が付いています。

```python
F.upper(User.name)  # Func[Varchar]
F.date_trunc("day", User.born)  # Func[Timestamp]
F.sum(Order.amount)  # AggregateFunc[Decimal]
F.coalesce(User.age, 0)  # Func[BigInt]（引数の型から決まる）
F.list_transform(User.tags, lambda s: F.length(s))  # Func[List[BigInt]]
F.upper(User.age)  # 型エラー
select(F.row_number())  # 型エラー：window 関数は .over() が必要
```

## CAST と値

```python
User.age.cast(dt.VARCHAR)  # Expr[Varchar]
val(1)  # Param[Integer]（Python の型から推論）
lit("x")  # Lit[Varchar]（インラインのリテラル）
```

## 型なしの式

次のものは型なし（`Expr[Any]`）で、どこにでも使えます。

- `col("name")`
- `table("t").c.name`
- `sql(t"...")`
- `func.<name>(...)`
- 型を推論できないカラム

型を付けたいときは、`col("age", type_=dt.INTEGER)` や `sql(t"...").cast(dt.DATE)` を使います。
