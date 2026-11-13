"""Typed DuckDB functions.

```python
import parrotlet.functions as fn

select(fn.upper(User.name), fn.sum(Order.amount)).from_(User).join(Order, User.id == Order.user_id)
```

Signatures are generated from DuckDB's function catalog (see `scripts/generate_functions.py`), so arguments and return
types are checked: `fn.upper(User.age)` is a type error, `fn.date_trunc("day", Order.ts)` is a `Func[Timestamp]`.
Table functions are in `fn.table`, the spatial extension's functions in `fn.spatial`.
`parrotlet.func.<name>(...)` remains as an untyped escape hatch.
"""

from parrotlet.functions import _core as _core
from parrotlet.functions import _generic as _generic
from parrotlet.functions import spatial, table
from parrotlet.functions._core import *  # noqa: F403
from parrotlet.functions._generic import *  # noqa: F403

__all__ = ["spatial", "table"]
__all__ += _core.__all__
__all__ += _generic.__all__
