"""论文 Section 5 Case Study：构造 Process AST 并生成 Type AST。

在项目根目录运行：

    python -B tests/tmp.py

本文件只做两件事：

1. 用项目的 AST 构造器写出 ``Vehicle || Controller``；
2. 调用 ``check_hcsp``，打印生成的行为 Type AST。

论文案例与项目当前语法之间有两处必要的表示调整：

* 论文的 ``stop?``/``stop!`` 是 unit 通信；项目要求每次通信至少携带一个
  标量，所以这里用 ``stop?(stop_signal)``/``stop!(0)`` 表示同一控制事件。
* 论文把 ``dh?... [] stop?...`` 事件选择接在 ``ch!(p,v)`` 后面；项目严格
  区分 Process 和 EventReaction，因此用一个无限等待、无用户状态方程的 ODE
  承载该事件选择。它不会改变用户状态，生成的通信行为类型与论文一致。

案例产生的 dL 前提必须由本机 KeYmaera X 实际证明。只要任何证明义务返回
``false`` 或 ``unknown``，类型推导就会停止并打印部分推导报告；只有全部
证明义务均为 ``true`` 时，程序才输出正式 Type AST。
"""

from __future__ import annotations

import math
import sys
from fractions import Fraction
from pathlib import Path

# 允许直接执行 ``python -B tests/tmp.py``。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hcsp_typechecker import (  # noqa: E402
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    EventChoice,
    HCSP,
    If,
    InputChannel,
    Mu,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Parallel,
    Process,
    RecursionAnnotation,
    Sequence,
    Skip,
    Var,
    check_hcsp,
)


# Section 5 中的符号参数在这个可运行示例中的具体取值。
DESTINATION = 10
MAX_VELOCITY = 4
MIN_ACCELERATION = -2
MAX_ACCELERATION = 2
# 论文把本次 T-ODE 推导所需的 d 作为外部批注，并未固定具体数值。这里暂时取
# d=0，以单独检查零延迟下的推导；使用 Fraction 保证车辆 ODE 批注、phi_a 的
# 一步预测和控制器 wait(d) 读取的是同一个精确有理数。该取值没有实际控制周期。
CONTROL_PERIOD = Fraction(0, 1)

BRAKING_DISTANCE = 4  # vmax^2 / (-2*amin) = 16 / 4。
BRAKING_FACTOR = 4  # -2*amin。


def velocity_safety(position: str, velocity: str) -> str:
    """构造最大速度保护曲线 phi_v。

    论文把到达终点、远离终点和接近终点描述为三个互斥位置区域；这里用
    ``or`` 拼合三个区域。接近终点区域中的平方形式与论文的平方根上界等价，
    但更适合项目当前的一阶逻辑/dL 表达式前端。
    """

    remaining = f"({DESTINATION} - ({position}))"
    return (
        f"((({position}) >= {DESTINATION} and ({velocity}) <= 0) or "
        f"({remaining} >= {BRAKING_DISTANCE} and "
        f"({velocity}) <= {MAX_VELOCITY}) or "
        f"(0 < {remaining} and {remaining} < {BRAKING_DISTANCE} and "
        f"(({velocity}) <= 0 or "
        f"({velocity}) * ({velocity}) <= {BRAKING_FACTOR} * {remaining})))"
    )


def acceleration_safety(
    position: str,
    velocity: str,
    acceleration: str,
) -> str:
    """构造一个控制周期之后仍位于速度保护曲线内的公式 phi_a。"""

    predicted_position = (
        f"(({position}) + ({velocity}) * {CONTROL_PERIOD} + "
        f"({acceleration}) * {CONTROL_PERIOD} ** 2 / 2)"
    )
    predicted_velocity = (
        f"(({velocity}) + ({acceleration}) * {CONTROL_PERIOD})"
    )
    return (
        f"({velocity_safety(predicted_position, predicted_velocity)} and "
        f"{MIN_ACCELERATION} <= ({acceleration}) and "
        f"({acceleration}) <= {MAX_ACCELERATION})"
    )


POSITION_SAFETY = f"p <= {DESTINATION}"
VELOCITY_SAFETY = velocity_safety("p", "v")
ACCELERATION_SAFETY = acceleration_safety("p", "v", "a")
ODE_SAFETY = f"({POSITION_SAFETY}) and ({VELOCITY_SAFETY})"
LOOP_INVARIANT = (
    f"({POSITION_SAFETY}) and "
    f"({VELOCITY_SAFETY}) and "
    f"({ACCELERATION_SAFETY})"
)


def build_vehicle() -> Process:
    """构造 Section 5 的 Vehicle Process AST。"""

    # 接收 a' 之后执行论文中的安全检查 phi_a{a'/a}。
    received_acceleration_is_safe = acceleration_safety(
        "p",
        "v",
        "new_acc",
    )

    # ch!(p,v) 之后，车辆在 dh?new_acc 与 stop? 之间作外部选择。
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
                        Assign("a", MIN_ACCELERATION),
                    ),
                    Var("X"),
                ),
            ),
            (InputChannel("stop", "stop_signal"), Skip()),
        ),
        annotation=ODEAnnotation(safety=ODE_SAFETY, delay=math.inf),
    )

    # 车辆动力学：p'=v, v'=a, a'=0；在一个控制周期内随时可输出 (p,v)。
    continuous_motion = ODE(
        [("p", "v"), ("v", "a"), ("a", 0)],
        True,
        EventChoice.of(
            (OutputChannel("ch", ("p", "v")), decision_wait),
        ),
        annotation=ODEAnnotation(
            safety=ODE_SAFETY,
            delay=CONTROL_PERIOD,
        ),
    )

    loop = Mu(
        "X",
        continuous_motion,
        annotation=RecursionAnnotation(LOOP_INVARIANT),
    )
    return Sequence.of(
        Assign("p", 0),
        Assign("v", 0),
        Assign("a", 0),
        loop,
    )


def build_controller() -> Process:
    """构造 Section 5 的 Controller Process AST。"""

    # accelerate / coast / decelerate 三层控制策略。
    choose_acceleration = If(
        acceleration_safety("x", "y", str(MAX_ACCELERATION)),
        Assign("command", MAX_ACCELERATION),
        If(
            acceleration_safety("x", "y", "0"),
            Assign("command", 0),
            Assign("command", MIN_ACCELERATION),
        ),
    )

    body = Sequence.of(
        InputChannel("ch", ("x", "y")),
        If(
            "y >= 0",
            Sequence.of(
                choose_acceleration,
                OutputChannel("dh", "command"),
                ODE.wait(CONTROL_PERIOD),
                Var("Y"),
            ),
            OutputChannel("stop", 0),
        ),
    )
    return Mu("Y", body, annotation=RecursionAnnotation(True))


def main() -> int:
    """构造 Process AST，经本机证明所有前提后打印 Type AST。"""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    vehicle = build_vehicle()
    controller = build_controller()
    system: HCSP = Parallel.of(vehicle, controller)

    # Gamma 把 process 中出现的完整 ODE 演化向量登记为
    # (p,v,a): R>=0 -> R^3。轨迹性质只由 ODE 节点自身的 safety 定义；隐式
    # 时钟 t 由 ODE 自己追加，不属于这里的向量成员。
    vehicle_trajectory = ContinuousType(
        variables=("p", "v", "a"),
    )
    vehicle_gamma = {
        "p": BasicType.REAL,
        "v": BasicType.REAL,
        "a": BasicType.REAL,
        "vehicle_ode": vehicle_trajectory,
    }
    controller_gamma = {"command": BasicType.REAL}
    gamma = {**vehicle_gamma, **controller_gamma}
    theta = {
        "ch": ChannelType(
            (BasicType.REAL, BasicType.REAL),
            binders=("position", "velocity"),
        ),
        "dh": ChannelType(
            BasicType.REAL,
            refinement=(
                f"{MIN_ACCELERATION} <= eta and "
                f"eta <= {MAX_ACCELERATION}"
            ),
        ),
        "stop": ChannelType(BasicType.INT, refinement="eta == 0"),
    }

    # T-parallel 分别检查两个局部配置，再组合成 ParallelType。
    configurations = (
        Configuration({}, vehicle, gamma=vehicle_gamma, name="Vehicle"),
        Configuration(
            {},
            controller,
            gamma=controller_gamma,
            name="Controller",
        ),
    )

    print("=== Section 5 Process AST ===")
    print(f"Vehicle   : {vehicle!r}")
    print(f"Controller: {controller!r}")
    print(f"System    : {system!r}")

    report = check_hcsp(
        gamma=gamma,
        theta=theta,
        configurations=configurations,
        path_condition=True,
    )

    print("\n=== Generated Type AST ===")
    if report.inferred_type is None:
        print("Type generation stopped because a premise was not proved.")
        print()
        print(report.format_detailed())
        return 1

    print(repr(report.inferred_type))
    print("\n=== Readable Type ===")
    print(report.inferred_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
