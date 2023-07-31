import ast
import sys
import types

from .check_subset import check_conformity
from .codegen import CodeGen
from .desugar import desugar
from .scope import top_scope


def load_file(filename, module_name):
    f = open(filename)
    source = f.read()
    f.close()
    return module_from_ast(module_name, filename, ast.parse(source))


def module_from_ast(module_name, filename, t):
    code = code_for_module(module_name, filename, t)
    module = types.ModuleType(module_name, ast.get_docstring(t))
    exec(code, module.__dict__)
    return module


def code_for_module(module_name, filename, t):
    t = desugar(t)
    check_conformity(t)
    return CodeGen(filename, top_scope(t)).compile_module(t, module_name)


if __name__ == "__main__":
    sys.argv.pop(0)
    load_file(sys.argv[0], "__main__")
