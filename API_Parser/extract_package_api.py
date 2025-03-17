import sys
import os
import venv
import subprocess
import importlib.util
import importlib
import inspect
import json
import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from packaging import version

def create_or_use_venv(venv_path: str) -> None:
    """
    如果 venv_path 不存在，就创建它；否则直接重用已有虚拟环境。
    """
    if os.path.exists(venv_path):
        print(f"【提示】使用已有虚拟环境: {venv_path}")
        return

    print(f"【操作】正在创建虚拟环境: {venv_path}")
    venv.EnvBuilder(with_pip=True).create(venv_path)
    print(f"【完成】虚拟环境已创建: {venv_path}")

def get_python_path(venv_path: str) -> str:
    """
    返回虚拟环境中的 python.exe 或 python 的绝对路径。
    """
    if os.name == "nt":
        return os.path.join(venv_path, "Scripts", "python.exe")
    else:
        return os.path.join(venv_path, "bin", "python")

def upgrade_build_tools(python_path: str) -> None:
    """
    使用虚拟环境中的 Python 执行 pip 升级命令，避免直接修改 pip 导致的错误。
    """
    print("【操作】升级虚拟环境内的 pip / setuptools / wheel ...")
    subprocess.check_call([python_path, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

def install_package_in_venv(
    venv_path: str,
    package_name: str,
    package_version: Optional[str] = None
) -> None:
    """
    在虚拟环境中安装指定包。
    - 自动升级构建工具（调用 upgrade_build_tools）
    - 针对 Python 3.11+ 环境中安装 numpy 版本低于 1.23 的情况，自动替换为 numpy==1.23.5
    """
    python_path = get_python_path(venv_path)
    # 升级构建工具
    upgrade_build_tools(python_path)

    # 处理兼容性逻辑：若安装 numpy 且 Python 3.11+ 且版本低于 1.23，则改用 1.23.5
    if package_name.lower() == "numpy" and sys.version_info >= (3, 11):
        if package_version:
            try:
                if version.parse(package_version) < version.parse("1.23"):
                    print(f"【警告】Python 3.11 不支持 numpy=={package_version}，改用 numpy==1.23.5")
                    package_version = "1.23.5"
            except Exception as e:
                print(f"【警告】版本解析出错({e})，将安装 numpy 的最新版本。")
                package_version = None
        else:
            print("【提示】Python 3.11 上安装 numpy 未指定版本，默认安装最新版。")

    pkg_spec = f"{package_name}=={package_version}" if package_version else package_name

    print(f"【操作】安装包: {pkg_spec} (若有可用.whl 将优先使用)")
    try:
        subprocess.check_call([python_path, "-m", "pip", "install", "--prefer-binary", pkg_spec])
        print(f"【完成】'{pkg_spec}' 安装成功。")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"安装 '{pkg_spec}' 失败: {e}")

def add_venv_site_packages_to_sys_path(venv_path: str) -> None:
    """
    将虚拟环境中的 site-packages 路径添加到 sys.path 中，便于后续导入安装包。
    """
    if os.name == "nt":
        site_pkgs = os.path.join(venv_path, "Lib", "site-packages")
    else:
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        site_pkgs = os.path.join(venv_path, "lib", f"python{py_ver}", "site-packages")

    if site_pkgs not in sys.path:
        sys.path.insert(0, site_pkgs)
        print(f"【提示】已将 site-packages 添加至导入路径: {site_pkgs}")

def parse_init_file(init_path: str) -> Set[str]:
    """
    基础的 __init__.py 分析，只能获取简单的 import、from-import、__all__ = [...]（字面量列表）等；
    遇到复杂情况（如大量动态拼接）则可能无法全部获取。
    """
    symbols = set()
    with open(init_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=init_path)

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                # "import X" -> 记录 "X"
                symbols.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # "from X import Y" -> 记录 "X".split('.')[0] 和别名 Y
                parts = node.module.split(".")
                if parts[0]:  # 不要空字符串
                    symbols.add(parts[0])
            for alias in node.names:
                symbols.add(alias.name)
        elif isinstance(node, ast.Assign):
            # if it's `__all__ = [ ... ]`
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "__all__"
            ):
                # 只处理列表或元组的字面量
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Str):
                            symbols.add(elt.s)

    return symbols

def is_deprecated_doc(doc: Optional[str]) -> bool:
    """
    判断 docstring 中是否包含 'deprecated' 关键词。
    """
    return bool(doc and "deprecated" in doc.lower())

def extract_doc_section(doc: Optional[str], keywords: List[str]) -> Optional[str]:
    """
    从 docstring 中提取包含指定关键字（如 :raise, :returns 等）的行。
    """
    if not doc:
        return None
    lines = doc.splitlines()
    matched = [line.strip() for line in lines if any(k in line.lower() for k in keywords)]
    return "\n".join(matched) if matched else None

def build_api_item(full_id: str, obj: Any, parent_class: Optional[type] = None) -> Dict[str, Any]:
    """
    构造 API 条目：包含 doc、signature、source_code、参数信息等。
    同时增加 module 和 file 属性供后续参考。
    """
    doc = inspect.getdoc(obj) or ""
    try:
        source_code = inspect.getsource(obj)
    except Exception:
        source_code = None
    try:
        sig = str(inspect.signature(obj))
    except Exception:
        sig = "()"

    if inspect.isclass(obj):
        obj_type = "class"
    elif inspect.isfunction(obj) or inspect.ismethod(obj):
        obj_type = "member_function" if parent_class else "function"
    elif inspect.ismodule(obj):
        obj_type = "module"
    else:
        obj_type = "unknown"

    parameters_info = {}
    if obj_type in ("function", "member_function"):
        try:
            sig_obj = inspect.signature(obj)
            for param_name, param in sig_obj.parameters.items():
                parameters_info[param_name] = {
                    "description": None,
                    "is_optional": (param.default is not inspect.Parameter.empty)
                }
        except Exception:
            pass

    # 新增: 获取模块名和文件路径（相对路径）
    module_name = getattr(obj, '__module__', None)
    try:
        file_path = inspect.getfile(obj)
        rel_file_path = os.path.relpath(file_path) if file_path else None
    except Exception:
        rel_file_path = None

    return {
        "_id": full_id,
        "doc": doc,
        "is_deprecated": is_deprecated_doc(doc),
        "source_code": source_code,
        "signature": sig,
        "parameters": parameters_info,
        "returns_doc": extract_doc_section(doc, [":return", ":returns"]),
        "raise_doc": extract_doc_section(doc, [":raise", ":raises"]),
        "type": obj_type,
        "class": parent_class.__name__ if parent_class else None,
        "from_init": False,  # 默认标记，后续再根据获取的“从 init 导出”符号来更改
        "module": module_name,
        "file": rel_file_path,
    }

def traverse_module(module: Any, visited: Optional[set] = None) -> List[Dict[str, Any]]:
    """
    递归遍历模块，收集类、函数、方法以及子模块的 API 信息。
    """
    if visited is None:
        visited = set()

    results = []
    mod_name = getattr(module, "__name__", "unknown")
    if mod_name in visited:
        return results
    visited.add(mod_name)

    # 收集模块本身的信息
    results.append(build_api_item(mod_name, module))

    for name, member in inspect.getmembers(module):
        full_id = f"{mod_name}.{name}"
        if inspect.ismodule(member):
            if getattr(member, "__name__", "").startswith(mod_name.split(".")[0]):
                results.extend(traverse_module(member, visited=visited))
        elif inspect.isclass(member):
            results.append(build_api_item(full_id, member))
            for sub_name, sub_member in inspect.getmembers(member):
                if inspect.isfunction(sub_member) or inspect.ismethod(sub_member):
                    method_id = f"{full_id}.{sub_name}"
                    results.append(build_api_item(method_id, sub_member, parent_class=member))
        elif inspect.isfunction(member):
            results.append(build_api_item(full_id, member))

    return results

def main():
    import argparse

    parser = argparse.ArgumentParser(description="提取指定 Python 包的 API 信息，并输出到 JSON。")
    parser.add_argument("--package", required=True, help="包名，例如 numpy、flask")
    parser.add_argument("--version", required=False, help="包版本，例如 2.2.5")
    parser.add_argument("--output_folder", default="API_output", help="输出 JSON 文件的目录")
    args = parser.parse_args()

    pkg_name = args.package
    pkg_ver = args.version
    output_folder = args.output_folder

    # 创建或重用虚拟环境
    venv_path = os.path.abspath(f"./temp_venv/temp_venv_{pkg_name.replace('-', '_')}")
    create_or_use_venv(venv_path)

    # 安装指定包（兼容性检查在内部处理）
    try:
        install_package_in_venv(venv_path, pkg_name, pkg_ver)
    except RuntimeError as e:
        print(f"【错误】{e}")
        sys.exit(1)

    # 将虚拟环境中的 site-packages 添加到 sys.path 以便导入
    add_venv_site_packages_to_sys_path(venv_path)

    # 定位包的 __init__.py
    pkg_spec = importlib.util.find_spec(pkg_name)
    if not pkg_spec or not pkg_spec.origin:
        raise ImportError(f"无法在虚拟环境中找到包 '{pkg_name}'。")

    init_file = pkg_spec.origin
    if not init_file or not os.path.isfile(init_file):
        raise FileNotFoundError(f"无法定位 {pkg_name} 的 __init__.py: {init_file}")
    print(f"【操作】找到 __init__.py 路径: {init_file}")

    # 1) 静态解析 __init__.py，获取其导出的符号（可能不完整）
    exported_symbols = parse_init_file(init_file)

    # 2) 将包导入后，若其设置了 __all__，则补充到 exported_symbols
    try:
        main_module = importlib.import_module(pkg_name)
    except Exception as e:
        raise ImportError(f"导入 '{pkg_name}' 出错: {e}")

    # 如果模块本身定义了 __all__，通常说明最终导出的顶层符号
    dynamic_all = getattr(main_module, '__all__', None)
    if isinstance(dynamic_all, (list, tuple, set)):
        exported_symbols.update(dynamic_all)

    print(f"【提示】最终获取到 {len(exported_symbols)} 个可能导出的符号: {exported_symbols}")

    # 3) 递归提取所有 API
    print(f"【操作】开始遍历 {pkg_name} 的 API ...")
    all_api = traverse_module(main_module)
    print(f"【完成】共收集到 {len(all_api)} 条 API 信息。")

    # 4) 标记哪些是来自 __init__.py 的导出
    #    简化规则：只要该 API 的“最后一段名称”在 exported_symbols 列表中，就认为是 from_init
    for item in all_api:
        parts = item["_id"].split(".")
        if parts[-1] in exported_symbols:
            item["from_init"] = True

    init_only_api = [i for i in all_api if i["from_init"]]

    # 输出 JSON 文件
    os.makedirs(output_folder, exist_ok=True)
    version_str = pkg_ver if pkg_ver else "latest"
    init_only_path = os.path.join(output_folder, f"{pkg_name}_{version_str}_api_init_only.json")
    all_api_path = os.path.join(output_folder, f"{pkg_name}_{version_str}_api_all.json")

    with open(init_only_path, "w", encoding="utf-8") as f:
        json.dump({"count": len(init_only_api), "data": init_only_api}, f, ensure_ascii=False, indent=4)
    print(f"【结果】init_only JSON 文件输出至: {init_only_path}")

    with open(all_api_path, "w", encoding="utf-8") as f:
        json.dump({"count": len(all_api), "data": all_api}, f, ensure_ascii=False, indent=4)
    print(f"【结果】all_api JSON 文件输出至: {all_api_path}")

if __name__ == "__main__":
    main()

# 使用示例:
# python extract_package_api.py --package numpy --version 2.2.3 --output_folder api_output