# -*- coding: utf-8 -*-
"""后端应用包。

这里导入 config 是刻意的：它会把 knowledge_base 目录加入 sys.path，
之后任何模块（包括 server、answer、tests）再 `import kb` 都不会失败。
"""
from . import config  # noqa: F401
