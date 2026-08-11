"""演示脚本对结构化 Constructor/Checker 错误接口的使用测试。

测试内容
--------
1. TypeConstructor 演示遇到输入错误和证明失败时，读取 ``kind/phase/rule/location``
   形成脚本结论，而不重新打印完整异常报告；
2. TypeChecker 演示中的故意错误必须精确归类为 ``type-mismatch``，不能把任意
   环境错误或证明失败误判为“示例符合预期”。

论文对应
--------
这些断言只约束演示层如何报告 Table 2 推导失败，不改变任何规则、公式或证明结论。
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest

import demo
import new_demo


class DemoStructuredErrorTests(unittest.TestCase):
    """锁定演示脚本不再依赖异常展示文本推测失败原因。"""

    # 测试输入：缺少 process 右花括号的非法完整输入。
    # 预期行为：Constructor 演示返回 failed，并打印 input-syntax 与精确位置。
    # 检查内容：脚本结论读取 HCSPInputError 的 kind/source_name/line/column。
    # 论文对应：输入尚未形成 Process AST，Table 2 推导不得启动。
    def test_constructor_demo_reports_structured_input_error(self) -> None:
        """输入失败应按前端错误类别和源码位置报告。"""

        output = StringIO()
        with redirect_stdout(output):
            outcome = demo._run_example(
                99,
                "非法输入",
                "验证结构化输入诊断",
                "gamma() theta() process {{skip",
            )

        rendered = output.getvalue()
        self.assertEqual(outcome, "failed")
        self.assertIn("脚本结论：输入无效 [input-syntax]", rendered)
        self.assertIn("demo-example-99.hcsp:", rendered)

    # 测试输入：语法正确但含 assert(false) 的构造输入。
    # 预期行为：接口以 proof-failed 拒绝，演示显示 proof 阶段与 T-Assert。
    # 检查内容：脚本读取 HCSPTypeConstructionError 的 kind/phase/rule/location。
    # 论文对应：T-Assert 的必要 FOL 前提被否证后不存在可信类型结论。
    def test_constructor_demo_reports_structured_proof_failure(self) -> None:
        """确定证明失败应显示类别、阶段和规则。"""

        output = StringIO()
        with redirect_stdout(output):
            outcome = demo._run_example(
                100,
                "否证断言",
                "验证结构化证明失败",
                "gamma() theta() process {{assert(false)}}",
            )

        rendered = output.getvalue()
        self.assertEqual(outcome, "failed")
        self.assertIn("[proof-failed/proof]", rendered)
        self.assertIn("规则 T-Assert", rendered)
        self.assertIn("判断位置 K1", rendered)

    # 测试输入：new_demo 的一份正确 Type 和一份遗漏输出动作的错误 Type。
    # 预期行为：前者通过；后者只因 type-mismatch 被认定为预期失败；main 返回 0。
    # 检查内容：输出含结构化 checker 类别，且不再打印无用的 Python 返回对象类型。
    # 论文对应：Checker 必须逐层匹配 T-In 后继中的 T-Out 结论。
    def test_checker_demo_requires_the_expected_error_kind(self) -> None:
        """错误 Type 示例必须命中结构不匹配，而非任意失败。"""

        output = StringIO()
        with redirect_stdout(output):
            exit_code = new_demo.main()

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("[type-mismatch/type-matching]", rendered)
        self.assertIn("规则 T-Out", rendered)
        self.assertNotIn("Python 返回对象", rendered)


if __name__ == "__main__":
    unittest.main()
