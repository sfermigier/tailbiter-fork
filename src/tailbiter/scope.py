import ast

from ._ast import Function


def top_scope(t):
    top = Scope(t, ())
    top.visit(t)
    top.analyze(set())
    return top


class Scope(ast.NodeVisitor):
    def __init__(self, t, defs):
        self.t = t
        self.children = {}  # Enclosed sub-scopes
        self.defs = set(defs)  # Variables defined
        self.uses = set()  # Variables referenced

    def visit_ClassDef(self, t):
        self.defs.add(t.name)
        for expr in t.bases:
            self.visit(expr)
        subscope = Scope(t, ())
        self.children[t] = subscope
        for stmt in t.body:
            subscope.visit(stmt)

    def visit_Function(self, t):
        all_args = list(t.args.args) + [t.args.vararg, t.args.kwarg]
        subscope = Scope(t, [arg.arg for arg in all_args if arg])
        self.children[t] = subscope
        for stmt in t.body:
            subscope.visit(stmt)

    def visit_Import(self, t):
        for alias in t.names:
            self.defs.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, t):
        for alias in t.names:
            self.defs.add(alias.asname or alias.name)

    def visit_Name(self, t):
        if isinstance(t.ctx, ast.Load):
            self.uses.add(t.id)
        elif isinstance(t.ctx, ast.Store):
            self.defs.add(t.id)
        else:
            assert False

    def analyze(self, parent_defs):
        self.local_defs = self.defs if isinstance(self.t, Function) else set()
        for child in self.children.values():
            child.analyze(parent_defs | self.local_defs)
        child_uses = set(
            [var for child in self.children.values() for var in child.freevars]
        )
        uses = self.uses | child_uses
        self.cellvars = tuple(child_uses & self.local_defs)
        self.freevars = tuple(uses & (parent_defs - self.local_defs))
        self.derefvars = self.cellvars + self.freevars

    def access(self, name):
        return (
            "deref"
            if name in self.derefvars
            else "fast"
            if name in self.local_defs
            else "name"
        )
