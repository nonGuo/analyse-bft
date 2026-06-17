import html
from collections import defaultdict, deque
import networkx as nx
from .models import ParseResult


GROUP_COLORS = [
    "#4e79a7", "#59a14f", "#e15759", "#f28e2b", "#b07aa1",
    "#edc948", "#76b7b2", "#ff9da7", "#9c755f", "#bab0ac",
]

NODE_TYPE_COLORS = {
    "source": "#4e79a7",
    "target": "#59a14f",
    "intermediate": "#f28e2b",
}


def generate_dag(parse_result: ParseResult) -> nx.DiGraph:
    G = nx.DiGraph()

    for lineage in parse_result.lineage_results:
        for dep in lineage.dependencies:
            G.add_edge(dep.source_table, dep.target_table)

    return G


def _normalize_node_name(name: str) -> str:
    return name.strip()


def _build_deduplicated_dag(parse_result: ParseResult) -> nx.DiGraph:
    G = nx.DiGraph()
    node_aliases: dict[str, str] = {}

    for lineage in parse_result.lineage_results:
        for dep in lineage.dependencies:
            src = _normalize_node_name(dep.source_table)
            tgt = _normalize_node_name(dep.target_table)

            src_key = src.lower()
            tgt_key = tgt.lower()

            if src_key not in node_aliases:
                node_aliases[src_key] = src
            if tgt_key not in node_aliases:
                node_aliases[tgt_key] = tgt

            canonical_src = node_aliases[src_key]
            canonical_tgt = node_aliases[tgt_key]

            if canonical_src != canonical_tgt:
                G.add_edge(canonical_src, canonical_tgt)

    return G


def _assign_layers(G: nx.DiGraph) -> dict[str, int]:
    if len(G.nodes) == 0:
        return {}

    in_degree = {n: G.in_degree(n) for n in G.nodes}
    queue = deque([n for n in G.nodes if in_degree[n] == 0])

    layers = {}
    for n in G.nodes:
        layers[n] = 0

    topo_order = []
    while queue:
        node = queue.popleft()
        topo_order.append(node)
        for succ in G.successors(node):
            layers[succ] = max(layers[succ], layers[node] + 1)
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    for node in G.nodes:
        if node not in [n for n in topo_order]:
            layers[node] = 0

    if not topo_order:
        for i, node in enumerate(G.nodes):
            layers[node] = i
        return layers

    max_layer = max(layers.values()) if layers else 0

    for node in G.nodes:
        if G.out_degree(node) == 0 and G.in_degree(node) > 0:
            layers[node] = max_layer

    return layers


def _order_within_layers(G: nx.DiGraph, layers: dict[str, int]) -> dict[int, list[str]]:
    layer_groups: dict[int, list[str]] = defaultdict(list)
    for node, layer in layers.items():
        layer_groups[layer].append(node)

    for layer in layer_groups:
        layer_groups[layer].sort()

    max_layer = max(layer_groups.keys()) if layer_groups else 0

    for _ in range(3):
        for layer_idx in range(1, max_layer + 1):
            if layer_idx not in layer_groups:
                continue
            prev_layer = layer_groups.get(layer_idx - 1, [])
            prev_pos = {n: i for i, n in enumerate(prev_layer)}

            def barycenter(node):
                preds = [p for p in G.predecessors(node) if p in prev_pos]
                if not preds:
                    return len(prev_layer)
                return sum(prev_pos[p] for p in preds) / len(preds)

            layer_groups[layer_idx].sort(key=barycenter)

        for layer_idx in range(max_layer - 1, -1, -1):
            if layer_idx not in layer_groups:
                continue
            next_layer = layer_groups.get(layer_idx + 1, [])
            next_pos = {n: i for i, n in enumerate(next_layer)}

            def barycenter_down(node):
                succs = [s for s in G.successors(node) if s in next_pos]
                if not succs:
                    return len(next_layer)
                return sum(next_pos[s] for s in succs) / len(succs)

            layer_groups[layer_idx].sort(key=barycenter_down)

    return dict(layer_groups)


def _get_node_category(node: str, G: nx.DiGraph) -> str:
    in_deg = G.in_degree(node)
    out_deg = G.out_degree(node)
    if in_deg == 0 and out_deg > 0:
        return "source"
    elif in_deg > 0 and out_deg == 0:
        return "target"
    else:
        return "intermediate"


def _get_node_group(node: str, parse_result: ParseResult) -> int | None:
    for lineage in parse_result.lineage_results:
        for tl in lineage.table_lineages:
            full_source = f"{tl.source_schema}.{tl.source_table}" if tl.source_schema else tl.source_table
            full_target = f"{tl.target_schema}.{tl.target_table}" if tl.target_schema else tl.target_table
            if node == full_source or node == full_target or node == tl.source_table or node == tl.target_table:
                if tl.group_id and tl.group_id > 1:
                    return tl.group_id
    return None


def _compute_layout(G: nx.DiGraph, parse_result: ParseResult):
    layers = _assign_layers(G)
    layer_groups = _order_within_layers(G, layers)

    node_width = 180
    node_height = 44
    h_spacing = 260
    v_spacing = 70
    margin_x = 80
    margin_y = 60

    max_nodes_in_layer = max(len(v) for v in layer_groups.values()) if layer_groups else 1
    canvas_height = max(400, max_nodes_in_layer * (node_height + v_spacing) + margin_y * 2)
    num_layers = (max(layer_groups.keys()) + 1) if layer_groups else 1
    canvas_width = max(800, num_layers * h_spacing + margin_x * 2 + node_width)

    node_positions = {}
    for layer_idx, nodes in sorted(layer_groups.items()):
        x = margin_x + layer_idx * h_spacing
        total_height = len(nodes) * node_height + (len(nodes) - 1) * v_spacing
        start_y = (canvas_height - total_height) / 2
        for i, node in enumerate(nodes):
            y = start_y + i * (node_height + v_spacing)
            node_positions[node] = (x, y)

    return node_positions, node_width, node_height, canvas_width, canvas_height


def _edge_path(x1, y1, x2, y2, node_width, node_height):
    sx = x1 + node_width
    sy = y1 + node_height / 2
    tx = x2
    ty = y2 + node_height / 2

    dx = tx - sx
    cp_offset = max(40, abs(dx) * 0.4)

    cp1x = sx + cp_offset
    cp1y = sy
    cp2x = tx - cp_offset
    cp2y = ty

    return f"M{sx},{sy} C{cp1x},{cp1y} {cp2x},{cp2y} {tx},{ty}"


def export_to_html(parse_result: ParseResult, output_path: str):
    G = _build_deduplicated_dag(parse_result)

    if len(G.nodes) == 0:
        _generate_empty_html(output_path)
        return

    node_positions, node_width, node_height, canvas_width, canvas_height = _compute_layout(G, parse_result)

    group_color_map = {}
    for node in G.nodes:
        gid = _get_node_group(node, parse_result)
        if gid is not None and gid > 1:
            group_color_map[node] = GROUP_COLORS[(gid - 1) % len(GROUP_COLORS)]

    edges_svg = []
    for source, target in G.edges:
        if source in node_positions and target in node_positions:
            sx, sy = node_positions[source]
            tx, ty = node_positions[target]
            path = _edge_path(sx, sy, tx, ty, node_width, node_height)

            source_cat = _get_node_category(source, G)
            edge_color = group_color_map.get(source, NODE_TYPE_COLORS.get(source_cat, "#999"))

            edges_svg.append(
                f'<path d="{path}" fill="none" stroke="{edge_color}" '
                f'stroke-width="2" stroke-opacity="0.6" '
                f'marker-end="url(#arrowhead)"/>'
            )

    nodes_svg = []
    for node in G.nodes:
        if node not in node_positions:
            continue
        x, y = node_positions[node]
        category = _get_node_category(node, G)

        color = group_color_map.get(node, NODE_TYPE_COLORS.get(category, "#999"))

        label = node
        escaped_label = html.escape(label)
        display_label = escaped_label
        max_chars = 22
        if len(escaped_label) > max_chars:
            display_label = escaped_label[:max_chars - 1] + "\u2026"

        tooltip_text = escaped_label

        in_deg = G.in_degree(node)
        out_deg = G.out_degree(node)
        tooltip_detail = f"In: {in_deg} / Out: {out_deg}"

        rx = 8
        nodes_svg.append(f'''<g class="node" data-tooltip="{tooltip_text} ({tooltip_detail})">
  <rect x="{x}" y="{y}" width="{node_width}" height="{node_height}" rx="{rx}" ry="{rx}"
        fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-width="2"/>
  <rect x="{x}" y="{y}" width="6" height="{node_height}" rx="3" ry="0" fill="{color}"/>
  <text x="{x + 16}" y="{y + node_height / 2 + 1}" dominant-baseline="middle"
        font-family="'SF Pro Text', 'Segoe UI', system-ui, -apple-system, sans-serif"
        font-size="13" font-weight="500" fill="#1a1a2e">{display_label}</text>
</g>''')

    legend_items = [
        ("Source (only outgoing)", NODE_TYPE_COLORS["source"]),
        ("Target (only incoming)", NODE_TYPE_COLORS["target"]),
        ("Intermediate", NODE_TYPE_COLORS["intermediate"]),
    ]
    legend_svg = []
    for i, (label, color) in enumerate(legend_items):
        lx = 20
        ly = canvas_height - 90 + i * 24
        legend_svg.append(
            f'<rect x="{lx}" y="{ly}" width="14" height="14" rx="3" fill="{color}" fill-opacity="0.7"/>'
            f'<text x="{lx + 20}" y="{ly + 11}" font-size="12" '
            f'font-family="\'SF Pro Text\', \'Segoe UI\', system-ui, sans-serif" '
            f'fill="#555">{label}</text>'
        )

    group_legend_items = []
    seen_groups = set()
    for node, color in group_color_map.items():
        gid = _get_node_group(node, parse_result)
        if gid and gid not in seen_groups:
            seen_groups.add(gid)
            group_legend_items.append((f"Group {gid}", color))

    if group_legend_items:
        offset = len(legend_items)
        for i, (label, color) in enumerate(group_legend_items):
            lx = 20
            ly = canvas_height - 90 + (offset + i) * 24
            legend_svg.append(
                f'<rect x="{lx}" y="{ly}" width="14" height="14" rx="3" fill="{color}" fill-opacity="0.7"/>'
                f'<text x="{lx + 20}" y="{ly + 11}" font-size="12" '
                f'font-family="\'SF Pro Text\', \'Segoe UI\', system-ui, sans-serif" '
                f'fill="#555">{label}</text>'
            )

    edges_block = "\n    ".join(edges_svg)
    nodes_block = "\n    ".join(nodes_svg)
    legend_block = "\n    ".join(legend_svg)

    total_nodes = len(G.nodes)
    total_edges = len(G.edges)

    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SQL Lineage DAG</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'SF Pro Text', 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: #f0f2f5;
  color: #1a1a2e;
}}
.header {{
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  color: white;
  padding: 20px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}}
.header h1 {{ font-size: 20px; font-weight: 600; letter-spacing: 0.3px; }}
.header .stats {{
  display: flex;
  gap: 24px;
  font-size: 13px;
  opacity: 0.85;
}}
.header .stat-value {{ font-weight: 700; margin-right: 4px; }}
.canvas-wrap {{
  padding: 24px;
  overflow: auto;
}}
.canvas-inner {{
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.04);
  padding: 16px;
  display: inline-block;
  min-width: 100%;
}}
svg {{
  display: block;
}}
.node {{ cursor: pointer; }}
.node rect {{
  transition: fill-opacity 0.15s, stroke-width 0.15s;
}}
.node:hover rect {{
  fill-opacity: 0.25;
  stroke-width: 3;
}}
.node:hover text {{
  font-weight: 700;
}}
.tooltip {{
  position: fixed;
  background: #1a1a2e;
  color: white;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.15s;
  z-index: 100;
  max-width: 400px;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0,0,0,0.2);
}}
</style>
</head>
<body>

<div class="header">
  <h1>SQL Lineage DAG</h1>
  <div class="stats">
    <span><span class="stat-value">{total_nodes}</span>tables</span>
    <span><span class="stat-value">{total_edges}</span>dependencies</span>
  </div>
</div>

<div class="canvas-wrap">
  <div class="canvas-inner">
    <svg width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}">
      <defs>
        <marker id="arrowhead" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L10,4 L0,8 L2,4 Z" fill="#888"/>
        </marker>
      </defs>

      <g class="edges">
        {edges_block}
      </g>

      <g class="nodes">
        {nodes_block}
      </g>

      <g class="legend">
        {legend_block}
      </g>
    </svg>
  </div>
</div>

<div class="tooltip" id="tooltip"></div>

<script>
(function() {{
  const tooltip = document.getElementById('tooltip');
  document.querySelectorAll('.node').forEach(node => {{
    node.addEventListener('mouseenter', e => {{
      const text = node.getAttribute('data-tooltip');
      tooltip.textContent = text;
      tooltip.style.opacity = '1';
    }});
    node.addEventListener('mousemove', e => {{
      tooltip.style.left = (e.clientX + 14) + 'px';
      tooltip.style.top = (e.clientY - 10) + 'px';
    }});
    node.addEventListener('mouseleave', () => {{
      tooltip.style.opacity = '0';
    }});
  }});
}})();
</script>

</body>
</html>'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)


def _generate_empty_html(output_path: str):
    html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>SQL Lineage DAG</title>
    <style>
        body { font-family: 'SF Pro Text', 'Segoe UI', system-ui, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #f0f2f5; }
        .container { text-align: center; padding: 48px; background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.04); }
        h1 { color: #1a1a2e; font-size: 20px; margin-bottom: 8px; }
        p { color: #666; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>SQL Lineage DAG</h1>
        <p>No table dependencies detected</p>
    </div>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
