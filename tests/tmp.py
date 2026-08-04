"""手动试验 HCSP 进程到行为类型的转换结果。

本文件不是自动化单元测试，因此文件名故意不以 ``test_`` 开头。用户只需修改
``build_case()`` 中的硬编码进程和环境，然后在项目根目录运行：

    python -B tests/tmp.py

脚本会依次显示 Process AST、总体判定、可读 Type、Type AST、规则原始公式、
证明器实际输入、判定证据、遗留义务和诊断。如果进程在 AST 构造阶段违反
Assumption 2.1/2.2，异常也会直接显示出来。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

# 支持直接执行 ``python tests/tmp.py``。直接执行时 Python 默认只把 tests/
# 放入模块搜索路径，因此这里显式加入项目根目录，以便导入 hcsp_typechecker。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hcsp_typechecker import (  # noqa: E402  (项目根目录在上面加入搜索路径)
    BasicType,
    ChannelType,
    Configuration,
    InputChannel,
    OutputChannel,
    Sequence,
    check_hcsp,
)


# ============================================================================
#                              手动修改区域
# ============================================================================

def build_case() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    Any,
    str,
    Callable[[], Any],
]:
    """返回环境、源程序文本和延迟执行的 Process AST 构造函数。

    修改下面的环境、源文本和构造函数即可测试其他例子。当前案例是
    ``ch!x; ch?x``：先从
    ``ch`` 发送当前 ``x``，随后再从同一通道接收一个值并绑定为 ``x``。

    Process 使用延迟构造，使 ``main()`` 能在 Assumption 2.1/2.2 报错之前
    先打印完整输入。修改案例时，应同步修改 ``source_text`` 和
    ``build_process()``。
    """

    # 第一个输出需要读取 x，因此必须在 Gamma 和初始状态中声明它。注意：
    # Gamma 声明不会改变 process 层的自由/绑定变量集合；后面的 ch?x 仍会
    # 按 Section 2.1/Assumption 2.1 把 x 记为绑定变量。
    gamma = {
        "x": BasicType.REAL,
    }
    theta = {
        # 输入和输出使用同一个一槽 Real 通道；refinement=true，不额外限制值。
        "ch": ChannelType(BasicType.REAL),
    }

    initial_state = {
        "x": 0,
    }
    path_condition = "x == 0"

    # 论文记法概要：
    #   ch!x; ch?x
    #
    source_text = "ch!x; ch?x"

    # 按当前项目保留的 Assumption 2.1：第一个 ch!x 自由使用 x，后一个 ch?x
    # 又把 x 作为输入绑定变量，因此整个进程同时具有 x in fv(P) 和 x in bv(P)。
    # 该交集非空，Sequence 构造时应直接报错，而不会生成行为类型。
    def build_process() -> Any:
        """在输入信息打印完成后构造当前手写 Process AST。"""

        return Sequence.of(
            OutputChannel("ch", "x"),
            InputChannel("ch", "x"),
        )

    return (
        gamma,
        theta,
        initial_state,
        path_condition,
        source_text,
        build_process,
    )


# ============================================================================
#                            以下通常无需修改
# ============================================================================
def main() -> int:
    """构造手写案例、调用公共检查入口并完整打印审计结果。"""

    # 详细报告可能包含论文/dL 常用的 Unicode 符号（例如 ¬、∧、≤）。Windows
    # 终端继承的旧式 GBK 编码无法表示其中部分字符，因此在手动入口显式使用
    # UTF-8；errors="backslashreplace" 保证极端终端环境下也不会因打印而丢报告。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    try:
        (
            gamma,
            theta,
            initial_state,
            path_condition,
            source_text,
            process_builder,
        ) = build_case()
    except Exception as exc:  # 手动脚本需要把构造期拒绝直接展示给用户。
        print("=== 手动案例定义失败 ===")
        print(f"{type(exc).__name__}: {exc}")
        return 1

    print("=== 输入 ===")
    print(f"HCSP source   : {source_text}")
    print(f"Gamma         : {gamma!r}")
    print(f"Theta         : {theta!r}")
    print(f"Initial state : {initial_state!r}")
    print(f"Path condition: {path_condition!r}")

    try:
        process = process_builder()
    except Exception as exc:
        print("Process AST   : <构造失败>")
        print("\n=== Process AST 构造失败 ===")
        print(f"{type(exc).__name__}: {exc}")
        return 1

    print(f"Process AST   : {process!r}")

    try:
        report = check_hcsp(
            gamma=gamma,
            theta=theta,
            configurations=[Configuration(initial_state, process)],
            path_condition=path_condition,
        )
    except Exception as exc:
        print("\n=== 类型检查调用失败 ===")
        print(f"{type(exc).__name__}: {exc}")
        return 1

    # CheckReport 统一负责详细展示，避免每个调用方各自遗漏规则轨迹、证明义务
    # 或 unknown/false 的解释。结构化字段仍然可以用于程序化审计。
    print()
    print(report.format_detailed())

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
