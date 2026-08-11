r"""演示项目的公开 TypeChecker 接口。

这个脚本直接接收用户写出的 Gamma、Theta、带批注 HCSP Process 和 Type，不调用
TypeConstructor 预先生成类型。第一个例子给出正确类型，应通过逐规则检查；第二个
例子故意漏掉输入后的输出行为，应被 TypeChecker 拒绝。

在项目根目录运行：

    python -B new_demo.py

默认只打印结果。把 ``OUTPUT_MODE`` 改成 ``"full"``，可以查看规则递归、证明
义务以及失败位置的完整日志。
"""

from __future__ import annotations

import sys
from textwrap import dedent

from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeCheckingError,
    TypeCheckingErrorKind,
    check_hcsp_type,
)


# 可选值为 "result" 或 "full"；该设置只影响输出详细程度。
OUTPUT_MODE = "result"


# ch?(x); ch!(x) 的正确类型：先接受 ch 输入，再在同一通道输出，最后为空行为。
CORRECT_TYPE_SOURCE = r"""
gamma(x: Int)
theta(ch: channel(value: Int))
process {{
    ch?(x);
    ch!(x)
}}
type forever interrupt angelic {
    ch? -> forever interrupt angelic {
        ch! -> empty
    }
}
"""


# 故意给错：该类型声称输入 ch 后立即结束，没有描述进程实际执行的 ch!(x)。
WRONG_TYPE_SOURCE = r"""
gamma(x: Int)
theta(ch: channel(value: Int))
process {{
    ch?(x);
    ch!(x)
}}
type forever interrupt angelic {
    ch? -> empty
}
"""


def _run_case(
    *,
    title: str,
    purpose: str,
    source: str,
    should_pass: bool,
) -> bool:
    """执行一个 TypeChecker 示例，并判断结果是否符合该示例的预期。"""

    source = dedent(source).strip()
    print("\n" + "=" * 76)
    print(title)
    print(purpose)
    print("-" * 76)
    print("用户输入：")
    print(source)
    print("\n[TypeChecker] 检查用户 Type 是否符合 Process 和环境")

    try:
        check_hcsp_type(
            source,
            source_name=f"new_demo:{title}",
            output=OUTPUT_MODE,
        )
    except HCSPInputError as error:
        # 接口已打印完整诊断；脚本仅记录可由程序判断的输入错误类别与位置。
        print(
            "脚本结论：输入无效 "
            f"[{error.kind}]，位置 {error.source_name}:{error.line}:{error.column}。"
        )
        return False
    except HCSPTypeCheckingError as error:
        print(
            "脚本结论：TypeChecker 拒绝给定 Type "
            f"[{error.kind.value}/{error.phase}]，"
            f"规则 {error.rule or '-'}，判断位置 {error.location or '-'}。"
        )
        if should_pass:
            return False
        # 本例专门演示 Type 结构不匹配；若因环境或证明失败而被拒绝，说明演示
        # 没有命中预期故障，不能笼统地当成“测试通过”。
        return error.kind is TypeCheckingErrorKind.TYPE_MISMATCH

    # 成功时接口返回已经解析并通过规则检查的正式 Type AST。
    if not should_pass:
        print("演示异常：这个故意写错的 Type 居然通过了检查。")
        return False
    return True


def main() -> int:
    """依次运行一个正确例和一个错误例，并返回适合脚本使用的退出码。"""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    if OUTPUT_MODE not in {"result", "full"}:
        print('OUTPUT_MODE 只能设为 "result" 或 "full"。')
        return 2

    print("HCSP TypeChecker 公共接口演示")
    print(f"输出模式：{OUTPUT_MODE!r}（改为 'full' 可查看完整检查日志）")

    results = (
        _run_case(
            title="1. 正确类型：ch?(x); ch!(x)",
            purpose="预期 TypeChecker 逐层匹配两个通信动作并检查成功。",
            source=CORRECT_TYPE_SOURCE,
            should_pass=True,
        ),
        _run_case(
            title="2. 错误类型：遗漏 ch!(x)",
            purpose="预期 TypeChecker 在输入动作的 continuation 处发现结构不匹配。",
            source=WRONG_TYPE_SOURCE,
            should_pass=False,
        ),
    )

    passed = sum(results)
    print(f"\n演示结束：{passed}/2 个示例得到预期结果。")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
