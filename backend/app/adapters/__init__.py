from .orders_base import FetchResult, MappedResult, OrderRow, Source, map_rows  # noqa: F401
from .orders_file import FileSource  # noqa: F401
from .orders_http import HttpSource  # noqa: F401
from .orders_sql import SqlSource  # noqa: F401


def get_source(settings) -> Source:
    if settings.orders_source == "http":
        return HttpSource(settings)
    if settings.orders_source == "sql":
        return SqlSource(settings)
    return FileSource(settings)
