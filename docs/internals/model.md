# モデル

`Model` は、1つのクラスでテーブル定義と行型を兼ねます。このページでは、それを実現している `Model.__init_subclass__`、`Column` デスクリプタ、型の推論、CREATE TABLE の生成を説明します。使い方は[ガイドのモデル](../guide/models.md)を参照してください。

```python
class User(Model, table="users"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    age: Column[int | None] = column(default=None, check=lambda c: c.age >= 0)
```

## クラスが作られるとき：`__init_subclass__`

`Model` のサブクラスを定義すると、`Model.__init_subclass__` がクラスのアノテーションを読み、カラムを組み立てます。

1. `typing.get_type_hints(cls)` で、基底クラスを含むすべてのアノテーションを解決する（評価できない前方参照があれば、生の `__annotations__` にフォールバックする）
2. `_` で始まる名前と `ClassVar` を読み飛ばす
3. `Column[X]` なら中身の `X` を取り出す
4. クラス属性を見て、カラムのデスクリプタを決める
    - `column(...)` が代入されていれば、それを使う
    - 普通の値（`age: Column[int] = 0`）なら、`Column(default=0)` を作って差し替える
    - 何も代入されていなければ、`Column()` を作って差し替える
5. `Column.resolve(X)` で、アノテーションから SQL 型と NULL 許可を決める
6. カラムを `cls.__columns__` に、テーブルを `cls.__table__` に記録する

テーブル名は、クラスキーワードの `table=`、親モデルのテーブル名、クラス名のスネークケース（`OrderItem` → `order_item`）の順で決まります。`abstract=True` のモデルはテーブルを持たず、カラムだけを子クラスに引き継ぎます。

`constraints` という名前のカラムは、テーブル制約を返すクラスメソッドと衝突するので、エラーになります。

## アノテーションから SQL 型を推論する

`infer_type()` は、Python の型を DuckDB の型と NULL 許可に変換します。

| Python の型 | DuckDB の型 |
|---|---|
| `bool` | `BOOLEAN`（`int` より先に判定する。`bool` は `int` のサブクラスのため） |
| `int` | `BIGINT` |
| `float` | `DOUBLE` |
| `Decimal` | `DECIMAL(18, 3)` |
| `str` | `VARCHAR` |
| `bytes` | `BLOB` |
| `UUID` | `UUID` |
| `datetime` | `TIMESTAMP`（`date` より先に判定する） |
| `date` / `time` / `timedelta` | `DATE` / `TIME` / `INTERVAL` |
| shapely のジオメトリ | `GEOMETRY` |
| `list[X]` | `X[]`（再帰的に推論） |
| `dict[K, V]` | `MAP(K, V)` |

`X | None` は NULL を許可し、それ以外は `NOT NULL` になります。推論できない型は `TypeError` になるので、`column(qlt.Integer)` のように型を明示します。

## Column デスクリプタ {#column-descriptor}

`Column` はデータデスクリプタ（`__get__` と `__set__` を持つ）です。クラスから参照するか、インスタンスから参照するかで、返すものが変わります。

```python
def __get__(self, obj, owner):
    if obj is None:  # User.age
        table = getattr(owner, "__table__", None)
        return ColumnRef(self.name, table.qualifier() if table else ())
    return obj.__dict__[self.attr]  # user.age
```

- `User.age` は `ColumnRef("age", ("users",))` になり、クエリで使える
- `user.age` はインスタンスの `__dict__` に入っている値を返す

`__get__` には、型チェッカー向けのオーバーロードがあります。`Column[X]` の `X` が `int` なら `ColumnRef[BigInt]`、`str` なら `ColumnRef[Varchar]`、というように、Python の型から SQL の幽霊型を決めます。`self: Column[X] | Column[X | None]` という形で、`Column[int]` と `Column[int | None]` の両方に一致させています。インスタンスから参照したときの型は `P`（`Column[P]` の型引数そのもの）です。

`ColumnRef` は参照されるたびに新しく作られます。修飾子は `owner.__table__` から取るので、後述の `aliased()` でサブクラスを作ると、同じデスクリプタが別の修飾子を返します。

`__set_name__` で、属性名（`attr`）と所有クラス（`owner`）を記録します。SQL 上のカラム名は、`column(name=...)` を指定しなければ属性名と同じです。

## インスタンス：行としての Model

`Model.__init__` は、キーワード引数だけを受け付けます。

- 渡された値を `__dict__` に入れる
- 渡されなかったカラムは `Column.initial_value()` で埋める：`default`、`default_factory()`、データベース側のデフォルトがあれば `DEFAULT` キーワード、どれもなければ `TypeError`
- 知らないキーワードは `TypeError`

```python
>>> User(id=1, name="a")
User(id=1, name='a', age=None, joined=Keyword(keyword='DEFAULT'))
>>> db.insert(User).values(User(id=1, name="a")).sql
'INSERT INTO "users" ("id", "name", "age", "joined") VALUES (?, ?, ?, DEFAULT)'
```

`column(default=fn.now())` のように SQL 式をデフォルトにすると、Python 側の値は `DEFAULT` キーワードになり、INSERT ではデータベースが値を埋めます。

`@dataclass_transform(kw_only_default=True, field_specifiers=(column, Column))` を付けているので、型チェッカーは `Model` のサブクラスを dataclass のように扱います。コンストラクタの引数名・型・省略可能かどうかが検査され、`column()` に `default` や `default_factory` があれば省略可能と判断されます。`column()` の戻り値を `Any` にしているのは、どの `Column[T]` アノテーションにも代入できるようにするためです。

その他のメソッドは次のとおりです。

| メソッド | 働き |
|---|---|
| `to_dict()` | `{属性名: 値}` |
| `to_row()` | `{SQL のカラム名: 値}`（INSERT と appender で使う） |
| `from_row(row)` | `{SQL のカラム名: 値}` からインスタンスを作る。`__init__` を通さず、GEOMETRY のカラムは WKB から shapely に戻す |
| `__eq__` | 同じクラスで `to_dict()` が等しければ等しい。可変なので `__hash__ = None` |

## CREATE TABLE の生成

`create_table(User)` は、`User.__columns__` と `User.constraints()` から `CreateTable` を作ります。各カラムは `Column.definition()` で次のように出力されます。

```text
"name" 型 [COLLATE ...] [PRIMARY KEY] [NOT NULL] [UNIQUE] [DEFAULT ...]
  [CHECK (...)] [REFERENCES ...] [GENERATED ALWAYS AS (...) VIRTUAL]
```

- `PRIMARY KEY` のカラムには `NOT NULL` を付けない（主キーは暗黙に NOT NULL）
- `DEFAULT` には、`server_default` か、Python の `default` を使う。`None` や呼び出し可能なもの（`default_factory` 相当）は SQL の DEFAULT にしない
- `check=lambda c: c.age >= 0` や `generated=lambda c: c.price * 2` のようなラムダは、ビルドするときに `owner` クラスを渡して評価する。クラス定義の途中ではまだ `User.age` が使えないため、評価を遅らせている
- 外部キーの参照先は `User.id`、`"users.id"`、`User`（主キーを参照）、同じクラスのカラムのどれでも書ける

カラム定義全体は `inline_params()` と `unqualified_columns()` の中でビルドされます。DDL は `?` を受け付けないので値はリテラルになり、`CHECK` の中のカラム名はテーブル名なしで出力されます（[SQL の組み立て](compilation.md#context-vars)）。

`constraints()` クラスメソッドは、CREATE TABLE を作るときに呼ばれます。クラスの定義が終わった後なので、`cls.name` などのカラムを使えます。

## `aliased()`：自己結合のための別名

```python
Boss = aliased(User, "boss")
select(User.name, Boss.name).from_(User).join(Boss, User.id == Boss.id)
# SELECT "users"."name", "boss"."name"
#   FROM "users" INNER JOIN "users" AS "boss" ON ("users"."id" = "boss"."id")
```

`aliased()` は `types.new_class` で `User` のサブクラスを作り、クラスキーワード `_alias="boss"` を渡します。`__init_subclass__` は親のテーブル名を引き継いだ `Table("users", alias="boss")` を `__table__` に設定します。

カラムのデスクリプタは親クラスのものがそのまま継承されますが、`__get__` は `owner.__table__.qualifier()` を見るので、`Boss.name` は `"boss"."name"` になります。`Table.qualifier()` は、別名があれば別名だけを、なければ `catalog.schema.name` を返します。

型の上では `aliased()` は `type[User]` を返すので、`Boss.name` も `ColumnRef[Varchar]` として型付けされます。
