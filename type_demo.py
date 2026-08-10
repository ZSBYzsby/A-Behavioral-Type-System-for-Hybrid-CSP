r"""演示复杂 ODE 在 TypeConstructor 与 TypeChecker 之间的完整往返。

本脚本复用 ``demo.py`` 的第六个示例，并依次执行：

1. 把 Gamma、Theta 和带批注 HCSP 输入交给 TypeConstructor；
2. 把返回的 Type AST 序列化成规范、带缩进的用户 ``type`` 语法；
3. 把该 ``type`` 分节追加到原输入；
4. 将完整输入交给 TypeChecker，逐规则检查同一类型；
5. 核对 Checker 返回的 Type AST 与 Constructor 结果完全相同。

该示例含非平凡 ODE，会在构造和检查阶段各调用一次 KeYmaera X。请在项目根目录
运行：

    python -B type_demo.py

默认打印简洁结果；把 ``OUTPUT_MODE`` 改为 ``"full"`` 可查看两阶段完整日志。
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from textwrap import dedent

from demo import COMPLEX_ODE_SOURCE, KEYMAERAX_TIMEOUT_SECONDS
from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPTypeCheckingError,
    HCSPUntrustedTypeConstructionError,
    check_hcsp_type,
    construct_hcsp_type,
)
from hcsp_typechecker.frontend.type_syntax import format_type_source


# 可选值为 "result" 或 "full"；只改变输出详细程度，不改变数学判断。
OUTPUT_MODE = "result"

# 把证明器的可写 home 和证明产物放在仓库内已被 .gitignore 排除的目录中。
# 这既避免污染用户主目录，也使脚本可在限制系统临时目录写入的环境中运行。
PROJECT_ROOT = Path(__file__).resolve().parent
KEYMAERAX_HOME_DIRECTORY = PROJECT_ROOT / ".keymaerax-home" / "type-demo"
KEYMAERAX_ARTIFACTS_DIRECTORY = (
    PROJECT_ROOT / ".keymaerax-artifacts" / "type-demo"
)


def main() -> int:
    """运行 Constructor -> Type 语法 -> Checker 往返并返回脚本退出码。"""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    if OUTPUT_MODE not in {"result", "full"}:
        print('OUTPUT_MODE 只能设为 "result" 或 "full"。')
        return 2

    process_source = dedent(COMPLEX_ODE_SOURCE).strip()
    os.environ["KEYMAERAX_HOME"] = str(KEYMAERAX_HOME_DIRECTORY)
    os.environ["KEYMAERAX_KEEP_ARTIFACTS"] = "true"
    os.environ["KEYMAERAX_ARTIFACTS"] = str(
        KEYMAERAX_ARTIFACTS_DIRECTORY
    )
    print("HCSP TypeConstructor -> TypeChecker 往返演示")
    print("示例：demo.py 的第六个复杂 ODE")
    print(f"输出模式：{OUTPUT_MODE!r}")

    print("\n" + "=" * 76)
    print("阶段 1：由用户 HCSP 输入构造 Type")
    print("-" * 76)
    try:
        constructed_type = construct_hcsp_type(
            process_source,
            source_name="type_demo:constructor",
            output=OUTPUT_MODE,
            keymaerax_timeout_seconds=KEYMAERAX_TIMEOUT_SECONDS,
        )
    except HCSPInputError:
        # 接口已按 result/full 模式打印精确输入诊断。
        return 1
    except HCSPUntrustedTypeConstructionError:
        # 本演示要求得到可信类型；unknown 候选不能继续冒充正确输入。
        print("阶段 1 未通过：只得到了尚未验证的不可信候选 Type。")
        return 1
    except HCSPTypeConstructionError:
        print("阶段 1 未通过：TypeConstructor 没有得到可信 Type。")
        return 1

    type_source = format_type_source(constructed_type)
    print("\n生成并将要交给 TypeChecker 的 Type 分节：")
    print(type_source)

    typed_source = process_source + "\n" + type_source
    print("\n" + "=" * 76)
    print("阶段 2：把生成的 Type 交回 TypeChecker")
    print("-" * 76)
    try:
        checked_type = check_hcsp_type(
            typed_source,
            source_name="type_demo:checker",
            output=OUTPUT_MODE,
            keymaerax_timeout_seconds=KEYMAERAX_TIMEOUT_SECONDS,
        )
    except HCSPInputError:
        return 1
    except HCSPTypeCheckingError:
        print("阶段 2 未通过：TypeChecker 拒绝了 Constructor 生成的 Type。")
        return 1

    if checked_type != constructed_type:
        print("往返失败：Checker 返回的 Type AST 与 Constructor 结果不一致。")
        return 1

    print("\n" + "=" * 76)
    print("往返成功：Constructor 生成的 Type 已被 TypeChecker 完整验证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
