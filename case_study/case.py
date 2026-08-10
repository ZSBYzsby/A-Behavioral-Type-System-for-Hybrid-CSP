r"""通过新版公共接口复现论文 Section 5 原始 case study 的 ``unknown``。

本例故意保留论文原始的加速度条件：

    phi_a(p, v, a) :=
        amin <= a <= amax
        and phi_v(p + v*d + a*d^2/2, v + a*d)

它没有加入 ``new_case.py`` 使用的周期终点位置检查和区间内转向点检查，
因此用于复现相应 dL 前提不能被证明的情况。四个物理量 ``end``、``vmax``、
``amin``、``amax`` 是 source 中声明的共享符号参数；只有 ODE 批注 ``d``
由命令行给出具体正有理数：

    python -B case_study/case.py
    python -B case_study/case.py --d 3/2

脚本只使用项目承诺兼容的单一公共接口。接口负责一次性打印 source、规则轨迹、
FOL/dL 义务、完整候选类型及其可信性，脚本自身只补充案例结论。
对本问题复现脚本而言，预期结果是：证明义务得到 ``unknown`` 后继续完成规则
构造，并通过 ``HCSPUntrustedTypeConstructionError.untrusted_type`` 给出完整但
不可信的候选 Type AST。解析错误、确定的 ``false``、未能完成类型结构，或者意外
得到可信 Type AST，退出码均为 1。
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import os
from pathlib import Path
import sys
from typing import Sequence


# 该文件位于项目子目录中。把源码仓库根目录加入模块搜索路径后，用户可直接
# 运行上面给出的命令，而不必先把项目安装为 Python 包或手工设置 PYTHONPATH。
_CASE_STUDY_DIRECTORY = Path(__file__).resolve().parent
_PROJECT_ROOT = _CASE_STUDY_DIRECTORY.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hcsp_typechecker import (  # noqa: E402 - 搜索路径必须先指向源码根目录
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    construct_hcsp_type,
)


PARAMETER_CONSTRAINT = (
    "end >= 0 and vmax >= 0 and amin < 0 and amax >= 0"
)
_KEYMAERAX_HOME = _CASE_STUDY_DIRECTORY / "tmp" / "paper-case-unknown-home"
_KEYMAERAX_ARTIFACTS = (
    _CASE_STUDY_DIRECTORY / "tmp" / "paper-case-unknown-artifacts"
)


def _number_text(value: Fraction) -> str:
    """把具体正有理数批注写成用户表达式语法可精确解析的文本。"""

    if value.denominator == 1:
        return str(value.numerator)
    return f"({value.numerator}/{value.denominator})"


def _position_safety(position: str) -> str:
    """生成论文的位置条件 ``phi_p(position)``。"""

    return f"({position}) <= end"


def _velocity_safety(position: str, velocity: str) -> str:
    r"""生成论文中无除法形式的三段式速度条件 ``phi_v``。

    ``sb=vmax^2/(-2*amin)`` 在参数约束 ``amin < 0`` 下等价改写为
    ``(-2*amin)*(end-p)`` 与 ``vmax^2`` 的比较，避免给 dL 公式引入与
    本案例无关的除法有定义性问题。
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


def _acceleration_safety(
    position: str,
    velocity: str,
    acceleration: str,
    period: Fraction,
) -> str:
    r"""生成论文原始的一步预测条件 ``phi_a``。

    这里有意不添加预测终点的 ``phi_p``，也不检查 ``0..d`` 内的速度
    转向点；这正是本脚本要保留和展示的原始案例特征。
    """

    duration = _number_text(period)
    predicted_position = (
        f"(({position}) + ({velocity}) * {duration} + "
        f"({acceleration}) * {duration} ** 2 / 2)"
    )
    predicted_velocity = (
        f"(({velocity}) + ({acceleration}) * {duration})"
    )
    return (
        f"(amin <= ({acceleration}) and "
        f"({acceleration}) <= amax and "
        f"{_velocity_safety(predicted_position, predicted_velocity)})"
    )


def _build_original_case_source(period: Fraction) -> str:
    """生成原始 case study 对应的一份完整、可复制的用户输入 source。"""

    phi_p = _position_safety("p")
    phi_v = _velocity_safety("p", "v")
    phi_a = _acceleration_safety("p", "v", "a", period)
    ode_safety = f"({phi_p}) and ({phi_v})"
    loop_invariant = f"({ode_safety}) and ({phi_a})"
    received_acceleration_is_safe = _acceleration_safety(
        "p",
        "v",
        "new_acc",
        period,
    )
    maximum_acceleration_is_safe = _acceleration_safety(
        "x",
        "y",
        "amax",
        period,
    )
    zero_acceleration_is_safe = _acceleration_safety(
        "x",
        "y",
        "0",
        period,
    )
    duration = _number_text(period)

    # 双花括号只负责转义 Python f-string。函数返回的 source 中仍是用户语法
    # 规定的单花括号，例如 ``process { {Vehicle}, {Controller} }``。
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
    {PARAMETER_CONSTRAINT}
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
                        )
                    }}
                )
            )
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
    """把 ``--d`` 解析为 ODE 批注所要求的具体正有理数。"""

    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise argparse.ArgumentTypeError(
            f"invalid rational delay: {value!r}"
        ) from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("d must be a positive rational number")
    return result


def _parse_period(argv: Sequence[str] | None = None) -> Fraction:
    """读取具体批注 ``d``；四个物理参数始终保持为 source 中的符号。"""

    parser = argparse.ArgumentParser(
        description=(
            "Reproduce the original Section 5 dL issue for all admissible "
            "end/vmax/amin/amax; only annotation d is concrete."
        ),
    )
    parser.add_argument("--d", type=_positive_fraction, default=Fraction(1, 1))
    return parser.parse_args(argv).d


def main(argv: Sequence[str] | None = None) -> int:
    """检查原始案例是否形成预期的 ``unknown`` 不可信候选类型。"""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    period = _parse_period(argv)
    source = _build_original_case_source(period)

    # 公共接口从环境变量读取证明器位置与产物策略。这里只选择本案例的可写
    # 工作目录，不接触内部 KeYmaeraXConfig 类型。
    os.environ["KEYMAERAX_HOME"] = str(_KEYMAERAX_HOME)
    os.environ["KEYMAERAX_KEEP_ARTIFACTS"] = "true"
    os.environ["KEYMAERAX_ARTIFACTS"] = str(_KEYMAERAX_ARTIFACTS)

    try:
        construct_hcsp_type(
            source,
            source_name=f"case_study/case.py (--d={period})",
            output="full",
            keymaerax_timeout_seconds=180.0,
        )
    except HCSPInputError:
        # full 模式已经输出带源码位置的解析诊断。
        return 1
    except HCSPUntrustedTypeConstructionError as error:
        print()
        print("=== 原始 case study 结论 ===")
        print(
            "已复现预期结果：unknown 义务没有中断类型构造；"
            "接口形成了完整但尚未验证的候选 Type AST。"
        )
        print("不可信候选 Type 已按上方的规范 Type 源码显示。")
        print("具体 dL 公式、未决原因和后续推导轨迹见上方完整日志。")
        return 0
    except HCSPTypeConstructionError as error:
        print()
        print("=== 原始 case study 结论 ===")
        print(
            f"未复现预期结果：构造过程得到 {error.verdict!r}，"
            "但没有形成原案例预期的完整不可信候选类型。"
        )
        return 1

    print()
    print("=== 原始 case study 结论 ===")
    print("未复现预期结果：本次运行意外生成了可信 Type AST。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
