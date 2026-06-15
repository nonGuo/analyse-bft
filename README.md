# SQL加工脚本解析工具

一款用于解析DWS/GaussDB环境下SQL脚本的工具，自动提取表级与字段级血缘关系，生成标准化的Mapping文档和数据流图。

## 功能特性

- **SQL预处理**：自动过滤注释、替换调度变量、移除DWS物理层DDL
- **核心语法解析**：支持CTAS、INSERT INTO SELECT、MERGE INTO、UPDATE语句
- **CTE与子查询**：深度嵌套的WITH语句和内联子查询解析
- **血缘提取**：
  - 表级依赖关系
  - 字段级映射关系
  - 转换逻辑捕获（CASE WHEN、COALESCE、聚合函数等）
  - 别名追踪
- **产物生成**：
  - Excel Mapping文档（格式化、带筛选）
  - HTML交互式数据流图（DAG）

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 基本用法

```bash
# 解析单个SQL文件
python main.py sql/insert.sql

# 解析整个目录
python main.py sql/

# 指定输出目录
python main.py sql/ -o output/

# 使用元数据目录（用于SELECT *展开）
python main.py sql/ -m metadata/
```

### 命令行参数

- `input`：输入SQL文件路径或目录（必需）
- `-o, --output`：输出目录（默认：output）
- `-m, --metadata`：元数据目录路径（可选）
- `--excel`：Excel输出文件名（默认：lineage_mapping.xlsx）
- `--html`：HTML数据流图文件名（默认：lineage_dag.html）

## 输出示例

### Excel Mapping文档

包含以下字段：
- 目标表
- 目标字段
- 数据类型
- 源表
- 源字段
- 转换规则

### HTML数据流图

交互式DAG图，展示表级依赖关系，支持缩放和拖拽。

## 支持的SQL语法

### 已支持

- INSERT INTO ... SELECT
- CREATE TABLE ... AS SELECT
- WITH ... AS (CTE)
- JOIN (INNER, LEFT, RIGHT, FULL)
- 子查询
- NVL, COALESCE, DECODE等函数
- CASE WHEN表达式
- 聚合函数

### DWS特有语法

- 自动忽略 DISTRIBUTE BY HASH/MODULO
- 自动忽略 WITH (ORIENTATION = COLUMN/ROW)
- 调度变量替换：${TX_DATE}, $bdp.system.bizdate 等

## 元数据提供者

针对SELECT *场景，工具支持三种元数据提供者：

1. **LocalFileMetadataProvider**：从本地JSON文件读取表结构
2. **DatabaseMetadataProvider**：从DWS数据库查询系统表
3. **DummyMetadataProvider**：空实现（默认）

### 使用本地元数据

在metadata目录下创建JSON文件，文件名为表名（不含schema），内容格式：

```json
[
  {"name": "id", "type": "INTEGER"},
  {"name": "name", "type": "VARCHAR"},
  {"name": "amount", "type": "DECIMAL"}
]
```

## 项目结构

```
analyse-bft/
├── src/
│   ├── __init__.py
│   ├── models.py              # 数据模型定义
│   ├── preprocessor.py        # SQL预处理
│   ├── dws_dialect.py         # DWS自定义方言
│   ├── lineage_analyzer.py    # 血缘分析器
│   ├── metadata_provider.py   # 元数据提供者
│   ├── excel_exporter.py      # Excel导出
│   └── dag_generator.py       # 数据流图生成
├── main.py                    # 主程序入口
├── requirements.txt           # 依赖配置
├── sql/                       # 测试SQL文件
└── output/                    # 输出目录
```

## 技术栈

- **sqlglot**：SQL解析引擎
- **networkx**：图拓扑与DAG构建
- **pyecharts**：交互式数据流图
- **pandas + openpyxl**：Excel文档生成

## 示例

### 输入SQL

```sql
WITH cte_order AS (
    SELECT order_id, customer_id, NVL(amount, 0) as amount
    FROM source_db.orders
)
INSERT INTO target_db.order_summary (order_id, total_amount)
SELECT o.order_id, o.amount * 1.13
FROM cte_order o
LEFT JOIN source_db.customers c ON o.customer_id = c.customer_id;
```

### 输出

- **目标表**：target_db.order_summary
- **字段映射**：
  - order_id <- cte_order.order_id
  - total_amount <- cte_order.amount (转换: o.amount * 1.13)
- **表依赖**：
  - source_db.orders -> target_db.order_summary
  - source_db.customers -> target_db.order_summary

## 注意事项

1. 确保SQL语法符合GaussDB/PostgreSQL规范
2. 对于SELECT *场景，建议提供元数据
3. 复杂嵌套子查询可能需要人工校验
4. 输出文件使用UTF-8编码

## 许可证

MIT License
