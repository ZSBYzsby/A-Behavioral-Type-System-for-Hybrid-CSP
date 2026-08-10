"""Process 层自有的、与外部工具无关的表达式抽象语法树。

HCSP 节点内部只保存本模块定义的 :class:`Expr`。为了让示例保持简洁，节点
构造器仍允许传入 ``"x + 1"`` 或整数；这些便捷输入会在构造阶段立即转换成
严格 AST，而不会原样留在程序树中。

────────────────── 明确支持的表达式 ────────────────────────────────────────

* 字面量：布尔、整数和实数；
* 标量变量：``x``、``velocity`` 等满足
  ``[A-Za-z_][A-Za-z0-9_]*`` 的 ASCII 标识符；
* 一元运算：``not B``、``+e``、``-e``；
* 算术运算：``+``、``-``、``*``、``/``、``%``、``**``；其中 ``/`` 的
  除数必须非零，``%`` 只接受 Nat/Int 操作数；
* 乘方便捷记号：``e ^ e``；它与 ``**`` 使用相同的高优先级和右结合性，
  进入 AST 后统一保存为 ``e ** e``；
* 布尔连接：``B1 and B2``、``B1 or B2``；
* 比较：``==``、``!=``、``<``、``<=``、``>``、``>=``；
* 链式比较：``0 <= x < limit``；
* 简单函数调用：``sqrt(x)``、``abs(x)``、``f(x, y)``，函数必须是普通名称；
  ``sqrt`` 的实数参数必须非负。

除零、负数平方根等是“语法合法但在某些状态下求值无定义”的表达式。解析器
保留其 AST，后续类型规则必须证明相应有定义条件；不能证明时检查结果为
``false``，而不是采用 SMT 求解器对偏运算的任意全函数扩展。

支持的字符串语法可概括如下，其中 ``c`` 是上述字面量，``x`` 和 ``f`` 是
满足项目 ASCII IDENT 规则的标识符：

.. code-block:: text

    e ::= c
        | x
        | +e | -e
        | e + e | e - e | e * e | e / e | e % e
        | e ** e | e ^ e
        | f(e, ..., e)

    B ::= true | false
        | not B
        | B and B | B or B
        | e == e | e != e
        | e < e | e <= e | e > e | e >= e
        | e relation e relation ... e

解析前还接受常见 HCSP 记号：``&&``、``||``、``!`` 和 ``<->`` 分别规范化
为 ``and``、``or``、``not`` 和 ``==``；``true``/``false`` 不区分大小写。

────────────────── 明确不支持的表达式 ──────────────────────────────────────

* 表达式级条件：``a if B else b``；条件控制流只能使用 HCSP 进程级
  ``If(B, P, P')``；
* 属性访问和方法调用：``plant.temperature``、``obj.f(x)``；
* 下标和动态调用：``array[i]``、``functions[i](x)``；
* lambda 和推导式：``lambda x: x + 1``、``[f(x) for x in values]``；
* dict、set：``{"x": 1}``、``{x, y}``；
* tuple/list：``(x, y)``、``[x, y]``，以及对应的 Python 容器输入；
* 字符串和 Unit 字面量：``'text'``、``None``；项目的基础值类型不包含
  ``String`` 或 ``Unit``；
* 关键字实参：``f(x=1)``；
* 未定义算术/位运算：``//``、``<<``、``>>``、``&``、``|``；
* 成员或身份比较：``x in values``、``x is None``；
* 表达式内赋值或解构左值：``x := 1``、``(x, y) := value``。

解析器在输入边界直接拒绝以上语法，避免把含义不明确或不属于论文需要的结构
带入 HCSP AST 和后续类型构造阶段。这里拒绝的是“作为一个表达式求值”的
tuple/list。``OutputChannel("ch", (e1, ..., en))`` 会先把最外层 Python
tuple/list 解释为多个独立的标量通信参数，再逐项调用 ``ensure_expr``，因此不构成
tuple 表达式，也不会产生一个 tuple 值。

────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import ast
import io
import re
import tokenize as python_tokenize
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Iterable, TypeAlias

from ...identifiers import is_hcsp_identifier


# --------------------------------------------------------------------------
# 语法对应：表达式语法 e 和布尔公式 B 的共同抽象基类；
#           它们分别进入赋值/输出/ODE 右端和 assert/if/演化域等位置。
# 构造方式：Expr 不直接实例化，由 Literal、Variable、UnaryExpr、
#           BinaryExpr、BooleanExpr、CompareExpr 和 CallExpr 构造具体节点。
# 构造检查：抽象 get_vars 阻止直接实例化裸 Expr；具体节点负责检查自身形状。
# --------------------------------------------------------------------------
class Expr(ABC):
    """所有项目内表达式节点的抽象基类。"""

    # 功能：为所有表达式节点规定统一的自由变量收集接口。
    # 检查/语法关系：变量集合供 HCSP AST 的 fv/V 分析及 Gamma 分区使用；
    #                是否已在 Gamma 声明由后续表达式翻译阶段检查。
    @abstractmethod
    def get_vars(self) -> set[str]:
        """返回表达式中出现的自由变量名；具体节点必须实现。"""


# --------------------------------------------------------------------------
# 语法对应：e ::= c，以及 B ::= true | false；c 只取布尔或数值常量。
# 构造方式：Literal(value)；ensure_expr 也会把 Python 标量转换为本节点。
# 构造检查：只接受项目声明的静态常量类型，拒绝任意外部 Python 对象；
#           常量在具体上下文中的值类型由 ExpressionTranslator 判断。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Literal(Expr):
    """布尔或数值字面量。"""

    value: bool | int | float | Decimal | Fraction

    # 功能：在 dataclass 保存字段后验证常量值属于项目表达式构造边界。
    # 检查/语法关系：保证 c 是受支持的原子常量，
    #                不在此判断它能否用于某个算术或布尔运算。
    def __post_init__(self) -> None:
        """拒绝把任意 Python 对象伪装成静态字面量。"""
        if not isinstance(
            self.value,
            (bool, int, float, Decimal, Fraction),
        ):
            raise TypeError(f"Unsupported literal value: {self.value!r}")

    # 功能：报告常量节点不引用任何状态变量。
    # 检查/语法关系：空集合会进入外层 HCSP 节点的 fv/V 汇总。
    def get_vars(self) -> set[str]:
        """字面量不包含自由变量。"""
        return set()

    # 功能：生成供报告和 dL/Z3 诊断阅读的稳定文本。
    # 检查/语法关系：不重新解析或修改常量。
    def __str__(self) -> str:
        """生成适合诊断的源代码形式。"""
        return str(self.value)


# --------------------------------------------------------------------------
# 语法对应：e ::= x；同一节点也可作为赋值/输入构造器的标量左值。
# 构造方式：Variable("x")；左值位置通常由 ensure_variable 统一构造。
# 构造检查：名称必须满足项目统一的 ASCII IDENT 规则；
#           是否已在 Gamma 声明以及具体类型留给 ExpressionTranslator。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Variable(Expr):
    """标量变量引用。"""

    name: str

    # 功能：在节点冻结后验证变量名的词法形状。
    # 检查/语法关系：拒绝空名、属性路径和带运算符文本，确保节点精确表示 x。
    def __post_init__(self) -> None:
        """变量名必须是合法的简单标识符。"""
        if not is_hcsp_identifier(self.name):
            raise ValueError(f"Invalid variable name: {self.name!r}")

    # 功能：返回该原子变量自身组成的自由变量集合。
    # 检查/语法关系：外层输入或 mu 的绑定分析可以据此移除受绑定出现。
    def get_vars(self) -> set[str]:
        """变量表达式的自由变量就是自身。"""
        return {self.name}

    # 功能：按源码标识符打印变量。
    # 检查/语法关系：名称已经由 __post_init__ 验证，不进行额外转义。
    def __str__(self) -> str:
        """返回源变量名。"""
        return self.name


# --------------------------------------------------------------------------
# 语法对应：e ::= +e | -e，以及 B ::= not B。
# 构造方式：UnaryExpr(op, operand)，其中 op 只能是 "not"、"+" 或 "-"。
# 构造检查：操作符必须属于支持集合，operand 必须已是项目 Expr；
#           数值/布尔类型相容性由 ExpressionTranslator 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class UnaryExpr(Expr):
    """一元否定、正号或负号表达式。"""

    op: str
    operand: Expr

    # 功能：验证一元运算节点的操作符和子节点边界。
    # 检查/语法关系：防止位反等未定义操作进入 AST，但不提前执行类型推断。
    def __post_init__(self) -> None:
        """限制操作符并保证子节点属于本项目 AST。"""
        if self.op not in {"not", "+", "-"}:
            raise ValueError(f"Unsupported unary operator: {self.op!r}")
        if not isinstance(self.operand, Expr):
            raise TypeError("Unary operand must be an Expr")

    # 功能：把操作数的自由变量直接传递给整个一元式。
    # 检查/语法关系：一元运算不绑定或引入新变量。
    def get_vars(self) -> set[str]:
        """返回操作数的自由变量。"""
        return self.operand.get_vars()

    # 功能：用显式括号打印操作数，避免嵌套优先级歧义。
    # 检查/语法关系：not 与算术正负号只在空格形式上有所区别。
    def __str__(self) -> str:
        """使用无歧义括号打印一元表达式。"""
        separator = " " if self.op == "not" else ""
        return f"{self.op}{separator}({self.operand})"


# --------------------------------------------------------------------------
# 语法对应：e ::= e+e | e-e | e*e | e/e | e%e | e**e；
#           输入文本中的 e^e 在 Python 建树前规范为 **，最终只产生 ** 节点。
# 构造方式：BinaryExpr(op, left, right)，左右子节点必须显式为 Expr。
# 构造检查：只允许六种内部算术运算并验证子树类别；
#           操作数值类型和除零等逻辑性质由后续翻译/证明处理。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BinaryExpr(Expr):
    """二元算术表达式。"""

    op: str
    left: Expr
    right: Expr

    # 功能：验证二元算术节点不会携带未定义运算符或外部对象。
    # 检查/语法关系：这里只检查 AST 形状，不计算表达式值。
    def __post_init__(self) -> None:
        """检查运算符及左右子树类型。"""
        if self.op not in {"+", "-", "*", "/", "%", "**"}:
            raise ValueError(f"Unsupported binary operator: {self.op!r}")
        if not isinstance(self.left, Expr) or not isinstance(self.right, Expr):
            raise TypeError("Binary operands must be Expr instances")

    # 功能：取左右算术子式自由变量集合的并集。
    # 检查/语法关系：算术运算不改变变量的自由/绑定身份。
    def get_vars(self) -> set[str]:
        """合并左右操作数的自由变量。"""
        return self.left.get_vars() | self.right.get_vars()

    # 功能：用括号保留二元 AST 的结合顺序。
    # 检查/语法关系：输出面向审计，不依赖读取者自行恢复运算符优先级。
    def __str__(self) -> str:
        """用括号保留原始运算树结构。"""
        return f"({self.left} {self.op} {self.right})"


# --------------------------------------------------------------------------
# 语法对应：B ::= B and B | B or B；实现允许同一运算符的任意元表示。
# 构造方式：BooleanExpr("and" | "or", operands)。
# 构造检查：至少需要两个可规范化表达式，并拒绝其他布尔连接符；
#           每个 operand 是否为 Bool 由 ExpressionTranslator 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BooleanExpr(Expr):
    """任意元 ``and`` 或 ``or`` 表达式。"""

    op: str
    operands: tuple[Expr, ...]

    # 功能：规范化全部布尔子式、检查运算符并冻结至少两个操作数。
    # 检查/语法关系：多元节点只是同类二元连接的紧凑 AST 表示，语义不扩展。
    def __init__(self, op: str, operands: Iterable["ExprLike"]):
        """冻结并验证至少两个布尔操作数。"""
        values = tuple(ensure_expr(item) for item in operands)
        if op not in {"and", "or"}:
            raise ValueError(f"Unsupported Boolean operator: {op!r}")
        if len(values) < 2:
            raise ValueError("BooleanExpr needs at least two operands")
        object.__setattr__(self, "op", op)
        object.__setattr__(self, "operands", values)

    # 功能：合并全部布尔子式的自由变量。
    # 检查/语法关系：and/or 不产生变量绑定。
    def get_vars(self) -> set[str]:
        """合并所有布尔子式的自由变量。"""
        return set().union(*(item.get_vars() for item in self.operands))

    # 功能：按保存顺序打印多元布尔连接，并用括号封闭整体。
    # 检查/语法关系：稳定顺序便于逐项核对原表达式 AST。
    def __str__(self) -> str:
        """用括号和操作符连接所有子式。"""
        return "(" + f" {self.op} ".join(str(item) for item in self.operands) + ")"


# --------------------------------------------------------------------------
# 语法对应：B ::= e==e | e!=e | e<e | e<=e | e>e | e>=e；
#           并支持 e relation e relation ... e 的链式比较。
# 构造方式：CompareExpr(operands, operators)。
# 构造检查：运算符必须受支持，且 n 个运算符必须连接 n+1 个表达式；
#           两侧值类型是否可比较由 ExpressionTranslator 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CompareExpr(Expr):
    """支持 Python 风格链式比较的关系表达式。"""

    operands: tuple[Expr, ...]
    operators: tuple[str, ...]

    # 功能：规范化比较操作数并验证运算符集合及链式比较元数。
    # 检查/语法关系：保留比较链顺序，不把它提前拆成 BooleanExpr。
    def __init__(
        self,
        operands: Iterable["ExprLike"],
        operators: Iterable[str],
    ):
        """要求 ``n`` 个关系运算符恰好连接 ``n+1`` 个操作数。"""
        values = tuple(ensure_expr(item) for item in operands)
        ops = tuple(operators)
        allowed = {"==", "!=", "<", "<=", ">", ">="}
        if not ops or any(op not in allowed for op in ops):
            raise ValueError(f"Unsupported comparison operators: {ops!r}")
        if len(values) != len(ops) + 1:
            raise ValueError("Comparison operands/operators have inconsistent arity")
        object.__setattr__(self, "operands", values)
        object.__setattr__(self, "operators", ops)

    # 功能：合并比较链中每个表达式引用的自由变量。
    # 检查/语法关系：关系运算生成 Bool，但不会绑定任何操作数变量。
    def get_vars(self) -> set[str]:
        """合并比较链中所有表达式的自由变量。"""
        return set().union(*(item.get_vars() for item in self.operands))

    # 功能：按操作数和关系符的交替顺序还原链式比较文本。
    # 检查/语法关系：显式括号确保整个比较式被视为单个 B。
    def __str__(self) -> str:
        """按链式比较顺序打印。"""
        parts = [str(self.operands[0])]
        for op, operand in zip(self.operators, self.operands[1:]):
            parts.extend((op, str(operand)))
        return "(" + " ".join(parts) + ")"


# --------------------------------------------------------------------------
# 语法对应：e ::= f(e, ..., e)，其中 f 必须是普通函数标识符。
# 构造方式：CallExpr("f", arguments)。
# 构造检查：拒绝属性/动态函数名，并递归规范化全部位置实参；
#           函数语义、返回类型和参数类型由 ExpressionTranslator 决定。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CallExpr(Expr):
    """简单命名函数调用，例如 ``sqrt(x)``。"""

    name: str
    arguments: tuple[Expr, ...]

    # 功能：验证普通函数名并把每个实参转换成项目表达式节点。
    # 检查/语法关系：函数名不作为状态变量；关键字实参在解析入口被拒绝。
    def __init__(self, name: str, arguments: Iterable["ExprLike"]):
        """函数名必须是普通标识符，不允许属性或动态调用。"""
        if not is_hcsp_identifier(name):
            raise ValueError(f"Invalid function name: {name!r}")
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self,
            "arguments",
            tuple(ensure_expr(item) for item in arguments),
        )

    # 功能：只合并函数实参中的自由变量。
    # 检查/语法关系：f 是函数符号而非 Gamma 中的普通值变量。
    def get_vars(self) -> set[str]:
        """函数名不是变量，只收集实参中的自由变量。"""
        return set().union(*(item.get_vars() for item in self.arguments))

    # 功能：生成普通位置实参函数调用形式。
    # 检查/语法关系：名称与实参均已在构造阶段规范化。
    def __str__(self) -> str:
        """生成普通函数调用形式。"""
        return f"{self.name}(" + ", ".join(str(item) for item in self.arguments) + ")"


# 功能：声明无需字符串解析即可成为 Literal 的 Python 标量输入范围。
# 检查/语法关系：str 被排除在此别名外，因为字符串在便捷构造器中表示表达式源码。
ScalarLiteral: TypeAlias = bool | int | float | Decimal | Fraction

# 功能：声明所有表达式构造器可接受的便捷输入边界。
# 检查/语法关系：这些输入最终都必须经 ensure_expr 变成项目自己的 Expr。
ExprLike: TypeAlias = Expr | ScalarLiteral | str


# 功能：把 ExprLike 便捷值统一规范化为项目表达式 AST。
# 检查/语法关系：已有 Expr 原样保留，标量成为 Literal，字符串交给 parse_expr；
#                tuple/list 和其他对象立即拒绝。
def ensure_expr(value: ExprLike) -> Expr:
    """把 Python 构造器接受的便捷输入转换成严格表达式 AST。

    字符串始终按表达式源码解析；字符串和 Unit 字面量不属于受支持的值域。
    任何不属于声明输入集合的对象都会立即触发 ``TypeError``。
    """
    if isinstance(value, Expr):
        return value
    if isinstance(value, (bool, int, float, Decimal, Fraction)):
        return Literal(value)
    if isinstance(value, str):
        return parse_expr(value)
    raise TypeError(
        "Expression must be a project Expr, scalar literal, or string source; "
        f"got {type(value).__name__}"
    )


# 功能：把赋值和输入动作的标量左值统一规范化为 Variable。
# 检查/语法关系：只接受已有 Variable 或合法简单标识符；
#                tuple 解构、属性和下标左值不属于当前表达式/HCSP 语法。
def ensure_variable(value: str | Variable) -> Variable:
    """把赋值/输入左值规范为项目内标量变量节点。"""
    if isinstance(value, Variable):
        return value
    if is_hcsp_identifier(value):
        return Variable(value)
    raise TypeError(f"Expected a scalar variable name, got {value!r}")


# 功能：在 Python 建树之前验证 NAME 并把 HCSP 的 ^ token 规范成真正的 **。
# 检查/语法关系：必须在 Python 执行 Unicode 名称规范化、并按异或优先级解释 ^
#                之前完成；字符串和注释中的同名字符不会被修改。
def _normalize_expression_tokens(text: str) -> str:
    """验证源码 NAME 为 ASCII IDENT，并把 ``^`` token 改写为 ``**``。"""

    try:
        tokens = list(
            python_tokenize.generate_tokens(io.StringIO(text).readline)
        )
    except (IndentationError, python_tokenize.TokenError) as exc:
        raise ValueError(f"Cannot tokenize expression {text!r}: {exc}") from exc

    for token in tokens:
        if (
            token.type == python_tokenize.NAME
            and not is_hcsp_identifier(token.string)
        ):
            raise ValueError(
                "Expression identifiers must match "
                f"[A-Za-z_][A-Za-z0-9_]*: {token.string!r}"
            )

    # 只向 untokenize 传递 token 类型和文本，避免把单字符 ^ 改成双字符 ** 后，
    # 原 TokenInfo 的结束坐标与新文本长度不一致。
    normalized = (
        (
            token.type,
            "**"
            if token.type == python_tokenize.OP and token.string == "^"
            else token.string,
        )
        for token in tokens
    )
    return python_tokenize.untokenize(normalized)


# 功能：把用户友好的表达式字符串解析成严格的项目 Expr 树。
# 检查/语法关系：先规范化 true/false、&&、||、!、<->、^ 等 HCSP 记号，
#                再借助 Python parser 完成词法分析，最终由 _from_python_ast 白名单转换。
def parse_expr(text: str) -> Expr:
    """解析受支持的字符串表达式子集。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Expression source must be a non-empty string")

    # 接受常见 HCSP 布尔记号，再交给 Python AST 完成可靠的词法/语法解析。
    normalized = re.sub(r"\btrue\b", "True", text, flags=re.IGNORECASE)
    normalized = re.sub(r"\bfalse\b", "False", normalized, flags=re.IGNORECASE)
    normalized = normalized.replace("&&", " and ").replace("||", " or ")
    normalized = re.sub(r"!(?!=)", " not ", normalized)
    normalized = normalized.replace("<->", " == ")
    normalized = _normalize_expression_tokens(normalized)
    try:
        node = ast.parse(normalized.strip(), mode="eval").body
    except SyntaxError as exc:
        raise ValueError(f"Cannot parse expression {text!r}: {exc.msg}") from exc
    return _from_python_ast(node)


# 功能：递归地把 Python AST 白名单节点翻译为项目表达式节点。
# 检查/语法关系：逐类处理常量、变量、一元/二元运算、布尔连接、
#                比较和简单调用；任何未显式列出的 Python 语法都会报错。
def _from_python_ast(node: ast.AST) -> Expr:
    """递归把 Python AST 的受支持子集转换成项目表达式节点。"""
    if isinstance(node, ast.Constant):
        return Literal(node.value)
    if isinstance(node, ast.Name):
        if node.id == "True":
            return Literal(True)
        if node.id == "False":
            return Literal(False)
        return Variable(node.id)
    if isinstance(node, ast.UnaryOp):
        operators = {
            ast.Not: "not",
            ast.UAdd: "+",
            ast.USub: "-",
        }
        op = operators.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported unary syntax: {ast.dump(node)}")
        return UnaryExpr(op, _from_python_ast(node.operand))
    if isinstance(node, ast.BinOp):
        operators = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.Div: "/",
            ast.Mod: "%",
            ast.Pow: "**",
        }
        op = operators.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported binary syntax: {ast.dump(node)}")
        return BinaryExpr(
            op,
            _from_python_ast(node.left),
            _from_python_ast(node.right),
        )
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            op = "and"
        elif isinstance(node.op, ast.Or):
            op = "or"
        else:
            raise ValueError(f"Unsupported Boolean syntax: {ast.dump(node)}")
        return BooleanExpr(op, (_from_python_ast(item) for item in node.values))
    if isinstance(node, ast.Compare):
        operators = {
            ast.Eq: "==",
            ast.NotEq: "!=",
            ast.Lt: "<",
            ast.LtE: "<=",
            ast.Gt: ">",
            ast.GtE: ">=",
        }
        ops: list[str] = []
        for item in node.ops:
            op = operators.get(type(item))
            if op is None:
                raise ValueError(f"Unsupported comparison: {ast.dump(item)}")
            ops.append(op)
        return CompareExpr(
            [_from_python_ast(node.left)]
            + [_from_python_ast(item) for item in node.comparators],
            ops,
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.keywords:
            raise ValueError("Keyword arguments are not supported in expressions")
        return CallExpr(
            node.func.id,
            (_from_python_ast(item) for item in node.args),
        )
    raise ValueError(f"Unsupported expression syntax: {ast.dump(node)}")
