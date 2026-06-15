import networkx as nx
from pyecharts import options as opts
from pyecharts.charts import Graph
from .models import ParseResult


def generate_dag(parse_result: ParseResult) -> nx.DiGraph:
    G = nx.DiGraph()

    for lineage in parse_result.lineage_results:
        for dep in lineage.dependencies:
            G.add_edge(dep.source_table, dep.target_table)

    return G


def export_to_html(parse_result: ParseResult, output_path: str):
    G = generate_dag(parse_result)

    if len(G.nodes) == 0:
        _generate_empty_html(output_path)
        return

    nodes = []
    for node in G.nodes:
        category = _get_node_category(node, G)
        nodes.append(
            opts.GraphNode(
                name=node,
                symbol_size=40,
                category=category,
                itemstyle_opts=opts.ItemStyleOpts(
                    color=_get_node_color(category)
                )
            )
        )

    links = []
    for source, target in G.edges:
        links.append(
            opts.GraphLink(
                source=source,
                target=target,
                linestyle_opts=opts.LineStyleOpts(curve=0.3)
            )
        )

    categories = [
        opts.GraphCategory(name="Source"),
        opts.GraphCategory(name="Target"),
        opts.GraphCategory(name="Intermediate"),
    ]

    graph = (
        Graph(init_opts=opts.InitOpts(width="1200px", height="800px"))
        .add(
            "",
            nodes=nodes,
            links=links,
            categories=categories,
            repulsion=300,
            edge_length=[150, 250],
            gravity=0.1,
            layout="force",
            is_rotate_label=True,
            linestyle_opts=opts.LineStyleOpts(color="source"),
            label_opts=opts.LabelOpts(is_show=True, position="right", font_size=12),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="数据血缘关系图", subtitle="SQL Lineage DAG"),
            legend_opts=opts.LegendOpts(orient="vertical", pos_left="left"),
        )
    )

    graph.render(output_path)


def _get_node_category(node: str, G: nx.DiGraph) -> int:
    in_degree = G.in_degree(node)
    out_degree = G.out_degree(node)

    if in_degree == 0 and out_degree > 0:
        return 0
    elif in_degree > 0 and out_degree == 0:
        return 1
    else:
        return 2


def _get_node_color(category: int) -> str:
    colors = ["#5470c6", "#91cc75", "#fac858"]
    return colors[category % len(colors)]


def _generate_empty_html(output_path: str):
    html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>数据血缘关系图</title>
    <style>
        body { font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #f5f5f5; }
        .container { text-align: center; padding: 40px; background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        h1 { color: #333; }
        p { color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <h1>数据血缘关系图</h1>
        <p>未检测到表级依赖关系</p>
    </div>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
