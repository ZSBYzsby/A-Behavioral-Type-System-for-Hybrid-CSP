"""复杂 ODE 的 Constructor -> 用户 Type 语法 -> Checker 往返演示测试。

测试内容
--------
复用 ``demo.py`` 第六个示例，确认 ``type_demo.main`` 先构造 Type AST，再把规范
Type 文本追加回原输入，并由 TypeChecker 成功验证同一类型。

论文对应
--------
同一组 Table 2 规则既可由 TypeConstructor 自底向上形成结论，也可由
TypeChecker 以该结论为目标递归检查。测试只替换外部 dL 后端的证明结果，不改写
Process、Type 或任何规则结构。
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

import type_demo


class TypeDemoRoundTripTests(unittest.TestCase):
    """锁定第六个复杂示例在两个公开业务入口之间的完整往返。"""

    # 测试输入：demo.py 第六个二阶 ODE、多标量中断与有限自然后继示例。
    # 预期行为：Constructor 与 Checker 均返回 true，脚本退出码为 0。
    # 检查内容：生成的缩进 type 分节进入 Checker，最终 Type AST 类别一致。
    # 论文对应：T-Assign、T-ODE、T-&、T-Out 与 T-End 的同一推导树可构造也可检查。
    def test_sixth_demo_round_trips_through_constructor_and_checker(self) -> None:
        """Constructor 生成的复杂 ODE Type 必须可被 Checker 接受。"""

        output = StringIO()
        with patch(
            "hcsp_typechecker.backend.common.keymaerax."
            "KeYmaeraXBackend.__call__",
            return_value=True,
        ) as backend, redirect_stdout(output):
            exit_code = type_demo.main()

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertGreater(backend.call_count, 0)
        self.assertIn("Type 源码 : type delay(3/2)", rendered)
        self.assertIn("reset? -> forever interrupt angelic", rendered)
        self.assertIn("往返成功", rendered)
        self.assertNotIn("FiniteDelayType", rendered)


if __name__ == "__main__":
    unittest.main()
