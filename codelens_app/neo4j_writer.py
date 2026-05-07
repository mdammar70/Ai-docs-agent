from neo4j import GraphDatabase


def resolve_calls(all_functions: dict) -> tuple[list, list]:
    name_index = {}
    for node_id, fn in all_functions.items():
        name_index.setdefault(fn["name"], []).append(node_id)

    resolved = []
    external = []

    for node_id, fn in all_functions.items():
        for raw_call in fn["calls"]:
            call_name = raw_call.split(".")[-1]
            candidates = name_index.get(call_name, [])

            if not candidates:
                external.append({"from": node_id, "raw_call": raw_call})
                continue

            same_file = [c for c in candidates if fn["file"] in c]
            target = same_file[0] if same_file else candidates[0]

            if target != node_id:
                resolved.append({"from": node_id, "to": target})

    seen = set()
    unique_resolved = []
    for e in resolved:
        key = (e["from"], e["to"])
        if key not in seen:
            seen.add(key)
            unique_resolved.append(e)

    return unique_resolved, external


class Neo4jWriter:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def run(self, cypher, **params):
        with self.driver.session() as s:
            s.run(cypher, **params)

    def close(self):
        self.driver.close()

    def clear(self):
        self.run("MATCH (n) DETACH DELETE n")

    def create_indexes(self):
        for cypher in [
            "CREATE INDEX fn_name  IF NOT EXISTS FOR (f:Function) ON (f.name)",
            "CREATE INDEX fn_file  IF NOT EXISTS FOR (f:Function) ON (f.file)",
            "CREATE INDEX cls_name IF NOT EXISTS FOR (c:Class)    ON (c.name)",
            "CREATE INDEX fi_path  IF NOT EXISTS FOR (f:File)     ON (f.path)",
        ]:
            self.run(cypher)

    def write_files(self, all_functions, all_classes):
        files = set()
        for fn in all_functions.values():
            files.add(fn["file"])
        for cls in all_classes.values():
            files.add(cls["file"])
        self.run(
            "UNWIND $files AS path MERGE (f:File {path: path})",
            files=list(files),
        )
        return len(files)

    def write_classes(self, all_classes):
        nodes = list(all_classes.values())
        self.run("""
            UNWIND $nodes AS node
            MERGE (c:Class {id: node.id})
            SET c.name       = node.name,
                c.file       = node.file,
                c.start_line = node.start_line,
                c.end_line   = node.end_line,
                c.bases      = node.bases
            WITH c, node
            MATCH (f:File {path: node.file})
            MERGE (c)-[:DEFINED_IN]->(f)
        """, nodes=nodes)
        return len(nodes)

    def write_functions(self, all_functions):
        nodes = list(all_functions.values())
        self.run("""
            UNWIND $nodes AS node
            MERGE (f:Function {id: node.id})
            SET f.name        = node.name,
                f.file        = node.file,
                f.class_name  = node.class_name,
                f.start_line  = node.start_line,
                f.end_line    = node.end_line,
                f.docstring   = node.docstring,
                f.params      = node.params,
                f.return_type = node.return_type,
                f.is_async    = node.is_async,
                f.source      = node.source
            WITH f, node
            MATCH (fi:File {path: node.file})
            MERGE (f)-[:DEFINED_IN]->(fi)
        """, nodes=nodes)

        methods = [n for n in nodes if n.get("class_name")]
        if methods:
            self.run("""
                UNWIND $methods AS m
                MATCH (f:Function {id: m.id})
                MATCH (c:Class {name: m.class_name, file: m.file})
                MERGE (f)-[:BELONGS_TO]->(c)
            """, methods=methods)

        return len(nodes), len(methods)

    def write_calls(self, resolved_edges):
        if not resolved_edges:
            return 0
        self.run("""
            UNWIND $edges AS edge
            MATCH (a:Function {id: edge.from})
            MATCH (b:Function {id: edge.to})
            MERGE (a)-[:CALLS]->(b)
        """, edges=resolved_edges)
        return len(resolved_edges)

    def write_external_calls(self, external_edges):
        if not external_edges:
            return 0
        self.run("""
            UNWIND $edges AS edge
            MERGE (lib:ExternalLib {name: edge.raw_call})
            WITH lib, edge
            MATCH (f:Function {id: edge.from})
            MERGE (f)-[:CALLS_EXTERNAL]->(lib)
        """, edges=external_edges)
        return len(external_edges)

    def write_inheritance(self, all_classes):
        name_index = {cls["name"]: cls["id"] for cls in all_classes.values()}
        inh_edges = [
            {"child_id": cls["id"], "parent_id": name_index[base]}
            for cls in all_classes.values()
            for base in cls.get("bases", [])
            if base in name_index
        ]
        if inh_edges:
            self.run("""
                UNWIND $edges AS edge
                MATCH (child:Class  {id: edge.child_id})
                MATCH (parent:Class {id: edge.parent_id})
                MERGE (child)-[:INHERITS]->(parent)
            """, edges=inh_edges)
        return len(inh_edges)

    def write_imports(self, all_imports, all_files_set):
        module_to_file = {}
        for f in all_files_set:
            module_key = f.replace("/", ".").replace(".py", "")
            module_to_file[module_key] = f

        import_edges = []
        for imp in all_imports:
            target_file = module_to_file.get(imp["module"])
            if target_file and target_file != imp["from_file"]:
                import_edges.append({
                    "from_file": imp["from_file"],
                    "to_file": target_file,
                    "names": ", ".join(imp["names"]) if imp["names"] else "",
                })

        if import_edges:
            self.run("""
                UNWIND $edges AS edge
                MATCH (a:File {path: edge.from_file})
                MATCH (b:File {path: edge.to_file})
                MERGE (a)-[:IMPORTS {names: edge.names}]->(b)
            """, edges=import_edges)
        return len(import_edges)


def ingest_to_neo4j(uri, user, password, all_functions, all_classes, all_imports):
    resolved_edges, external_edges = resolve_calls(all_functions)

    all_file_paths = set()
    for fn in all_functions.values():
        all_file_paths.add(fn["file"])
    for cls in all_classes.values():
        all_file_paths.add(cls["file"])

    writer = Neo4jWriter(uri, user, password)

    writer.clear()
    print("  DB cleared")

    writer.create_indexes()
    print("  Indexes created")

    fc = writer.write_files(all_functions, all_classes)
    print(f"  File nodes     : {fc}")

    cc = writer.write_classes(all_classes)
    print(f"  Class nodes    : {cc}")

    fn_count, method_count = writer.write_functions(all_functions)
    print(f"  Function nodes : {fn_count}  ({method_count} methods)")

    rc = writer.write_calls(resolved_edges)
    print(f"  CALLS edges    : {rc}")

    ec = writer.write_external_calls(external_edges)
    print(f"  EXTERNAL edges : {ec}")

    ic = writer.write_inheritance(all_classes)
    print(f"  INHERITS edges : {ic}")

    imc = writer.write_imports(all_imports, all_file_paths)
    print(f"  IMPORTS edges  : {imc}")

    writer.close()

    return {
        "files": fc,
        "classes": cc,
        "functions": fn_count,
        "calls": rc,
        "external": ec,
        "inherits": ic,
        "imports": imc,
    }
