import dis
from itertools import chain


def assemble(assembly):
    return bytes(iter(assembly.encode(0, dict(assembly.resolve(0)))))


def plumb_depths(assembly):
    depths = [0]
    assembly.plumb(depths)
    return max(depths)


def make_lnotab(assembly):
    firstlineno = None
    lnotab = []
    byte = 0
    line = None
    for next_byte, next_line in assembly.line_nos(0):
        if firstlineno is None:
            firstlineno = line = next_line
        elif line < next_line:
            while byte + 255 < next_byte:
                lnotab.extend([255, 0])
                byte += 255
            while line + 255 < next_line:
                lnotab.extend([next_byte - byte, 255])
                byte, line = next_byte, line + 255
            if (byte, line) != (next_byte, next_line):
                lnotab.extend([next_byte - byte, next_line - line])
                byte, line = next_byte, next_line

    return firstlineno or 1, bytes(lnotab)


def concat(assemblies):
    return sum(assemblies, no_op)


class Assembly:
    def __add__(self, other):
        return Chain(self, other)

    length = 0

    def resolve(self, start):
        return ()

    def encode(self, start, addresses):
        return b""

    def line_nos(self, start):
        return ()

    def plumb(self, depths):
        pass


no_op = Assembly()


class Label(Assembly):
    def resolve(self, start):
        return ((self, start),)


class SetLineNo(Assembly):
    def __init__(self, line):
        self.line = line

    def line_nos(self, start):
        return ((start, self.line),)


class Instruction(Assembly):
    def __init__(self, opcode, arg):
        self.opcode = opcode
        self.arg = arg
        self.length = 1 if arg is None else 3

    def encode(self, start, addresses):
        if self.opcode in dis.hasjabs:
            arg = addresses[self.arg]
        elif self.opcode in dis.hasjrel:
            arg = addresses[self.arg] - (start + 3)
        else:
            arg = self.arg
        if arg is None:
            return bytes([self.opcode])
        else:
            return bytes([self.opcode, arg % 256, arg // 256])

    def plumb(self, depths):
        arg = 0 if isinstance(self.arg, Label) else self.arg
        depths.append(depths[-1] + dis.stack_effect(self.opcode, arg))


class Chain(Assembly):
    def __init__(self, assembly1, assembly2):
        self.part1 = assembly1
        self.part2 = assembly2
        self.length = assembly1.length + assembly2.length

    def resolve(self, start):
        return chain(
            self.part1.resolve(start),
            self.part2.resolve(start + self.part1.length),
        )

    def encode(self, start, addresses):
        return chain(
            self.part1.encode(start, addresses),
            self.part2.encode(start + self.part1.length, addresses),
        )

    def line_nos(self, start):
        return chain(
            self.part1.line_nos(start),
            self.part2.line_nos(start + self.part1.length),
        )

    def plumb(self, depths):
        self.part1.plumb(depths)
        self.part2.plumb(depths)


class OffsetStack(Assembly):
    def plumb(self, depths):
        depths.append(depths[-1] - 1)


def denotation(opcode):
    if opcode < dis.HAVE_ARGUMENT:
        return Instruction(opcode, None)
    else:
        return lambda arg: Instruction(opcode, arg)


op = type(
    "op",
    (),
    dict([(name, denotation(opcode)) for name, opcode in dis.opmap.items()]),
)
