"""死锁/活锁分析报告的只读用户展示格式。"""

from .serializer import format_lock_freedom_full, format_lock_freedom_result

__all__ = ["format_lock_freedom_full", "format_lock_freedom_result"]
