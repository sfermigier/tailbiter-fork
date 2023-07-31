import ast

from ._ast import Function


def desugar(t):
    return ast.fix_missing_locations(Desugarer().visit(t))


def rewriter(rewrite):
    def visit(self, t):
        return ast.copy_location(rewrite(self, self.generic_visit(t)), t)

    return visit


def Call(fn, args):
    return ast.Call(fn, args, [], None, None)


load, store = ast.Load(), ast.Store()


class Desugarer(ast.NodeTransformer):
    @rewriter
    def visit_Assert(self, t):
        return ast.If(
            t.test,
            [],
            [
                ast.Raise(
                    Call(
                        ast.Name("AssertionError", load),
                        [] if t.msg is None else [t.msg],
                    ),
                    None,
                )
            ],
        )

    @rewriter
    def visit_Lambda(self, t):
        return Function("<lambda>", t.args, [ast.Return(t.body)])

    @rewriter
    def visit_FunctionDef(self, t):
        fn = Function(t.name, t.args, t.body)
        for d in reversed(t.decorator_list):
            fn = Call(d, [fn])
        return ast.Assign([ast.Name(t.name, store)], fn)

    @rewriter
    def visit_ListComp(self, t):
        result_append = ast.Attribute(ast.Name(".0", load), "append", load)
        body = ast.Expr(Call(result_append, [t.elt]))
        for loop in reversed(t.generators):
            for test in reversed(loop.ifs):
                body = ast.If(test, [body], [])
            body = ast.For(loop.target, loop.iter, [body], [])
        fn = [body, ast.Return(ast.Name(".0", load))]
        args = ast.arguments([ast.arg(".0", None)], None, [], None, [], [])
        return Call(Function("<listcomp>", args, fn), [ast.List([], load)])
