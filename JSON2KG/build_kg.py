"""
脚本功能：
1. 从用户指定 JSON 文件中读取数据，构建 rdflib.Graph；
2. 可选地将该图谱保存为 TTL 文件；
3. 可选地使用 py2neo 将数据写入 Neo4j 图数据库，方便在 Neo4j Browser 查看可视化图。

示例用法：
    python build_kg.py --json_file ./api_output/flask_3.0.2_api_init_only.json --ttl_out ./kg/flask_graph.ttl --neo4j_url bolt://localhost:7687 --neo4j_user neo4j --neo4j_pass jc20050419 --library_name "Flask 3.0.2"
"""

import os
import sys
import json
import argparse

import rdflib
from rdflib import Graph, Namespace, RDF, RDFS, URIRef, Literal
from rdflib.namespace import XSD

from py2neo import Graph as NeoGraph, Node, Relationship


def build_knowledge_graph(json_data, library_name="MyLibrary"):
    """
    根据 JSON 数据构建本地的 rdflib.Graph，并返回 (graph, node_dicts)。
    node_dicts 可在写入 Neo4j 时重复利用。
    """
    CODE = Namespace("http://example.org/code#")

    graph = rdflib.Graph()
    graph.bind("code", CODE)

    # 声明本体（实体及关系）
    graph.add((CODE.Library, RDFS.label, Literal("Library")))
    graph.add((CODE.Script, RDFS.label, Literal("Script")))
    graph.add((CODE.Module, RDFS.label, Literal("Module")))
    graph.add((CODE.Class, RDFS.label, Literal("Class")))
    graph.add((CODE.API, RDFS.label, Literal("API")))
    graph.add((CODE.Description, RDFS.label, Literal("Description")))
    graph.add((CODE.ReturnValue, RDFS.label, Literal("ReturnValue")))
    graph.add((CODE.Parameter, RDFS.label, Literal("Parameter")))

    graph.add((CODE.hasScript, RDFS.label, Literal("has script")))
    graph.add((CODE.containModule, RDFS.label, Literal("contain module")))
    graph.add((CODE.include, RDFS.label, Literal("include")))
    graph.add((CODE.inherit, RDFS.label, Literal("inherit")))
    graph.add((CODE.hasMethod, RDFS.label, Literal("has method")))
    graph.add((CODE.hasReturnValueType, RDFS.label, Literal("has return value type")))
    graph.add((CODE.hasDescription, RDFS.label, Literal("has description")))
    graph.add((CODE.hasReturnValue, RDFS.label, Literal("has return value")))
    graph.add((CODE.hasParameter, RDFS.label, Literal("has parameter")))

    # 创建 Library 节点：库+版本（如 "Flask 2.1.0"）
    safe_library_name = library_name.replace(" ", "_")
    library_node = URIRef(f"{CODE}{safe_library_name}")
    graph.add((library_node, RDF.type, CODE.Library))
    graph.add((library_node, RDFS.label, Literal(library_name, datatype=XSD.string)))

    # 用于后续写 Neo4j 时可重用的字典
    script_map = {}
    module_map = {}
    class_map = {}
    api_map = {}

    def uri_encode(base_ns, identifier: str) -> URIRef:
        safe_id = identifier.replace("\\", "_") \
                            .replace("/", "_") \
                            .replace(" ", "_") \
                            .replace(".", "_")
        return URIRef(f"{base_ns}{safe_id}")

    data_list = json_data.get("data", [])
    for item in data_list:
        file_str = item.get("file")
        module_str = item.get("module")
        class_str = item.get("class")
        doc_str = item.get("doc")
        ret_doc = item.get("returns_doc")
        param_dict = item.get("parameters", {})
        item_type = item.get("type")
        _id = item.get("_id")  # eg: "flask.Flask.make_response"

        # 1) 处理 Script
        if file_str:
            if file_str not in script_map:
                script_node = uri_encode(CODE.Script, file_str)
                graph.add((script_node, RDF.type, CODE.Script))
                graph.add((script_node, RDFS.label, Literal(file_str, datatype=XSD.string)))
                graph.add((library_node, CODE.hasScript, script_node))
                script_map[file_str] = script_node
            else:
                script_node = script_map[file_str]
        else:
            script_node = None

        # 2) 处理 Module
        if module_str:
            if module_str not in module_map:
                mod_node = uri_encode(CODE.Module, module_str)
                graph.add((mod_node, RDF.type, CODE.Module))
                graph.add((mod_node, RDFS.label, Literal(module_str, datatype=XSD.string)))
                module_map[module_str] = mod_node
                if script_node:
                    graph.add((script_node, CODE.containModule, mod_node))
            else:
                mod_node = module_map[module_str]
        else:
            mod_node = None

        # 3) Class / API
        if item_type == "class":
            # 若没有 module 信息且特定类名是 Flask 或 App，则使用一个缺省 module
            if not module_str:
                if class_str in ("Flask", "App"):
                    module_str = "flask.app"
                else:
                    module_str = "UnknownModule"

                if module_str not in module_map:
                    mod_node = uri_encode(CODE.Module, module_str)
                    graph.add((mod_node, RDF.type, CODE.Module))
                    graph.add((mod_node, RDFS.label, Literal(module_str, datatype=XSD.string)))
                    module_map[module_str] = mod_node
                    if script_node:
                        graph.add((script_node, CODE.containModule, mod_node))
                else:
                    mod_node = module_map[module_str]

            class_node = uri_encode(CODE.Class, _id)
            graph.add((class_node, RDF.type, CODE.Class))
            graph.add((class_node, RDFS.label, Literal(_id, datatype=XSD.string)))
            class_map[_id] = class_node

            if mod_node:
                graph.add((mod_node, CODE.include, class_node))

        elif item_type in ("function", "member_function"):
            api_node = uri_encode(CODE.API, _id)
            graph.add((api_node, RDF.type, CODE.API))
            graph.add((api_node, RDFS.label, Literal(_id, datatype=XSD.string)))
            api_map[_id] = api_node

            if item_type == "member_function" and class_str:
                if class_str not in class_map:
                    parent_class_node = uri_encode(CODE.Class, class_str)
                    graph.add((parent_class_node, RDF.type, CODE.Class))
                    graph.add((parent_class_node, RDFS.label, Literal(class_str, datatype=XSD.string)))
                    class_map[class_str] = parent_class_node
                else:
                    parent_class_node = class_map[class_str]
                graph.add((parent_class_node, CODE.hasMethod, api_node))
            else:
                if mod_node:
                    graph.add((mod_node, CODE.hasMethod, api_node))

        # 4) doc 描述信息
        if doc_str:
            desc_node = uri_encode(CODE.Description, f"{_id}_desc")
            graph.add((desc_node, RDF.type, CODE.Description))
            graph.add((desc_node, RDFS.label, Literal(doc_str[:200], datatype=XSD.string)))
            if item_type in ("function", "member_function"):
                api_node = api_map.get(_id)
                if api_node:
                    graph.add((api_node, CODE.hasDescription, desc_node))
            elif item_type == "class":
                class_node = class_map.get(_id)
                if class_node:
                    graph.add((class_node, CODE.hasDescription, desc_node))

        # 5) 返回值
        if ret_doc and item_type in ("function", "member_function"):
            ret_node = uri_encode(CODE.ReturnValue, f"{_id}_ret")
            graph.add((ret_node, RDF.type, CODE.ReturnValue))
            graph.add((ret_node, RDFS.label, Literal(ret_doc, datatype=XSD.string)))
            api_node = api_map.get(_id)
            if api_node:
                graph.add((api_node, CODE.hasReturnValue, ret_node))

        # 6) 参数
        if param_dict and item_type in ("function", "member_function"):
            api_node = api_map.get(_id)
            if api_node:
                for p_name, p_info in param_dict.items():
                    # 先从 p_info 中获取实际参数名，否则回退到字典键 p_name
                    real_param_name = p_info.get("name", p_name)
                    param_node = uri_encode(CODE.Parameter, f"{_id}_{real_param_name}")
                    graph.add((param_node, RDF.type, CODE.Parameter))
                    label_str = f"{real_param_name} (optional={p_info.get('is_optional', False)})"
                    graph.add((param_node, RDFS.label, Literal(label_str, datatype=XSD.string)))
                    graph.add((api_node, CODE.hasParameter, param_node))

    node_dicts = {
        "library_name": library_name,
        "script_map": script_map,
        "module_map": module_map,
        "class_map": class_map,
        "api_map": api_map
    }
    return graph, node_dicts


def write_to_neo4j_py2neo(node_dicts, json_data, neo4j_url, neo4j_user, neo4j_pass):
    """
    使用 py2neo 将解析后的数据合并(MERGE)到 Neo4j。
    在 Neo4j Browser 中浏览节点和关系图即可实现可视化。
    """
    print(f"[提示] 正在通过 py2neo 连接至 Neo4j: {neo4j_url}")
    neo_graph = NeoGraph(neo4j_url, auth=(neo4j_user, neo4j_pass))

    # 使用 node_dicts 中传入的 library_name
    library_name = node_dicts["library_name"]
    # 尝试查询是否已存在 Library 节点（根据 name 唯一）
    existing_library = neo_graph.nodes.match("Library", name=library_name).first()
    if existing_library:
        library_node = existing_library
    else:
        library_node = Node("Library", name=library_name)
        neo_graph.create(library_node)

    data_list = json_data.get("data", [])

    for item in data_list:
        file_str = item.get("file")
        module_str = item.get("module")
        class_str = item.get("class")
        doc_str = item.get("doc")
        ret_doc = item.get("returns_doc")
        param_dict = item.get("parameters", {})
        item_type = item.get("type")
        _id = item.get("_id")

        # 1) Script Node
        script_node = None
        if file_str:
            script_node = Node("Script", name=file_str)
            neo_graph.merge(script_node, "Script", "name")
            rel = Relationship(library_node, "HAS_SCRIPT", script_node)
            neo_graph.merge(rel)

        # 2) Module Node
        module_node = None
        if module_str:
            module_node = Node("Module", name=module_str)
            neo_graph.merge(module_node, "Module", "name")
            if script_node:
                rel = Relationship(script_node, "CONTAIN_MODULE", module_node)
                neo_graph.merge(rel)

        # 3) Class / API处理
        if item_type == "class":
            # 若没有 module 信息且类名是 Flask 或 App，则使用一个缺省 module
            if not module_str:
                if class_str in ("Flask", "App"):
                    module_str = "flask.app"
                else:
                    module_str = "UnknownModule"

                module_node = Node("Module", name=module_str)
                neo_graph.merge(module_node, "Module", "name")
                if script_node:
                    rel = Relationship(script_node, "CONTAIN_MODULE", module_node)
                    neo_graph.merge(rel)

            class_node = Node("Class", name=_id)
            neo_graph.merge(class_node, "Class", "name")
            if module_node:
                rel = Relationship(module_node, "INCLUDE", class_node)
                neo_graph.merge(rel)

            # doc 描述信息
            if doc_str:
                desc_node = Node("Description", name=f"{_id}_desc", content=doc_str)
                neo_graph.merge(desc_node, "Description", "name")
                rel = Relationship(class_node, "HAS_DESCRIPTION", desc_node)
                neo_graph.merge(rel)

        elif item_type in ("function", "member_function"):
            api_node = Node("API", name=_id)
            neo_graph.merge(api_node, "API", "name")

            if item_type == "member_function" and class_str:
                parent_class_node = Node("Class", name=class_str)
                neo_graph.merge(parent_class_node, "Class", "name")
                rel = Relationship(parent_class_node, "HAS_METHOD", api_node)
                neo_graph.merge(rel)
            else:
                if module_node:
                    rel = Relationship(module_node, "HAS_METHOD", api_node)
                    neo_graph.merge(rel)

            if doc_str:
                desc_node = Node("Description", name=f"{_id}_desc", content=doc_str)
                neo_graph.merge(desc_node, "Description", "name")
                rel = Relationship(api_node, "HAS_DESCRIPTION", desc_node)
                neo_graph.merge(rel)

            if ret_doc:
                ret_node = Node("ReturnValue", name=f"{_id}_ret", content=ret_doc)
                neo_graph.merge(ret_node, "ReturnValue", "name")
                rel = Relationship(api_node, "HAS_RETURN_VALUE", ret_node)
                neo_graph.merge(rel)

            if param_dict:
                for p_name, p_info in param_dict.items():
                    real_param_name = p_info.get("name", p_name)
                    param_node = Node(
                        "Parameter",
                        name=f"{_id}_{real_param_name}",
                        optional=p_info.get("is_optional", False)
                    )
                    neo_graph.merge(param_node, "Parameter", "name")
                    rel = Relationship(api_node, "HAS_PARAMETER", param_node)
                    neo_graph.merge(rel)

    print("[提示] 数据已成功写入 (MERGE) 到 Neo4j。可在 Neo4j Browser 中查看。")


def main():
    parser = argparse.ArgumentParser(
        description="从 JSON 文件构建知识图谱 (TTL + py2neo/Neo4j)"
    )
    parser.add_argument("--json_file", required=True, help="输入的 JSON 文件路径")
    parser.add_argument("--ttl_out", help="可选，输出 .ttl 文件路径")
    parser.add_argument("--library_name", default="MyLibrary", help="Library 节点名称: 如 'Flask 2.1.0'")
    # py2neo / Neo4j相关参数
    parser.add_argument("--neo4j_url", help="如: bolt://localhost:7687")
    parser.add_argument("--neo4j_user", help="Neo4j 用户名", default=None)
    parser.add_argument("--neo4j_pass", help="Neo4j 密码", default=None)

    args = parser.parse_args()

    json_file = args.json_file
    ttl_out = args.ttl_out
    library_name = args.library_name
    neo4j_url = args.neo4j_url
    neo4j_user = args.neo4j_user
    neo4j_pass = args.neo4j_pass

    if not os.path.isfile(json_file):
        print(f"[错误] 无法找到 JSON 文件: {json_file}")
        sys.exit(1)

    # 读取 JSON
    with open(json_file, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    # 1) rdflib 构建本地图谱
    kg, node_dicts = build_knowledge_graph(json_data, library_name=library_name)

    # 2) 如果指定 ttl_out，则保存 TTL
    if ttl_out:
        ttl_dir = os.path.dirname(ttl_out)
        if ttl_dir and not os.path.exists(ttl_dir):
            os.makedirs(ttl_dir, exist_ok=True)
        kg.serialize(destination=ttl_out, format="turtle")
        print(f"[完成] RDF Graph 已保存为 TTL 文件: {ttl_out}")

    # 3) 如果提供 Neo4j 参数，使用 py2neo 写入到 Neo4j
    if neo4j_url and neo4j_user and neo4j_pass:
        write_to_neo4j_py2neo(node_dicts, json_data, neo4j_url, neo4j_user, neo4j_pass)


if __name__ == "__main__":
    main()
