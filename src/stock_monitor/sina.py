"""旧模块名兼容入口；正式实现为 xinlang.py。"""
import sys
from . import xinlang

sys.modules[__name__] = xinlang
