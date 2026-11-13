"""Typed DuckDB functions.

```python
from parrotlet import functions as F
from parrotlet.functions import spatial as ST, tables as TF

select(F.upper(User.name), F.sum(Order.amount)).from_(User).join(Order, User.id == Order.user_id)
```

Signatures are generated from DuckDB's function catalog (see `scripts/generate_functions.py`), so arguments and return
types are checked: `F.upper(User.age)` is a type error, `F.date_trunc("day", Order.ts)` is a `Func[Timestamp]`.
`parrotlet.func.<name>(...)` remains as an untyped escape hatch.
"""

from parrotlet.functions._core import *  # noqa: F403
from parrotlet.functions._generic import *  # noqa: F403
