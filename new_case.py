r"""对一般物理参数推导 Section 5 Vehicle 的行为 Type AST。

``end``、``vmax``、``amin``、``amax`` 在本文件中属于独立的共享参数环境，
不属于任一并行分量的状态 Gamma，也没有被替换成任何具体数值。参数环境的
统一约束是：

    end >= 0 and vmax >= 0 and amin < 0 and amax >= 0

类型检查器会把该约束自动加入所有配置、递归体和 ODE 证明前件，生成的一阶
逻辑和 dL premise 对四个参数作全称有效性判断。``d`` 不属于上述符号参数；
它按照论文的 ODE 批注要求，在每次运行时
取一个具体的正有理数，默认值为 1：

    python -B new_case.py
    python -B new_case.py --d 3/2

本例同时推导 Vehicle 和 Controller 两个配置。二者拥有互不相交的状态 Gamma，
但读取同一个共享参数预赋值；Vehicle 在接收新加速度后自行检查 ``phi_a``，
不安全时回退到共享参数 ``amin``。
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Sequence

from hcsp_typechecker import (
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    EventChoice,
    If,
    InputChannel,
    KeYmaeraXConfig,
    Mu,
    ODE,
    ODEAnnotation,
    OutputChannel,
    ParameterEnvironment,
    Process,
    RecursionAnnotation,
    Sequence,
    Skip,
    Var,
    check_hcsp,
)


# 这些名字是证明中的自由 Real 参数，不是 Python 数值。
PARAMETER_NAMES = ("end", "vmax", "amin", "amax")
PARAMETER_ASSUMPTIONS = (
    "end >= 0 and vmax >= 0 and amin < 0 and amax >= 0"
)
ARTIFACTS_DIRECTORY = (
    Path(__file__).resolve().parent / "tmp" / "general-case-keymaerax-artifacts"
)
KEYMAERAX_HOME_DIRECTORY = (
    Path(__file__).resolve().parent / "tmp" / "general-case-keymaerax-home"
)


def _number_text(value: Fraction) -> str:
    """把批注使用的具体正有理数 d 写成精确表达式文本。"""

    if value.denominator == 1:
        return str(value.numerator)
    return f"({value.numerator}/{value.denominator})"


def position_safety(position: str) -> str:
    """返回一般参数下的 ``phi_p(position)``。"""

    return f"({position}) <= end"


def velocity_safety(position: str, velocity: str) -> str:
    r"""返回一般参数下、无除法形式的三段式 ``phi_v``。

    原定义中的 ``sb=vmax^2/(-2*amin)`` 在 ``amin<0`` 下等价改写为比较
    ``(-2*amin)*(end-p)`` 与 ``vmax^2``。这样 ``end``、``vmax`` 和
    ``amin`` 始终保持为符号参数，同时避免在证明义务中引入除法。
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
    r"""构造对一般物理参数成立的加强版 ``phi_a``。"""

    duration = _number_text(period)
    predicted_position = (
        f"(({position}) + ({velocity}) * {duration} + "
        f"({acceleration}) * {duration} ** 2 / 2)"
    )
    predicted_velocity = (
        f"(({velocity}) + ({acceleration}) * {duration})"
    )
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


def invariant_formulas(period: Fraction) -> tuple[str, str, str, str, str]:
    """返回一般参数公式；参数约束由共享参数环境自动提供。"""

    phi_p = position_safety("p")
    phi_v = velocity_safety("p", "v")
    phi_a = acceleration_safety("p", "v", "a", period)
    state_safety = f"({phi_p}) and ({phi_v})"

    # H 不再重复写入每个不变量。ParameterEnvironment 会把 H 作为不可变的
    # 共享背景条件加入 T-sigma、递归和 dL 前件。
    ode_safety = state_safety
    loop_invariant = f"({state_safety}) and ({phi_a})"
    return phi_p, phi_v, phi_a, ode_safety, loop_invariant


def build_vehicle(period: Fraction) -> Process:
    """构造未实例化四个物理参数的 Vehicle HCSP AST。"""

    _, _, _, ode_safety, loop_invariant = invariant_formulas(period)
    received_acceleration_is_safe = acceleration_safety(
        "p",
        "v",
        "new_acc",
        period,
    )

    decision_wait = ODE(
        [],
        True,
        EventChoice.of(
            (
                InputChannel("dh", "new_acc"),
                Sequence.of(
                    If(
                        received_acceleration_is_safe,
                        Assign("a", "new_acc"),
                        Assign("a", "amin"),
                    ),
                    Var("X"),
                ),
            ),
            (InputChannel("stop", "stop_signal"), Skip()),
        ),
        annotation=ODEAnnotation(safety=ode_safety, delay=math.inf),
    )

    continuous_motion = ODE(
        [("p", "v"), ("v", "a"), ("a", 0)],
        True,
        EventChoice.of(
            (OutputChannel("ch", ("p", "v")), decision_wait),
        ),
        annotation=ODEAnnotation(
            safety=ode_safety,
            delay=period,
        ),
    )

    loop = Mu(
        "X",
        continuous_motion,
        annotation=RecursionAnnotation(loop_invariant),
    )
    return Sequence.of(
        Assign("p", 0),
        Assign("v", 0),
        Assign("a", 0),
        loop,
    )


def build_controller(period: Fraction) -> Process:
    """构造读取同一共享参数环境的 Controller HCSP AST。"""

    choose_acceleration = If(
        acceleration_safety("x", "y", "amax", period),
        Assign("command", "amax"),
        If(
            acceleration_safety("x", "y", "0", period),
            Assign("command", 0),
            Assign("command", "amin"),
        ),
    )
    body = Sequence.of(
        InputChannel("ch", ("x", "y")),
        If(
            "y >= 0",
            Sequence.of(
                choose_acceleration,
                OutputChannel("dh", "command"),
                ODE.wait(period),
                Var("Y"),
            ),
            OutputChannel("stop", 0),
        ),
    )
    return Mu("Y", body, annotation=RecursionAnnotation(True))


def build_typing_input(period: Fraction) -> tuple[
    dict[str, BasicType | ContinuousType],
    dict[str, ChannelType],
    tuple[Configuration, ...],
    ParameterEnvironment,
    tuple[Process, Process],
]:
    """建立共享参数、分离状态 Gamma 和两个并行配置。"""

    vehicle = build_vehicle(period)
    controller = build_controller(period)
    vehicle_gamma: dict[str, BasicType | ContinuousType] = {
        "p": BasicType.REAL,
        "v": BasicType.REAL,
        "a": BasicType.REAL,
        "vehicle_ode": ContinuousType(("p", "v", "a")),
    }
    controller_gamma: dict[str, BasicType | ContinuousType] = {
        "command": BasicType.REAL,
    }
    gamma = {**vehicle_gamma, **controller_gamma}
    parameters = ParameterEnvironment(
        {name: BasicType.REAL for name in PARAMETER_NAMES},
        PARAMETER_ASSUMPTIONS,
    )
    theta = {
        "ch": ChannelType(
            (BasicType.REAL, BasicType.REAL),
            binders=("position", "velocity"),
        ),
        "dh": ChannelType(
            BasicType.REAL,
            refinement="amin <= eta and eta <= amax",
        ),
        "stop": ChannelType(BasicType.INT, refinement="eta == 0"),
    }
    configurations = (
        Configuration({}, vehicle, gamma=vehicle_gamma, name="Vehicle"),
        Configuration({}, controller, gamma=controller_gamma, name="Controller"),
    )
    return gamma, theta, configurations, parameters, (vehicle, controller)


def _positive_fraction(value: str) -> Fraction:
    """解析 ODE 批注需要的具体正有理数 d。"""

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
    """只读取具体批注 d；四个物理参数没有数值入口。"""

    parser = argparse.ArgumentParser(
        description=(
            "Derive a Type AST for all admissible end/vmax/amin/amax; "
            "only the annotation delay d is concrete."
        ),
    )
    parser.add_argument("--d", type=_positive_fraction, default=Fraction(1, 1))
    return parser.parse_args(argv).d


def main(argv: Sequence[str] | None = None) -> int:
    """执行一般参数 HCSP AST 到 Type AST 的完整推导。"""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    period = parse_period(argv)
    phi_p, phi_v, phi_a, _, loop_invariant = invariant_formulas(period)
    gamma, theta, configurations, parameters, processes = build_typing_input(period)

    print("=== General-parameter Section 5 case ===")
    print("symbolic parameters : end, vmax, amin, amax : Real")
    print(f"parameter premise   : {PARAMETER_ASSUMPTIONS}")
    print(f"concrete annotation d: {period}")
    print(f"phi_p               : {phi_p}")
    print(f"phi_v               : {phi_v}")
    print(f"phi_a               : {phi_a}")
    print(f"loop invariant      : {loop_invariant}")

    print("\n=== HCSP AST ===")
    print(f"Vehicle   : {processes[0]!r}")
    print(f"Controller: {processes[1]!r}")

    base_config = KeYmaeraXConfig.from_environment()
    # KeYmaera X 自身也读取同名环境变量来选择可写缓存目录；仅设置 Java
    # user.home 不会覆盖这一层。该修改只影响当前脚本及其证明器子进程。
    os.environ["KEYMAERAX_HOME"] = str(KEYMAERAX_HOME_DIRECTORY)
    prover_config = replace(
        base_config,
        timeout_seconds=max(base_config.timeout_seconds, 180.0),
        home_directory=KEYMAERAX_HOME_DIRECTORY,
        keep_artifacts=True,
        artifacts_directory=ARTIFACTS_DIRECTORY,
    )
    report = check_hcsp(
        gamma=gamma,
        theta=theta,
        configurations=configurations,
        path_condition=True,
        parameters=parameters,
        keymaerax_config=prover_config,
    )

    print("\n=== Type AST ===")
    if report.inferred_type is None:
        print("(none: at least one general premise was not proved)")
    else:
        print(repr(report.inferred_type))
        print("\n=== Readable Type ===")
        print(report.inferred_type)

    print("\n=== Full derivation report ===")
    print(report.format_detailed())
    return 0 if report.inferred_type is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
