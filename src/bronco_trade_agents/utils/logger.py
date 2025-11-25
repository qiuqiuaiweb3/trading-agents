import logging
import sys
from rich.logging import RichHandler

def setup_logging(level=logging.INFO):
    """
    配置全局日志，使用 Rich 美化输出。
    """
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)]
    )
    
    # 调整部分嘈杂库的日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
