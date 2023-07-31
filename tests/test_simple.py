import ast
from unittest import skip

from tailbiter.check_subset import check_conformity
from tailbiter.compiler import module_from_ast, code_for_module
from tailbiter.desugar import desugar

SRC = """
def f(x): pass
# class A:
#     pass
# f(1)
# print(2)
# 2 * 3
"""


# @skip
def test_module():
    t = ast.parse(SRC)
    module = module_from_ast("toto", "toto.py", t)


# @skip
def test_code():
    t = ast.parse(SRC)
    code = code_for_module("toto", "toto.py", t)


def test_desugar():
    t = ast.parse(SRC)
    t = desugar(t)
    check_conformity(t)
