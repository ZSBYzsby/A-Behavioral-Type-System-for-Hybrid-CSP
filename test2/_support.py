"""``test2`` 单文件样例共用的运行和精确类型断言工具。

本模块刻意只抽取机械性的公共代码。每个 HCSP 程序、Gamma、Theta、初始状态、
路径条件和预期 Type AST 仍完整写在各自样例文件中，审计者不必跨文件还原输入。

ODE 样例默认注入一个固定返回 ``true`` 的 dL 后端：这些文件的职责是验证
Process -> Type 的结构转换和证明义务生成，不依赖本机 KeYmaera X 安装。真实
dL 翻译与后端执行继续由 ``tests/dl`` 中的专门测试覆盖。
"""

from __future__ import annotations

import unittest
from typing import Any, Callable, Mapping, Sequence

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    CheckReport,
    Configuration,
    ConfigurationType,
    Verdict,
    check_hcsp,
    types_equivalent,
)


def approve_dl(_obligation: object) -> Verdict:
    """把 dL 义务固定判为真，使样例只测试类型结构与义务生成。"""

    return Verdict.TRUE


def check_process(
    process: Any,
    *,
    gamma: Mapping[str, BasicType] | None = None,
    theta: Mapping[str, ChannelType | Any] | None = None,
    state: Mapping[str, Any] | None = None,
    path_condition: Any = True,
    dl_checker: Callable[[object], Any] | None = approve_dl,
) -> CheckReport:
    """把一个 HCSP 进程包装成单配置 judgment，并返回完整审计报告。"""

    return check_hcsp(
        gamma=gamma,
        theta=theta,
        configurations=[Configuration(state, process)],
        path_condition=path_condition,
        dl_checker=dl_checker,
    )


def assert_conversion(
    test_case: unittest.TestCase,
    report: CheckReport,
    expected_type: ConfigurationType | None,
    *,
    expected_verdict: Verdict = Verdict.TRUE,
    obligation_rules: Sequence[str] = (),
    diagnostic_contains: Sequence[str] = (),
) -> None:
    """精确检查 verdict、候选 Type AST、规则证据和必要诊断文本。"""

    detail = report.format_detailed()
    test_case.assertEqual(report.verdict, expected_verdict, detail)
    if expected_type is None:
        test_case.assertIsNone(report.inferred_type, detail)
    else:
        test_case.assertIsNotNone(report.inferred_type, detail)
        test_case.assertTrue(
            types_equivalent(report.inferred_type, expected_type),
            f"Expected Type AST: {expected_type!r}\n{detail}",
        )

    actual_rules = tuple(item.rule for item in report.obligations)
    for required_rule in obligation_rules:
        test_case.assertIn(required_rule, actual_rules, detail)

    diagnostics = "\n".join(item.message for item in report.diagnostics)
    for fragment in diagnostic_contains:
        test_case.assertIn(fragment, diagnostics, detail)

