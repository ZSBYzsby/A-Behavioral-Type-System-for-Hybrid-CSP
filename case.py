r"""用 KeYmaera X 验证 Section 5 安全公式的参数化反例。

本文件验证的不是某一个固定 ``d`` 的数值样例，而是保留 ``d`` 为自由实变量。
KeYmaera X 证明下面两条对所有 ``d > 0`` 都成立的公式：

1. 参数化构造的初始状态满足 ``phi_p and phi_v and phi_a and t=0``；
2. 同一状态沿 ``p'=v, v'=a, a'=0, t'=1`` 演化到 ``t=d/2`` 时，能够到达
   ``not (phi_p and phi_v)``。

第二条使用 dL 的 diamond 模态，直接证明不安全状态“可达”。它与原安全公式中
要求所有轨迹都安全的 box 模态相反，因此两条证明同时成功就是一个可信的反例
证据。生成的 ``.kyx/.kyp`` 文件保存在被 Git 忽略的
``tmp/case-keymaerax-artifacts`` 中，方便人工审计。

案例固定采用论文示例中的参数：

* ``end = 10``：目标位置；
* ``vmax = 4``：最大速度；
* ``amin = -2``：最小加速度（最大制动强度）；
* ``amax = 2``：最大加速度；
* ``sb = vmax^2 / (-2*amin) = 4``：最大速度对应的制动距离；
* ``-2*amin = 4``：接近终点时速度平方上界中的制动系数。

运行方式：

    python case.py

需要事先按 README 配置 ``KEYMAERAX_JAR``；Java 可由 ``KEYMAERAX_JAVA``、
``JAVA_HOME`` 或 ``PATH`` 提供。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from hcsp_typechecker import (
    DLFormula,
    KeYmaeraXBackend,
    KeYmaeraXConfig,
    ProofObligation,
    Verdict,
)


PROJECT_ROOT = Path(__file__).resolve().parent
ARTIFACTS_DIRECTORY = PROJECT_ROOT / "tmp" / "case-keymaerax-artifacts"

# --------------------------------------------------------------------------
# Section 5 案例的固定物理参数。代码使用清晰的 Python 名称，右侧注释给出
# 公式中的论文记号；这些值固定不变，只有反例中的 delay ``d`` 保持任意正数。
# --------------------------------------------------------------------------
END_POSITION = 10  # end = 10：目标位置。
MAX_VELOCITY = 4  # vmax = 4：允许的最大速度。
MIN_ACCELERATION = -2  # amin = -2：允许的最小加速度。
MAX_ACCELERATION = 2  # amax = 2：允许的最大加速度。

# sb = vmax^2 / (-2*amin) = 16/4 = 4。
BRAKING_DISTANCE = MAX_VELOCITY**2 // (-2 * MIN_ACCELERATION)
# -2*amin = 4；phi_v 的近距离分支写成 v^2 <= 4*(end-p)。
BRAKING_FACTOR = -2 * MIN_ACCELERATION


def phi_p(position: str) -> str:
    """返回位置安全性质 ``p <= 10`` 的 KeYmaera X 文本。"""

    return f"({position}<={END_POSITION})"


def phi_v(position: str, velocity: str) -> str:
    r"""展开当前案例的速度安全性质 ``phi_v(position, velocity)``。"""

    remaining = f"({END_POSITION}-({position}))"
    return (
        f"((({position})>={END_POSITION} & ({velocity})<=0) | "
        f"({remaining}>={BRAKING_DISTANCE} & "
        f"({velocity})<={MAX_VELOCITY}) | "
        f"(0<{remaining} & {remaining}<{BRAKING_DISTANCE} & "
        f"(({velocity})<=0 | "
        f"({velocity})^2<={BRAKING_FACTOR}*{remaining})))"
    )


def phi_a(position: str, velocity: str, acceleration: str, delay: str) -> str:
    r"""展开 ``phi_a``：预测 ``d`` 时刻的 ``phi_v`` 加上加速度范围。"""

    predicted_position = (
        f"(({position})+({velocity})*({delay})+"
        f"({acceleration})*({delay})^2/2)"
    )
    predicted_velocity = f"(({velocity})+({acceleration})*({delay}))"
    return (
        f"({phi_v(predicted_position, predicted_velocity)} & "
        f"{MIN_ACCELERATION}<=({acceleration}) & "
        f"({acceleration})<={MAX_ACCELERATION})"
    )


# 对每个 d>0 使用同一个有理参数化构造：
#
#     u = d/(d+1),
#     p = end-u^2/(-2*amin) = 10-u^2/4,
#     v = u,
#     a = -2u/d = -2/(d+1),
#     t = 0.
#
# d>0 蕴含 0<u<d、0<u<1，因而加速度始终属于 (-2,0)。完整演化 d 时间后
# 位置回到 p、速度变成 -u；但在 d/2 时速度为 0，位置已经严格大于 end=10。
U = "(d/(d+1))"
CONSTRUCTION = (
    f"(d>0 & u={U} & p={END_POSITION}-u^2/{BRAKING_FACTOR} & v=u & "
    f"a=-2*u/d & t=0)"
)

INITIAL_SAFETY = (
    f"({phi_p('p')} & {phi_v('p', 'v')} & {phi_a('p', 'v', 'a', 'd')})"
)

ODE_PROGRAM = "{p'=v, v'=a, a'=0, t'=1 & t<=d/2}"
MIDPOINT_UNSAFE = (
    f"(t=d/2 & t<=d & p>{END_POSITION} & v=0 & "
    f"!({phi_p('p')} & {phi_v('p', 'v')}))"
)


def obligation(name: str, source: str, description: str) -> ProofObligation:
    """把一条直接书写的、可审计 dL 公式包装成项目证明义务。"""

    formula = DLFormula(
        source=source,
        variables=("d", "u", "p", "v", "a", "t"),
        symbol_map=tuple((name, name) for name in ("d", "u", "p", "v", "a", "t")),
        role=name,
    )
    return ProofObligation(
        rule=f"Counterexample-{name}",
        description=description,
        formula=formula,
        kind="dl",
    )


def main() -> int:
    """调用本机 KeYmaera X，并在两条证明都成功时返回零。"""

    base_config = KeYmaeraXConfig.from_environment()
    config = replace(
        base_config,
        timeout_seconds=max(base_config.timeout_seconds, 120.0),
        keep_artifacts=True,
        artifacts_directory=ARTIFACTS_DIRECTORY,
    )
    backend = KeYmaeraXBackend(config)

    obligations = (
        obligation(
            "initial-premise",
            f"({CONSTRUCTION} -> {INITIAL_SAFETY})",
            "The parameterized state satisfies phi_p, phi_v, and phi_a",
        ),
        obligation(
            "unsafe-midpoint",
            f"({CONSTRUCTION} -> <{ODE_PROGRAM}>{MIDPOINT_UNSAFE})",
            "The ODE can reach an unsafe state at time d/2",
        ),
    )

    print("=== KeYmaera X parameterized counterexample check ===")
    print("Fixed case parameters:")
    print(f"  end  = {END_POSITION}")
    print(f"  vmax = {MAX_VELOCITY}")
    print(f"  amin = {MIN_ACCELERATION}")
    print(f"  amax = {MAX_ACCELERATION}")
    print(f"  sb   = vmax^2/(-2*amin) = {BRAKING_DISTANCE}")
    print(f"  -2*amin = {BRAKING_FACTOR}")
    print("Parameter condition: d > 0")
    print(f"Construction      : {CONSTRUCTION}")
    print(f"Artifacts         : {ARTIFACTS_DIRECTORY}")

    all_proved = True
    for index, item in enumerate(obligations, start=1):
        result = backend.check(item)
        print(f"\n[{index}] {item.description}")
        print(f"Formula : {item.formula}")
        print(f"Verdict : {result.verdict}")
        print(f"Detail  : {result.detail}")
        all_proved = all_proved and result.verdict is Verdict.TRUE

    print("\n=== Conclusion ===")
    if all_proved:
        print("Counterexample verified for every d > 0.")
        print("The initial premise holds, but an unsafe state is reachable at t=d/2.")
        return 0

    print("Counterexample was not fully verified; inspect the verdicts above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
