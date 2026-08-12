r"""构造改良版 Section 5 Type，并继续生成其 Table 3 状态迁移图。

本文件生成一份符合项目用户输入语法的完整 source，并通过
``construct_hcsp_type(source) -> TypeAST`` 一次完成解析、类型构造和必要公式证明。
只有 Constructor 正常返回可信 Type AST 后，脚本才调用
``build_type_transition_graph(type_ast) -> TypeTransitionGraph``：第三接口先规范化
Type、建立等递归循环项图，再穷尽项目 Table 3 的全部可达迁移。Process AST、
规范 Type AST 和循环项图仍是内部对象，不需要由本脚本手工构造。
图构造完成后，脚本再调用 ``analyze_type_lock_freedom(graph)``，用第四接口检查
全部可达状态是否同时满足死锁自由和活锁自由，并在失败时给出有限反例路径。

``end``、``vmax``、``amin``、``amax`` 是 source 中声明的共享只读 Real
参数，不属于任一并行分量的状态 Gamma，也不会被替换成具体数值。统一约束为：

    end >= 0 and vmax >= 0 and amin < 0 and amax >= 0

``d`` 不是共享符号参数，而是每次运行时给定的具体正有理数 ODE 批注；它会
同时用于 Vehicle 的 delay、Controller 显式空 flow ODE 和 ``phi_a`` 的周期预测。默认值
为 1，也可以通过命令行修改：

    python -B case_study/new_case.py
    python -B case_study/new_case.py --d 3/2

本例使用加强后的 ``phi_a``：除了周期终点的 ``phi_p``、``phi_v``，还检查区间
内部可能出现的速度转向点。Vehicle 收到新加速度后检查该性质，不安全时回退到
共享参数 ``amin``。Constructor 默认 ``result`` 模式只显示最终 Type 摘要；改成
``"full"`` 可查看 source、环境、FOL/dL 公式、证明结果和规则轨迹。状态图默认也
使用 ``result``，显示图规模和初始规范 Type；把 ``GRAPH_OUTPUT_MODE`` 改为
``"full"`` 可查看全部状态、迁移标签和 Table 3 推导证据。
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import os
from pathlib import Path
import sys
from typing import Sequence

# 该脚本位于项目子目录中。直接执行文件时 Python 只把 ``case_study`` 加入
# 模块搜索路径，因此在导入公共包之前显式加入源码仓库根目录。这里不依赖安装包。
CASE_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = CASE_DIRECTORY.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPTypeTransitionGraphError,
    HCSPTypeLockAnalysisError,
    HCSPUntrustedTypeConstructionError,
    build_type_transition_graph,
    analyze_type_lock_freedom,
    construct_hcsp_type,
)


PARAMETER_ASSUMPTIONS = (
    "end >= 0 and vmax >= 0 and amin < 0 and amax >= 0"
)
ARTIFACTS_DIRECTORY = (
    CASE_DIRECTORY / "tmp" / "general-case-keymaerax-artifacts"
)
KEYMAERAX_HOME_DIRECTORY = (
    CASE_DIRECTORY / "tmp" / "general-case-keymaerax-home"
)

# 设为 "full" 可查看每条公式、证明器说明和完整规则轨迹。
OUTPUT_MODE = "result"

# 设为 "full" 可查看所有状态、边标签以及合并后的 Table 3 推导证据。
GRAPH_OUTPUT_MODE = "result"

# 设为 "full" 可查看死锁可达前缀、无限等待边或活锁静默环及规则证据。
LOCK_ANALYSIS_OUTPUT_MODE = "result"


def _number_text(value: Fraction) -> str:
    """把具体有理数批注写成用户输入语法可精确解析的文本。"""

    if value.denominator == 1:
        return str(value.numerator)
    return f"({value.numerator}/{value.denominator})"


def position_safety(position: str) -> str:
    """返回一般参数下的位置安全性质 ``phi_p(position)``。"""

    return f"({position}) <= end"


def velocity_safety(position: str, velocity: str) -> str:
    r"""返回一般参数下、无除法形式的三段式 ``phi_v``。

    原定义中的 ``sb=vmax^2/(-2*amin)`` 在 ``amin<0`` 下等价改写为比较
    ``(-2*amin)*(end-p)`` 与 ``vmax^2``，避免在证明义务中引入除法。
    """

    remaining = f"(end - ({position}))"
    braking_capacity = f"((-2 * amin) * {remaining})"
    maximum_speed_square = "(vmax * vmax)"
    return (
        f"((({position}) >= end and ({velocity}) <= 0) or "
        f"({braking_capacity} >= {maximum_speed_square} and "
        f"({velocity}) <= vmax) or "
        f"(0 < {remaining} and "
        f"{braking_capacity} < {maximum_speed_square} and "
        f"(({velocity}) <= 0 or "
        f"({velocity}) * ({velocity}) <= {braking_capacity})))"
    )


def acceleration_safety(
    position: str,
    velocity: str,
    acceleration: str,
    period: Fraction,
) -> str:
    r"""构造包含周期终点和区间内部转向点检查的 ``phi_a``。"""

    duration = _number_text(period)
    predicted_position = (
        f"(({position}) + ({velocity}) * {duration} + "
        f"({acceleration}) * {duration} ** 2 / 2)"
    )
    predicted_velocity = f"(({velocity}) + ({acceleration}) * {duration})"
    turning_point_safe = (
        f"(({acceleration}) >= 0 or "
        f"({velocity}) <= 0 or "
        f"({predicted_velocity}) > 0 or "
        f"({velocity}) * ({velocity}) <= "
        f"-2 * ({acceleration}) * (end - ({position})))"
    )
    return (
        f"(amin <= ({acceleration}) and "
        f"({acceleration}) <= amax and "
        f"{position_safety(predicted_position)} and "
        f"{velocity_safety(predicted_position, predicted_velocity)} and "
        f"{turning_point_safe})"
    )


def build_source(period: Fraction) -> str:
    """生成与改良版案例一一对应的完整用户输入文本。"""

    phi_p = position_safety("p")
    phi_v = velocity_safety("p", "v")
    phi_a = acceleration_safety("p", "v", "a", period)
    ode_safety = f"({phi_p}) and ({phi_v})"
    loop_invariant = f"({ode_safety}) and ({phi_a})"
    received_acceleration_is_safe = acceleration_safety(
        "p", "v", "new_acc", period
    )
    maximum_acceleration_is_safe = acceleration_safety(
        "x", "y", "amax", period
    )
    zero_acceleration_is_safe = acceleration_safety(
        "x", "y", "0", period
    )
    duration = _number_text(period)

    # 双花括号只用于在 Python f-string 中产生用户 source 的单个花括号。
    return f"""
gamma(
    p: Real,
    v: Real,
    a: Real,
    vehicle_ode: continuous(p, v, a),
    command: Real
)

parameters(
    end: Real,
    vmax: Real,
    amin: Real,
    amax: Real
) where(
    {PARAMETER_ASSUMPTIONS}
)

theta(
    ch: channel(position: Real, velocity: Real),
    dh: channel(eta: Real) where(amin <= eta and eta <= amax),
    stop: channel(eta: Int) where(eta == 0)
)

process {{
    {{
        p := 0;
        v := 0;
        a := 0;
        mu X invariant({loop_invariant}) {{
            ode(
                flow(
                    dot p = v,
                    dot v = a,
                    dot a = 0
                ),
                domain(true),
                safety({ode_safety}),
                delay({duration}),
                interrupt(
                    on ch!(p, v) {{
                        ode(
                            flow(),
                            domain(true),
                            safety({ode_safety}),
                            delay(inf),
                            interrupt(
                                on dh?(new_acc) {{
                                    if ({received_acceleration_is_safe}) {{
                                        a := new_acc
                                    }} else {{
                                        a := amin
                                    }};
                                    call X
                                }},
                                on stop?(stop_signal) {{
                                    skip
                                }}
                            )
                            );
                            skip
                        }}
                )
            );
            skip
        }}
    }},
    {{
        mu Y invariant(true) {{
            ch?(x, y);
            if (y >= 0) {{
                if ({maximum_acceleration_is_safe}) {{
                    command := amax
                }} else {{
                    if ({zero_acceleration_is_safe}) {{
                        command := 0
                    }} else {{
                        command := amin
                    }}
                }};
                dh!(command);
                ode(flow(), domain(t < {duration}), delay({duration}));
                call Y
            }} else {{
                stop!(0)
            }}
        }}
    }}
}}
""".strip()


def _positive_fraction(value: str) -> Fraction:
    """解析 ODE 批注所需的具体正有理数 ``d``。"""

    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise argparse.ArgumentTypeError(
            f"invalid rational delay: {value!r}"
        ) from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("d must be a positive rational number")
    return result


def parse_period(argv: Sequence[str] | None = None) -> Fraction:
    """读取具体批注 ``d``；四个物理参数始终保持符号化。"""

    parser = argparse.ArgumentParser(
        description=(
            "Derive a Type AST for all admissible end/vmax/amin/amax; "
            "only the annotation delay d is concrete."
        ),
    )
    parser.add_argument("--d", type=_positive_fraction, default=Fraction(1, 1))
    return parser.parse_args(argv).d


def main(argv: Sequence[str] | None = None) -> int:
    """依次构造可信 Type、完整状态图，并用第四接口检查锁自由性。"""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    period = parse_period(argv)
    source = build_source(period)

    # 公共接口从这些环境变量读取证明器目录与产物保留策略。设置只影响
    # 当前脚本进程及其 KeYmaera X 子进程。
    os.environ["KEYMAERAX_HOME"] = str(KEYMAERAX_HOME_DIRECTORY)
    os.environ["KEYMAERAX_KEEP_ARTIFACTS"] = "true"
    os.environ["KEYMAERAX_ARTIFACTS"] = str(ARTIFACTS_DIRECTORY)

    try:
        type_ast = construct_hcsp_type(
            source,
            source_name=(
                f"case_study/new_case.py --d {_number_text(period)}"
            ),
            output=OUTPUT_MODE,
            keymaerax_timeout_seconds=180.0,
        )
    except HCSPInputError as error:
        print(
            "案例终止：输入无效 "
            f"[{error.kind}]，位置 {error.source_name}:{error.line}:{error.column}。"
        )
        return 1
    except HCSPUntrustedTypeConstructionError as error:
        print(
            "案例未通过：Type 已完整构造，但仍有未决证明义务 "
            f"[{error.kind.value}]，规则 {error.rule or '-'}，"
            f"位置 {error.location or '-'}。"
        )
        return 1
    except HCSPTypeConstructionError as error:
        print(
            "案例未通过：TypeConstructor 失败 "
            f"[{error.kind.value}/{error.phase}]，规则 {error.rule or '-'}，"
            f"位置 {error.location or '-'}。"
        )
        return 1
    print("案例第一阶段通过：Type 构造完成，全部证明义务均已验证。")

    try:
        graph = build_type_transition_graph(
            type_ast,
            output=GRAPH_OUTPUT_MODE,
        )
    except HCSPTypeTransitionGraphError as error:
        print(
            "案例第二阶段失败：无法构造完整状态迁移图 "
            f"[{error.kind.value}/{error.phase}]。"
        )
        return 1

    print(
        "案例第二阶段通过：已从可信 Type AST 构造完整状态迁移图；"
        f"状态 {len(graph.states)} 个，转移 {len(graph.transitions)} 条。"
    )
    try:
        report = analyze_type_lock_freedom(
            graph,
            output=LOCK_ANALYSIS_OUTPUT_MODE,
        )
    except HCSPTypeLockAnalysisError as error:
        print(
            "案例第三阶段失败：无法分析完整状态迁移图 "
            f"[{error.kind.value}/{error.phase}]。"
        )
        return 1
    if not report.lock_free:
        print(
            "案例第三阶段未通过：状态图存在锁反例；"
            f"deadlock_free={report.deadlock_free}, "
            f"livelock_free={report.livelock_free}。"
        )
        return 1
    print("案例第三阶段通过：全部可达状态同时满足死锁自由和活锁自由。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
