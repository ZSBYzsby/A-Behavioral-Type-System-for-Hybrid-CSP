r"""验证有限 ODE 的唯一自然终止规则。

测试内容
--------
1. 位于语句末尾的有限 ODE 只使用自然到时规则，并构造 ``delay(1).0``。
2. 自然结束边界为 false 时，构造失败而不会退回 ``\bot``。
3. 边界为 unknown 时，保留 ``delay(1).0`` 作为不可信候选。
4. 直接写在过程末尾的有限 ODE 与 ``ODE; skip`` 具有相同的正常终止语义。

论文对应
--------
本项目把有限 ODE 的省略末尾规范为隐式 ``skip``。因此 Table 2 中带自然
结束后继的 ODE 规则是唯一可用规则；纯通信中断形式不会被 TypeConstructor
用来为一个可自然结束的 HCSP 行为制造 ``\bot`` 后继。
"""

from __future__ import annotations

import unittest
from typing import Any, Callable

from hcsp_typechecker._internal import (
    BasicType,
    Configuration,
    ContinuousType,
    EndType,
    ODE,
    ODEAnnotation,
    FiniteDelayType,
    NoInterruptType,
    TypeConstructionRequest,
    TypeConstructor,
    Verdict,
)


def _boundary_backend(
    boundary: Verdict,
    calls: list[str],
) -> Callable[[Any], Verdict]:
    """建立仅对自然结束边界返回指定结论的可观察 dL 后端。"""

    def decide(obligation: Any) -> Verdict:
        """记录公式角色；安全性质 true 时只有 boundary 会进入后端。"""

        role = getattr(getattr(obligation, "formula", None), "role", "")
        calls.append(role)
        return boundary if role == "boundary" else Verdict.TRUE

    return decide


def _finite_terminal_ode() -> ODE:
    """构造带显式时钟边界、位于语句末尾的有限空流 ODE。"""

    return ODE((), "t < 1", annotation=ODEAnnotation(safety=True, delay=1))


class FiniteODETerminationTests(unittest.TestCase):
    """锁定有限 ODE 绝不退回正式底行为的构造边界。"""

    # 测试输入：带显式时钟演化域的有限空 flow ODE，自然结束边界可证。
    # 预期行为：构造 delay(1).0，且只生成自然结束所需的 boundary 义务。
    # 检查内容：只调用一次 boundary 后端，不产生额外规则分支。
    # 论文对应：有限 ODE 到 d 后进入正常终止后继。
    def test_terminal_ode_constructs_normal_delay_when_boundary_is_proved(self) -> None:
        """可证边界的末尾 ODE 必须得到可信的纯时延正常终止类型。"""

        calls: list[str] = []
        report = TypeConstructor(
            dl_checker=_boundary_backend(Verdict.TRUE, calls)
        ).construct(
            TypeConstructionRequest(
                gamma={},
                theta={},
                configurations=[Configuration({}, _finite_terminal_ode())],
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), EndType()),
        )
        self.assertEqual(calls, ["boundary"])

    # 测试输入：有限空 flow ODE，但自然结束边界被后端否证。
    # 预期行为：类型构造失败，不以 delay(1).bottom 伪造结果。
    # 检查内容：FALSE 终止当前推导分支，constructed_type 为 None。
    # 论文对应：自然到时规则的 boundary 前提必须成立。
    def test_false_boundary_fails_instead_of_falling_back_to_bottom(self) -> None:
        """有限 ODE 的自然结束前提为假时必须直接报告构造失败。"""

        calls: list[str] = []
        report = TypeConstructor(
            dl_checker=_boundary_backend(Verdict.FALSE, calls)
        ).construct(
            TypeConstructionRequest(
                gamma={},
                theta={},
                configurations=[Configuration({}, _finite_terminal_ode())],
            )
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertEqual(calls, ["boundary"])

    # 测试输入：有限空 flow ODE，自然结束边界暂时未知。
    # 预期行为：继续形成 delay(1).0，但将整体结论标为 unknown。
    # 检查内容：结果中不含 BottomType，UNKNOWN 只降低证明可信性。
    # 论文对应：UNKNOWN 仅降低证明可信性，不改变已确定的过程结构。
    def test_unknown_boundary_keeps_an_untrusted_normal_delay(self) -> None:
        """未决边界应保留正常终止候选，而不是切换到底行为。"""

        calls: list[str] = []
        report = TypeConstructor(
            dl_checker=_boundary_backend(Verdict.UNKNOWN, calls)
        ).construct(
            TypeConstructionRequest(
                gamma={},
                theta={},
                configurations=[Configuration({}, _finite_terminal_ode())],
            )
        )

        self.assertEqual(report.verdict, Verdict.UNKNOWN)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), EndType()),
        )
        self.assertEqual(calls, ["boundary"])

    # 测试输入：直接位于过程末尾的有限 ODE，没有显式 ``; skip``。
    # 预期行为：末尾自动补正常 Skip，得到正常终止形状。
    # 检查内容：验证直接 AST 构造入口也不能绕过该规范化语义。
    # 论文对应：有限连续演化自然到时后进入过程的正常终止。
    def test_terminal_finite_ode_has_an_implicit_normal_skip(self) -> None:
        """末尾有限 ODE 应等价于拥有显式 Skip 后继的 ODE。"""

        report = TypeConstructor(
            dl_checker=lambda _obligation: Verdict.TRUE
        ).construct(
            TypeConstructionRequest(
                gamma={
                    "x": BasicType.REAL,
                    "motion": ContinuousType(("x",)),
                },
                theta={},
                configurations=[
                    Configuration(
                        {"x": 0},
                        ODE(
                            (("x", 0),),
                            True,
                            annotation=ODEAnnotation(delay=1),
                        ),
                    )
                ],
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), EndType()),
        )


if __name__ == "__main__":
    unittest.main()
