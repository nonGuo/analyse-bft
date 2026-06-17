import networkx as nx
from pyecharts import options as opts
from pyecharts.charts import Graph
from .models import ParseResult, ProcessingScenario


SCENARIO_COLORS = [
    "#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de",
    "#3ba272", "#fc8452", "#9a60b4", "#ea7ccc", "#48b8d0",
]
SHARED_COLOR = "#999999"


def generate_dag(parse_result: ParseResult) -> nx.DiGraph:
    G = nx.DiGraph()

    for lineage in parse_result.lineage_results:
        for dep in lineage.dependencies:
            G.add_edge(dep.source_table, dep.target_table)
        for mapping in lineage.mappings:
            if mapping.scenario.discriminator_value:
                for src_table in mapping.source_tables:
                    G.add_edge(src_table, mapping.target_table)

    return G


def export_to_html(parse_result: ParseResult, output_path: str):
    G = generate_dag(parse_result)

    if len(G.nodes) == 0:
        _generate_empty_html(output_path)
        return

    scenario_index = _build_scenario_index(parse_result)

    nodes = []
    for node in G.nodes:
        category, color = _get_node_style(node, G, parse_result, scenario_index)
        label = _get_node_label(node, parse_result)
        nodes.append(
            opts.GraphNode(
                name=node,
                symbol_size=40,
                category=category,
                label_opts=opts.LabelOpts(is_show=True, position="right", font_size=12, formatter=label),
                itemstyle_opts=opts.ItemStyleOpts(color=color)
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

    legend_items = []
    for scenario_label, color in sorted(scenario_index.items()):
        legend_items.append(opts.GraphCategory(name=scenario_label))

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


def _build_scenario_index(parse_result: ParseResult) -> dict[str, str]:
    index: dict[str, str] = {}
    color_idx = 0
    for lineage in parse_result.lineage_results:
        for mapping in lineage.mappings:
            s = mapping.scenario
            if s.discriminator_value:
                label = s.label
                if label not in index:
                    index[label] = SCENARIO_COLORS[color_idx % len(SCENARIO_COLORS)]
                    color_idx += 1
    return index


def _get_node_style(node: str, G: nx.DiGraph, parse_result: ParseResult, scenario_index: dict) -> tuple[int, str]:
    in_degree = G.in_degree(node)
    out_degree = G.out_degree(node)

    if in_degree == 0 and out_degree > 0:
        category = 0
        default_color = "#5470c6"
    elif in_degree > 0 and out_degree == 0:
        category = 1
        default_color = "#91cc75"
    else:
        category = 2
        default_color = "#fac858"

    node_scenarios = set()
    for lineage in parse_result.lineage_results:
        for mapping in lineage.mappings:
            if mapping.target_table == node or node in mapping.source_tables:
                if mapping.scenario.discriminator_value:
                    node_scenarios.add(mapping.scenario.label)
                elif mapping.scenario.is_shared:
                    node_scenarios.add("(公共)")
        for tl in lineage.table_lineages:
            full_target = f"{tl.target_schema}.{tl.target_table}" if tl.target_schema else tl.target_table
            full_source = f"{tl.source_schema}.{tl.source_table}" if tl.source_schema else tl.source_table
            if full_target == node or full_source == node or tl.source_table == node:
                if tl.scenario.discriminator_value:
                    node_scenarios.add(tl.scenario.label)

    if len(node_scenarios) == 1:
        label = node_scenarios.pop()
        if label in scenario_index:
            return category, scenario_index[label]
        if label == "(公共)":
            return category, SHARED_COLOR

    if len(node_scenarios) > 1:
        return category, "#ffffff"

    return category, default_color


def _get_node_label(node: str, parse_result: ParseResult) -> str:
    scenarios = set()
    for lineage in parse_result.lineage_results:
        for mapping in lineage.mappings:
            if mapping.target_table == node or node in mapping.source_tables:
                if mapping.scenario.label:
                    scenarios.add(mapping.scenario.label)

    if scenarios:
        return f"{node}\n[{', '.join(sorted(scenarios))}]"
    return node


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
