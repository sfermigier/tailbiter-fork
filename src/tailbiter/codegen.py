import ast
import collections
import dis
import types
from functools import reduce

from .assembly import (
    Label,
    OffsetStack,
    SetLineNo,
    assemble,
    concat,
    make_lnotab,
    no_op,
    op,
    plumb_depths,
)
from .exceptions import CodegenException


def collect(table):
    return tuple(sorted(table, key=table.get))


class CodeGen(ast.NodeVisitor):
    def __init__(self, filename, scope):
        self.filename = filename
        self.scope = scope
        self.constants = make_table()
        self.names = make_table()
        self.varnames = make_table()

    def compile_module(self, t, name):
        assembly = self(t.body) + self.load_const(None) + op.RETURN_VALUE
        return self.make_code(assembly, name, 0, False, False)

    def make_code(self, assembly, name, argcount, has_varargs, has_varkws):
        kwonlyargcount = 0
        nlocals = len(self.varnames)
        stacksize = plumb_depths(assembly)
        flags = (
            (0x02 if nlocals else 0)
            | (0x04 if has_varargs else 0)
            | (0x08 if has_varkws else 0)
            | (0x10 if self.scope.freevars else 0)
            | (0x40 if not self.scope.derefvars else 0)
        )
        firstlineno, lnotab = make_lnotab(assembly)
        # FIXME: args should be: __argcount, __posonlyargcount, __kwonlyargcount, __nlocals, __stacksize, __flags, __codestring, __constants, __names, __varnames, __filename, __name, __qualname, __firstlineno, __linetable, #, __freevars=..., __cellvars=...
        return types.CodeType(
            argcount, # __argcount
            0, # __posonlyargcount
            kwonlyargcount, # __kwonlyargcount
            nlocals, # __nlocals
            stacksize, # __stacksize
            flags, # __flags
            assemble(assembly), # __codestring
            self.collect_constants(),  # __constants
            collect(self.names), # __names
            collect(self.varnames), # __varnames
            self.filename, # __filename
            name, # __name
            firstlineno, # __firstlineno
            lnotab, # __linetable
            self.scope.freevars,  # __freevars
            self.scope.cellvars,  # __cellvars
        )

    def load_const(self, constant):
        return op.LOAD_CONST(self.constants[constant, type(constant)])

    def collect_constants(self):
        return tuple([constant for constant, _ in collect(self.constants)])

    def visit_NameConstant(self, t):
        return self.load_const(t.value)

    def visit_Num(self, t):
        return self.load_const(t.n)

    def visit_Str(self, t):
        return self.load_const(t.s)

    visit_Bytes = visit_Str

    def visit_Name(self, t: ast.Name):
        match t.ctx:
            case ast.Load():
                return self.load(t.id)
            case ast.Store():
                return self.store(t.id)
            # TODO
            # case ast.Del():
            #     return self.delete(t.id)
            case _:
                raise CodegenException(f"Unknown context: {t.ctx}")

    def load(self, name):
        access = self.scope.access(name)
        match access:
            case "fast":
                return op.LOAD_FAST(self.varnames[name])
            case "deref":
                return op.LOAD_DEREF(self.cell_index(name))
            case "name":
                return op.LOAD_NAME(self.names[name])
            case _:
                raise CodegenException(f"Unknown access type: {access}")

    def store(self, name):
        access = self.scope.access(name)
        match access:
            case "fast":
                return op.STORE_FAST(self.varnames[name])
            case "deref":
                return op.STORE_DEREF(self.cell_index(name))
            case "name":
                return op.STORE_NAME(self.names[name])
            case _:
                raise CodegenException(f"Unknown access type: {access}")

    def cell_index(self, name):
        return self.scope.derefvars.index(name)

    def visit_Call(self, t):
        assert len(t.args) < 256 and len(t.keywords) < 256
        opcode = (
            op.CALL_FUNCTION_VAR_KW
            if t.starargs and t.kwargs
            else op.CALL_FUNCTION_VAR
            if t.starargs
            else op.CALL_FUNCTION_KW
            if t.kwargs
            else op.CALL_FUNCTION
        )
        return (
            self(t.func)
            + self(t.args)
            + self(t.keywords)
            + (self(t.starargs) if t.starargs else no_op)
            + (self(t.kwargs) if t.kwargs else no_op)
            + opcode((len(t.keywords) << 8) | len(t.args))
        )

    def visit_keyword(self, t):
        return self.load_const(t.arg) + self(t.value)

    def __call__(self, t):
        if isinstance(t, list):
            return concat(map(self, t))
        assembly = self.visit(t)
        return SetLineNo(t.lineno) + assembly if hasattr(t, "lineno") else assembly

    def generic_visit(self, t):
        assert False, t

    def visit_Expr(self, t):
        return self(t.value) + op.POP_TOP

    def visit_Assign(self, t):
        def compose(left, right):
            return op.DUP_TOP + left + right

        return self(t.value) + reduce(compose, map(self, t.targets))

    def visit_If(self, t):
        orelse, after = Label(), Label()
        return (
            self(t.test)
            + op.POP_JUMP_IF_FALSE(orelse)
            + self(t.body)
            + op.JUMP_FORWARD(after)
            + orelse
            + self(t.orelse)
            + after
        )

    def visit_IfExp(self, t):
        orelse, after = Label(), Label()
        return (
            self(t.test)
            + op.POP_JUMP_IF_FALSE(orelse)
            + self(t.body)
            + op.JUMP_FORWARD(after)
            + OffsetStack()
            + orelse
            + self(t.orelse)
            + after
        )

    def visit_Dict(self, t):
        return op.BUILD_MAP(min(0xFFFF, len(t.keys))) + concat(
            [self(v) + self(k) + op.STORE_MAP for k, v in zip(t.keys, t.values)]
        )

    def visit_Subscript(self, t):
        return self(t.value) + self(t.slice.value) + self.subscr_ops[type(t.ctx)]

    subscr_ops = {ast.Load: op.BINARY_SUBSCR, ast.Store: op.STORE_SUBSCR}

    def visit_Attribute(self, t):
        sub_op = self.attr_ops[type(t.ctx)]
        return self(t.value) + sub_op(self.names[t.attr])

    attr_ops = {ast.Load: op.LOAD_ATTR, ast.Store: op.STORE_ATTR}

    def visit_List(self, t):
        return self.visit_sequence(t, op.BUILD_LIST)

    def visit_Tuple(self, t):
        return self.visit_sequence(t, op.BUILD_TUPLE)

    def visit_sequence(self, t, build_op):
        match t.ctx:
            case ast.Load:
                return self(t.elts) + build_op(len(t.elts))
            case ast.Store:
                return op.UNPACK_SEQUENCE(len(t.elts)) + self(t.elts)
            case _:
                raise CodegenException("Unknown context for sequence")

    def visit_UnaryOp(self, t):
        return self(t.operand) + self.ops1[type(t.op)]

    ops1 = {
        ast.UAdd: op.UNARY_POSITIVE,
        ast.Invert: op.UNARY_INVERT,
        ast.USub: op.UNARY_NEGATIVE,
        ast.Not: op.UNARY_NOT,
    }

    def visit_BinOp(self, t):
        return self(t.left) + self(t.right) + self.ops2[type(t.op)]

    # FIXME: this has changed
    ops2 = {
        # ast.Pow: op.BINARY_POWER,
        # ast.Add: op.BINARY_ADD,
        # ast.LShift: op.BINARY_LSHIFT,
        # ast.Sub: op.BINARY_SUBTRACT,
        # ast.RShift: op.BINARY_RSHIFT,
        # ast.Mult: op.BINARY_MULTIPLY,
        # ast.BitOr: op.BINARY_OR,
        # ast.Mod: op.BINARY_MODULO,
        # ast.BitAnd: op.BINARY_AND,
        # ast.Div: op.BINARY_TRUE_DIVIDE,
        # ast.BitXor: op.BINARY_XOR,
        # ast.FloorDiv: op.BINARY_FLOOR_DIVIDE,
    }

    def visit_Compare(self, t):
        [operator], [right] = t.ops, t.comparators
        cmp_index = dis.cmp_op.index(self.ops_cmp[type(operator)])
        return self(t.left) + self(right) + op.COMPARE_OP(cmp_index)

    ops_cmp = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Is: "is",
        ast.IsNot: "is not",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.In: "in",
        ast.NotIn: "not in",
        ast.Gt: ">",
        ast.GtE: ">=",
    }

    def visit_BoolOp(self, t):
        op_jump = self.ops_bool[type(t.op)]

        def compose(left, right):
            after = Label()
            return left + op_jump(after) + OffsetStack() + right + after

        return reduce(compose, map(self, t.values))

    ops_bool = {
        ast.And: op.JUMP_IF_FALSE_OR_POP,
        ast.Or: op.JUMP_IF_TRUE_OR_POP,
    }

    def visit_Pass(self, t):
        return no_op

    def visit_Raise(self, t):
        return self(t.exc) + op.RAISE_VARARGS(1)

    def visit_Import(self, t):
        return concat(
            [
                self.import_name(0, None, alias.name)
                + self.store(alias.asname or alias.name.split(".")[0])
                for alias in t.names
            ]
        )

    def visit_ImportFrom(self, t):
        fromlist = tuple([alias.name for alias in t.names])
        return (
            self.import_name(t.level, fromlist, t.module)
            + concat(
                [
                    op.IMPORT_FROM(self.names[alias.name])
                    + self.store(alias.asname or alias.name)
                    for alias in t.names
                ]
            )
            + op.POP_TOP
        )

    def import_name(self, level, fromlist, name):
        return (
            self.load_const(level)
            + self.load_const(fromlist)
            + op.IMPORT_NAME(self.names[name])
        )

    def visit_While(self, t):
        loop, end = Label(), Label()
        return (
            loop
            + self(t.test)
            + op.POP_JUMP_IF_FALSE(end)
            + self(t.body)
            + op.JUMP_ABSOLUTE(loop)
            + end
        )

    def visit_For(self, t):
        loop, end = Label(), Label()
        return (
            self(t.iter)
            + op.GET_ITER
            + loop
            + op.FOR_ITER(end)
            + self(t.target)
            + self(t.body)
            + op.JUMP_ABSOLUTE(loop)
            + end
            + OffsetStack()
        )

    def visit_Return(self, t):
        return (self(t.value) if t.value else self.load_const(None)) + op.RETURN_VALUE

    def visit_Function(self, t):
        code = self.sprout(t).compile_function(t)
        return self.make_closure(code, t.name)

    def sprout(self, t):
        return CodeGen(self.filename, self.scope.children[t])

    def make_closure(self, code, name):
        if code.co_freevars:
            return (
                concat(
                    [
                        op.LOAD_CLOSURE(self.cell_index(freevar))
                        for freevar in code.co_freevars
                    ]
                )
                + op.BUILD_TUPLE(len(code.co_freevars))
                + self.load_const(code)
                + self.load_const(name)
                + op.MAKE_CLOSURE(0)
            )
        else:
            return self.load_const(code) + self.load_const(name) + op.MAKE_FUNCTION(0)

    def compile_function(self, t):
        self.load_const(ast.get_docstring(t))
        for arg in t.args.args:
            self.varnames[arg.arg]
        if t.args.vararg:
            self.varnames[t.args.vararg.arg]
        if t.args.kwarg:
            self.varnames[t.args.kwarg.arg]
        assembly = self(t.body) + self.load_const(None) + op.RETURN_VALUE
        return self.make_code(
            assembly, t.name, len(t.args.args), t.args.vararg, t.args.kwarg
        )

    def visit_ClassDef(self, t):
        code = self.sprout(t).compile_class(t)
        return (
            op.LOAD_BUILD_CLASS
            + self.make_closure(code, t.name)
            + self.load_const(t.name)
            + self(t.bases)
            + op.CALL_FUNCTION(2 + len(t.bases))
            + self.store(t.name)
        )

    def compile_class(self, t):
        docstring = ast.get_docstring(t)
        assembly = (
            self.load("__name__")
            + self.store("__module__")
            + self.load_const(t.name)
            + self.store("__qualname__")
            + (
                no_op
                if docstring is None
                else self.load_const(docstring) + self.store("__doc__")
            )
            + self(t.body)
            + self.load_const(None)
            + op.RETURN_VALUE
        )
        return self.make_code(assembly, t.name, 0, False, False)


def make_table():
    table = collections.defaultdict(lambda: len(table))
    return table
