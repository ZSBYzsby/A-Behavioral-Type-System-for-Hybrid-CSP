r"""用几个小程序演示项目的两阶段公共接口。

每个示例都从一段完整的用户输入开始：第一阶段调用
``parse_hcsp_program`` 得到绑定了 Gamma、Theta、参数和 Process AST 的
``HCSPProgram``；第二阶段调用 ``infer_hcsp_type`` 得到正式 Type AST。

这些示例只包含离散 HCSP 行为，证明义务由内置的一阶逻辑后端处理，因此运行
本文件不需要启动 KeYmaera X。请在项目根目录执行：

    python -B demo.py

默认使用简洁的 ``result`` 输出。若要查看原始输入、规则轨迹和证明义务，把
下面的 ``OUTPUT_MODE`` 改成 ``"full"`` 即可。
"""

from __future__ import annotations

import sys
from textwrap import dedent

from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeError,
    infer_hcsp_type,
    parse_hcsp_program,
)


# 可选值为 "result" 或 "full"；两种模式只改变显示内容，不改变推导结果。
OUTPUT_MODE = "result"


# 每项依次为：标题、希望展示的功能、完整用户输入。
EXAMPLES = (
    (
        "1. 最小程序：skip",
        "展示空环境以及不执行任何动作的进程；预期 Type AST 为 0。",
        """
        gamma()
        theta()
        process {{skip}}
        """,
    ),
    (
        "2. 通信顺序：ch?(x); ch!(x)",
        "展示输入绑定、顺序后继和同一通道上的单值输出。",
        """
        gamma(x: Int)
        theta(ch: channel(value: Int))
        process {{ch?(x); ch!(x)}}
        """,
    ),
    (
        "3. 参数、赋值、条件与 refinement",
        "展示只读参数约束如何用于赋值、分支和输出 refinement 的证明。",
        """
        gamma(x: Int)
        parameters(limit: Int) where(limit >= 0)
        theta(out: channel(value: Int) where(value <= limit))
        process {{
            x := limit;
            if (x == limit) {
                out!(x)
            } else {
                skip
            }
        }}
        """,
    ),
    (
        "4. 两个独立分量并行执行",
        "展示 Gamma 的状态分区以及两个分量类型组成的并行 Type AST。",
        """
        gamma(left_state: Int, right_state: Int)
        theta(
            left: channel(value: Int),
            right: channel(value: Int)
        )
        process {
            {left_state := 1; left!(left_state)},
            {right_state := 2; right!(right_state)}
        }
        """,
    ),
)


def _run_example(index: int, title: str, purpose: str, source: str) -> bool:
    """运行单个示例；成功返回 ``True``，并让失败信息保持在对应示例内。"""

    source = dedent(source).strip()
    separator = "=" * 76
    print(f"\n{separator}")
    print(title)
    print(purpose)
    print("-" * 76)
    print("用户输入：")
    print(source)

    print("\n[第一阶段] 用户输入 -> HCSPProgram")
    # infer_hcsp_type 的 full 日志已经包含第一阶段的完整模型；此时让解析接口
    # 静默，避免把同一份原始输入和 Process AST 打印两次。
    parse_output = "none" if OUTPUT_MODE == "full" else OUTPUT_MODE
    try:
        program = parse_hcsp_program(
            source,
            source_name=f"demo-example-{index}.hcsp",
            output=parse_output,
        )
    except HCSPInputError as error:
        print(error.format_diagnostic())
        return False

    if OUTPUT_MODE == "full":
        print("解析成功；完整 HCSPProgram 将显示在下一阶段的日志开头。")

    print("\n[第二阶段] HCSPProgram -> Type AST")
    try:
        infer_hcsp_type(program, output=OUTPUT_MODE)
    except HCSPTypeError as error:
        # 接口已经按所选模式打印结果；这里只在静默模式下补充异常内容。
        if OUTPUT_MODE == "none":
            print(error.format_full())
        return False
    return True


def main() -> int:
    """依次运行全部示例，并用退出码表示是否全部转换成功。"""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    if OUTPUT_MODE not in {"result", "full"}:
        print('OUTPUT_MODE 只能设为 "result" 或 "full"。')
        return 2

    print("HCSP 公共接口演示")
    print(f"输出模式：{OUTPUT_MODE!r}（改为 'full' 可查看完整推导日志）")

    succeeded = 0
    for index, (title, purpose, source) in enumerate(EXAMPLES, start=1):
        if _run_example(index, title, purpose, source):
            succeeded += 1

    print(f"\n演示结束：{succeeded}/{len(EXAMPLES)} 个示例转换成功。")
    return 0 if succeeded == len(EXAMPLES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
