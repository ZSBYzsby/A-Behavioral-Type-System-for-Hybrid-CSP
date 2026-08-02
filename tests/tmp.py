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
from typing import Any

# 支持直接执行 ``python tests/tmp.py``。直接执行时 Python 默认只把 tests/
# 放入模块搜索路径，因此这里显式加入项目根目录，以便导入 hcsp_typechecker。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hcsp_typechecker import (  # noqa: E402  (项目根目录在上面加入搜索路径)
    BasicType,
    ChannelType,
    Configuration,
    KeYmaeraXConfig,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Sequence,
    check_hcsp,
)


# ============================================================================
#                              手动修改区域
# ============================================================================

def build_case() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any, Any]:
    """返回 Gamma、Theta、初始状态、路径条件和待检查的 HCSP 进程。

    修改下面五个变量即可测试其他例子。当前案例是 ``x'=1`` 的简单 ODE，
    会同时产生 safety 和精确 boundary 两条 dL 证明义务，并由项目默认配置的
    KeYmaera X 后端尝试证明。
    """

    # x 是唯一的用户状态变量。ODE 自动拥有隐藏局部时钟 t，因此 Gamma、初始
    # 状态和方程列表中都不需要额外声明 t。
    gamma = {
        "x": BasicType.REAL,
    }
    theta = {
        # ODE 在 x=1 的边界自然结束；输出 refinement 用来验证后继确实可以
        # 利用 ``not B and safety`` 推出 x=1。
        "done": ChannelType(BasicType.REAL, "eta == 1"),
    }

    initial_state = {
        "x": 0,
    }
    path_condition = "x == 0"

    # 论文记法概要：
    #   <dot(x)=1 & x<1>_{safety: x<=1, delay: 1};
    #   done!x
    #
    # 重点观察最终报告中的三条公式：
    # 1. T-ODE-safety：在 0<=t<=1 内保持 x<=1；
    # 2. T-ODE-boundary：t<1 时 x<1，t=1 时 not(x<1)；
    # 3. T-Out：在自然结束路径 not B and safety 下证明发送值 x 满足 eta=1。
    # 预期行为类型为 ``delay(1).done!.0``。
    process = Sequence.of(
        ODE(
            [("x", 1)],
            "x < 1",
            annotation=ODEAnnotation(
                safety="x <= 1",
                delay=1,
            ),
        ),
        OutputChannel("done", "x"),
    )

    return gamma, theta, initial_state, path_condition, process


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
        gamma, theta, initial_state, path_condition, process = build_case()
    except Exception as exc:  # 手动脚本需要把构造期拒绝直接展示给用户。
        print("=== Process AST 构造失败 ===")
        print(f"{type(exc).__name__}: {exc}")
        return 1

    print("=== 输入 ===")
    print(f"Process AST   : {process!r}")
    print(f"Gamma         : {gamma!r}")
    print(f"Theta         : {theta!r}")
    print(f"Initial state : {initial_state!r}")
    print(f"Path condition: {path_condition!r}")

    try:
        report = check_hcsp(
            gamma=gamma,
            theta=theta,
            configurations=[Configuration(initial_state, process)],
            path_condition=path_condition,
            # 公开版本不写死开发者电脑路径。配置依次来自 KEYMAERAX_JAR、
            # KEYMAERAX_JAVA、KEYMAERAX_HOME、KEYMAERAX_TIMEOUT 等环境变量；
            # 源码 checkout 也可把未纳入版本控制的 jar 放在 tools/ 下。
            # 未配置证明器时报告会保守显示 unknown，而不会在这里抛出异常。
            keymaerax_config=KeYmaeraXConfig.from_environment(),
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
