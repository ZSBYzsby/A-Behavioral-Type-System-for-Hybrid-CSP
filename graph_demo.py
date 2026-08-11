r"""用多个并行 Type AST 演示 Table 3 状态迁移图构造器。

本脚本刻意从 Type AST 开始，而不先解析 HCSP 或调用 TypeConstructor。这样用户
可以直接比较：

1. Python 中手工构造的原始 Type AST；
2. 图接口打印的规范化 Type 状态；
3. Table 3 产生的全部 ``tau``、通信和最大共同时间迁移；
4. 每条边附带的规则及分量/分支证据。

三个例子分别覆盖：多个相同通信伙伴的非确定性配对、递归协议与 watchdog 的
并发竞争、内部选择与不同 deadline 的组合。运行方式：

    python -B graph_demo.py

``GRAPH_OUTPUT_MODE="full"`` 会打印完整图；改成 ``"result"`` 时只打印图规模
和初始规范 Type。这里导入具体 Type AST 节点是为了演示内部数据结构；普通用户
取得 Type AST 后只需调用包根的 ``build_type_transition_graph``。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import sys

from hcsp_typechecker import TypeAST, build_type_transition_graph
from hcsp_typechecker.data_structures.type_ast import (
    EmptyType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    NoInterruptType,
    OutputType,
    ParallelType,
    TypeVar,
    format_type_source,
    make_external_choice,
)


# 可设为 "result" 或 "full"；只改变图的显示详细程度。
GRAPH_OUTPUT_MODE = "full"


@dataclass(frozen=True, slots=True)
class GraphExample:
    """一份可直接交给图构造器的命名 Type AST 示例。"""

    title: str
    purpose: str
    type_ast: TypeAST


def _racing_clients_example() -> GraphExample:
    """构造一个递归服务器与两个同构客户端竞争同步的并行类型。"""

    server = MuType(
        "server_loop",
        InfiniteDelayType(
            InputType("request", TypeVar("server_loop"))
        ),
    )
    client = InfiniteDelayType(OutputType("request", EmptyType()))
    return GraphExample(
        "1. 递归服务器与两个竞争客户端",
        (
            "服务器可与任意客户端在 request 上同步；两个客户端结构相同，"
            "所以两种配对到达同一图边，但边中必须保留两份推导证据。"
        ),
        ParallelType((server, client, client)),
    )


def _watchdog_protocol_example() -> GraphExample:
    """构造请求/应答协议与可抢先停止服务器的 watchdog 并行类型。"""

    server = MuType(
        "server_loop",
        InfiniteDelayType(
            make_external_choice(
                (
                    InputType(
                        "request",
                        FiniteDelayType(
                            2,
                            NoInterruptType(),
                            InfiniteDelayType(
                                OutputType(
                                    "reply",
                                    TypeVar("server_loop"),
                                )
                            ),
                        ),
                    ),
                    InputType("stop", EmptyType()),
                )
            )
        ),
    )
    client = InfiniteDelayType(
        OutputType(
            "request",
            InfiniteDelayType(InputType("reply", EmptyType())),
        )
    )
    watchdog = FiniteDelayType(
        1,
        OutputType("stop", EmptyType()),
        EmptyType(),
    )
    return GraphExample(
        "2. 请求/应答服务器、客户端与 watchdog",
        (
            "初态既可执行 request 同步，也可执行 stop 同步；request 分支随后"
            "经历 watchdog 的 1 单位 deadline、服务器的第 2 单位 deadline、"
            "reply 同步并回到递归服务器。"
        ),
        ParallelType((server, client, watchdog)),
    )


def _choice_and_deadlines_example() -> GraphExample:
    """构造带三元内部选择、不同 deadline 和空并行单位元的类型。"""

    worker = InternalChoiceType(
        (
            FiniteDelayType(
                1,
                OutputType("alarm", EmptyType()),
                InfiniteDelayType(OutputType("done", EmptyType())),
            ),
            FiniteDelayType(
                3,
                OutputType("status", EmptyType()),
                EmptyType(),
            ),
            InfiniteDelayType(OutputType("idle", EmptyType())),
        )
    )
    observer = InfiniteDelayType(InputType("done", EmptyType()))
    return GraphExample(
        "3. 内部选择、错开 deadline 与 Empty 并行单位元",
        (
            "worker 首先非确定性选择三种行为；其中一支在 1 单位后与 observer "
            "完成 done 同步，另一支等待 3 单位，最后一支永久等待。显式 Empty "
            "分量应在规范化时消失且不阻塞其他分量时间推进。"
        ),
        ParallelType((worker, observer, EmptyType())),
    )


def build_examples() -> tuple[GraphExample, ...]:
    """返回按演示顺序排列、彼此独立的全部并行 Type AST 示例。"""

    return (
        _racing_clients_example(),
        _watchdog_protocol_example(),
        _choice_and_deadlines_example(),
    )


def _run_example(example: GraphExample) -> bool:
    """打印一个原始 Type AST 及其完整可达图，并返回图是否完整。"""

    print("\n" + "=" * 76)
    print(example.title)
    print(example.purpose)
    print("-" * 76)
    print("输入 Type AST 的用户语法：")
    print(format_type_source(example.type_ast))
    print("\nTable 3 状态迁移图：")
    graph = build_type_transition_graph(
        example.type_ast,
        output=GRAPH_OUTPUT_MODE,
    )
    print(
        "\n图摘要："
        f"{len(graph.states)} 个规范状态，"
        f"{len(graph.transitions)} 条迁移，"
        f"complete={str(graph.complete).lower()}。"
    )
    if not graph.complete:
        print("截断原因：" + str(graph.truncation_reason))
    return graph.complete


def main() -> int:
    """依次生成三个并行 Type AST 的完整 Table 3 状态迁移图。"""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if GRAPH_OUTPUT_MODE not in {"result", "full"}:
        print('GRAPH_OUTPUT_MODE 只能设为 "result" 或 "full"。')
        return 2

    print("并行 Type AST -> 规范化 Type -> Table 3 状态图演示")
    print(f"图输出模式：{GRAPH_OUTPUT_MODE!r}")
    complete = True
    for example in build_examples():
        complete = _run_example(example) and complete

    print("\n" + "=" * 76)
    print("演示结束：全部状态图均已完整闭包。" if complete else "演示结束：存在被截断的图。")
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
