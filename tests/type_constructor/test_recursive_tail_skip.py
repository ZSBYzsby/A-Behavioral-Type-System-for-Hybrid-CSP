r"""验证 ``skip`` 不会破坏递归调用的尾位置。

测试内容
--------
1. 多元内部选择缺省公共后继产生的 ``X;skip`` 仍是合法尾递归；
2. 用户显式写出的 ``call X;skip`` 具有相同的空行为语义；
3. ``call X`` 后存在任意非 ``skip`` 进程时仍被拒绝；
4. TypeConstructor 形成的递归 Type 可由 TypeChecker 原样确认。

论文对应
--------
T-X 只允许递归变量出现在尾位置。项目的 ``Skip`` 构造 ``EmptyType``，不产生
通信或状态动作；因此它不是递归调用之后的有效行为。这个局部化简只用于递归
尾位置判断，不影响 ``ODE;skip`` 对两条 ODE 规则的显式候选语义。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker import (
    HCSPTypeConstructionError,
    check_hcsp_type,
    construct_hcsp_type,
)
from hcsp_typechecker.frontend.type_syntax import format_type_source


_CHOICE_WITH_IMPLICIT_SKIP = """gamma()
theta(a: channel(value: Int), b: channel(value: Int))
process {{
    mu X invariant(true) {
        choose {a!(0); call X} or {b!(0); call X}
    }
}}"""


class RecursiveTailSkipTests(unittest.TestCase):
    """锁定递归尾位置判断对空操作和真实后继的区分。"""

    # 测试输入：两个内部选择分支都以受通信保护的 call X 结束，Q 未显式书写。
    # 预期行为：缺省 continuation=Skip 不导致 T-X 报非尾调用。
    # 检查内容：Constructor 成功，且其规范 Type 源码可被 Checker 接受。
    # 论文对应：T-sqcup 分支中的 X 仍位于各自完整行为的尾部。
    def test_choice_default_skip_preserves_tail_recursion(self) -> None:
        """内部选择的缺省空后继不得制造虚假的非尾递归。"""

        constructed = construct_hcsp_type(_CHOICE_WITH_IMPLICIT_SKIP)
        checked = check_hcsp_type(
            _CHOICE_WITH_IMPLICIT_SKIP + "\n" + format_type_source(constructed)
        )

        self.assertEqual(format_type_source(checked), format_type_source(constructed))

    # 测试输入：通信后执行 call X; skip，skip 是用户显式写出的末尾空操作。
    # 预期行为：与直接以 call X 结束完全相同，递归类型构造成功。
    # 检查内容：T-X 的有效 tail 为空，但通信守卫检查仍然生效。
    # 论文对应：skip 的类型为 EmptyType，不增加递归回边后的可观察行为。
    def test_explicit_skip_after_call_is_still_tail_position(self) -> None:
        """显式 ``X;skip`` 应按尾递归处理。"""

        source = """gamma()
theta(a: channel(value: Int))
process {{mu X invariant(true) {a!(0); call X; skip}}}"""

        construct_hcsp_type(source)

    # 测试输入：通信后执行 call X; skip; assert(true)。
    # 预期行为：虽然中间 skip 可忽略，但 assert 是实际后继，构造必须失败。
    # 检查内容：实现不能把整个 tail 因含有 skip 而错误地当成空。
    # 论文对应：T-X 的递归回边之后存在非空顺序行为，因而不在尾位置。
    def test_non_skip_after_call_remains_non_tail(self) -> None:
        """忽略 skip 后仍有进程时必须继续拒绝非尾递归。"""

        source = """gamma()
theta(a: channel(value: Int))
process {{mu X invariant(true) {a!(0); call X; skip; assert(true)}}}"""

        with self.assertRaisesRegex(
            HCSPTypeConstructionError,
            "tail position",
        ):
            construct_hcsp_type(source)

    # 测试输入：整个递归进程后仅有一个显式 skip。
    # 预期行为：T-mu 与 T-X 一致地忽略该空后继，构造仍然成功。
    # 检查内容：尾位置语义不仅修复选择分支，也覆盖递归结点的外层顺序尾。
    # 论文对应：``(mu X.P);skip`` 与 ``mu X.P`` 的通信行为抽象相同。
    def test_skip_after_mu_is_not_an_observable_continuation(self) -> None:
        """递归进程本身之后的 skip 也不应超出尾递归片段。"""

        source = """gamma()
theta(a: channel(value: Int))
process {{mu X invariant(true) {a!(0); call X}; skip}}"""

        construct_hcsp_type(source)


if __name__ == "__main__":
    unittest.main()
