import ast


class Function(ast.FunctionDef):
    _fields = ("name", "args", "body")

