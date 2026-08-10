r"""用几个小程序演示项目的单一公共 TypeConstructor 接口。

每个示例都把包含 Parameters、Gamma、Theta 和 Process 的完整用户输入直接交给
``construct_hcsp_type``；接口在内部完成解析、类型构造和必要公式证明，成功时
返回正式 Type AST。

前四个示例是离散 HCSP；第五个示例使用空 flow、隐式时钟边界 ``t < 1`` 和恒真
安全性质展示有限 delay；第六个示例则包含二阶微分方程、隐式时钟、非线性 safety、多标量
通信中断和自然超时后继，会实际调用 KeYmaera X。请在项目根目录执行：

    python -B demo.py

默认使用简洁的 ``result`` 输出。若要查看原始输入、规则轨迹和证明义务，把
下面的 ``OUTPUT_MODE`` 改成 ``"full"`` 即可。
"""

from __future__ import annotations

import sys
from textwrap import dedent

from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    construct_hcsp_type,
)


# 可选值为 "result" 或 "full"；两种模式只改变显示内容，不改变类型构造结果。
OUTPUT_MODE = "result"

# 第六个示例需要真实 dL 证明；该值只覆盖本次接口调用的证明器超时。
KEYMAERAX_TIMEOUT_SECONDS = 180.0


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
    (
        "5. 有限 delay 与通信中断",
        "展示在 1 个时间单位内等待输入；t < 1 使 ODE 恰在时限到达时停止。",
        """
        gamma(x: Int)
        theta(ch: channel(value: Int))
        process {{
            ode(
                flow(),
                domain(t < 1),
                safety(true),
                delay(1),
                interrupt(
                    on ch?(x) {
                        skip
                    }
                )
            )
        }}
        """,
    ),
    (
        "6. 二阶微分方程、多标量中断与自然超时后继",
        "展示 p'=v、v'=2、隐式 t、非线性 safety、delay(3/2) 和 timed choice。",
        """
        gamma(
            p: Real,
            v: Real,
            new_p: Real,
            new_v: Real,
            motion: continuous(p, v)
        )
        theta(
            reset: channel(rp: Real, rv: Real)
                where(rp >= 0 and rv >= 0),
            report: channel(out_p: Real, out_v: Real)
                where(out_p >= 0 and out_v >= 0)
        )
        process {{
            p := 0;
            v := 0;
            ode(
                flow(
                    dot p = v,
                    dot v = 2
                ),
                domain(t < 3 / 2),
                safety(
                    p == t ** 2 and
                    v == 2 * t and
                    p >= 0 and
                    v >= 0
                ),
                delay(3 / 2),
                interrupt(
                    on reset?(new_p, new_v) {
                        p := new_p;
                        v := new_v
                    }
                )
            );
            report!(p, v)
        }}
        """,
    ),
)


def _run_example(index: int, title: str, purpose: str, source: str) -> str:
    """运行单个示例，返回 ``trusted``、``untrusted`` 或 ``failed``。"""

    source = dedent(source).strip()
    separator = "=" * 76
    print(f"\n{separator}")
    print(title)
    print(purpose)
    print("-" * 76)
    print("用户输入：")
    print(source)

    print("\n[类型构造] 用户输入 -> Type AST")
    try:
        construct_hcsp_type(
            source,
            source_name=f"demo-example-{index}.hcsp",
            output=OUTPUT_MODE,
            keymaerax_timeout_seconds=KEYMAERAX_TIMEOUT_SECONDS,
        )
    except HCSPInputError:
        # result/full 模式已经输出解析诊断；这里只记录该示例失败，避免重复打印。
        return "failed"
    except HCSPUntrustedTypeConstructionError:
        # 类型结构已构造完成，但 result/full 已把候选明确标为未验证、不可信。
        return "untrusted"
    except HCSPTypeConstructionError:
        # 确定失败或无法形成完整类型；接口已经打印原因与实际部分构造过程。
        return "failed"
    return "trusted"


def main() -> int:
    """运行全部示例；只有输入错误或无法构造类型时返回非零退出码。"""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    if OUTPUT_MODE not in {"result", "full"}:
        print('OUTPUT_MODE 只能设为 "result" 或 "full"。')
        return 2

    print("HCSP TypeConstructor 公共接口演示")
    print(f"输出模式：{OUTPUT_MODE!r}（改为 'full' 可查看完整构造日志）")

    outcomes = {"trusted": 0, "untrusted": 0, "failed": 0}
    for index, (title, purpose, source) in enumerate(EXAMPLES, start=1):
        outcome = _run_example(index, title, purpose, source)
        outcomes[outcome] += 1

    print(
        "\n演示结束："
        f"可信类型 {outcomes['trusted']} 个，"
        f"完整但未验证的候选 {outcomes['untrusted']} 个，"
        f"构造失败 {outcomes['failed']} 个。"
    )
    return 0 if outcomes["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
