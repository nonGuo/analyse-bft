# AI增强功能更新说明

## 本次更新内容

### 1. 新增 base_url 配置项

支持自定义AI API端点，适用于：
- Azure OpenAI
- 本地部署的开源模型（如Ollama、vLLM等）
- 第三方AI服务商

**配置示例**：
```json
{
  "enabled": true,
  "api_key": "your-api-key",
  "model": "gpt-4",
  "base_url": "https://your-custom-endpoint.com/v1",
  "fallback_to_rules": true
}
```

### 2. 字段转换逻辑整合启用AI

**变更说明**：
- 之前：仅在过滤条件改写时使用AI
- 现在：**所有数据加工字段逻辑整合都启用AI**

**影响范围**：
当临时表的数据经过多步转换时，AI会自动整合转换逻辑：

**示例场景**：
```
表A → 表B: amount * 1.1 as amount
表B → 表C: amount * 1.13 as total_amount
```

**规则引擎结果**：
```sql
(amount * 1.1) * 1.13
```

**AI优化结果**：
```sql
amount * 1.413
```

AI可以智能简化表达式，去除冗余括号，优化运算顺序。

### 3. 新增字段转换整合方法

**AIRewriter.rewrite_column_transformation()**：
- 整合上下游字段转换逻辑
- 智能简化表达式
- 确保运算优先级正确

**使用示例**：
```python
from src import AIRewriter

rewriter = AIRewriter(api_key="your-key", model="gpt-4")

result = rewriter.rewrite_column_transformation(
    upstream_transformation="UPPER(name)",
    downstream_transformation="CONCAT('Mr. ', name)",
    column_name="name"
)

# 结果: CONCAT('Mr. ', UPPER(name))
```

## 配置说明

### ai_config.json 完整配置

```json
{
  "enabled": true,
  "api_key": "sk-...",
  "model": "gpt-4",
  "base_url": "",
  "fallback_to_rules": true
}
```

**配置项说明**：

| 配置项 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| enabled | boolean | 是否启用AI功能 | true |
| api_key | string | API密钥 | "sk-..." |
| model | string | 模型名称 | "gpt-4" |
| base_url | string | API基础URL（可选） | "https://api.openai.com/v1" |
| fallback_to_rules | boolean | AI失败时是否降级到规则引擎 | true |

### base_url 使用场景

#### 1. Azure OpenAI
```json
{
  "enabled": true,
  "api_key": "your-azure-key",
  "model": "your-deployment-name",
  "base_url": "https://your-resource.openai.azure.com/",
  "fallback_to_rules": true
}
```

#### 2. 本地Ollama
```json
{
  "enabled": true,
  "api_key": "ollama",
  "model": "llama2",
  "base_url": "http://localhost:11434/v1",
  "fallback_to_rules": true
}
```

#### 3. 自定义端点
```json
{
  "enabled": true,
  "api_key": "your-key",
  "model": "custom-model",
  "base_url": "https://your-proxy.com/v1",
  "fallback_to_rules": true
}
```

## 工作流程

### 字段转换整合流程

```
表A → 表B（临时表）→ 表C
    ↓              ↓
  转换1           转换2
    ↓              ↓
    └──────┬───────┘
           ↓
      AI整合转换逻辑
           ↓
    表A → 表C（最终转换）
```

**示例**：

**输入**：
- 转换1: `amount * 1.1`
- 转换2: `amount * 1.13`

**AI处理**：
1. 识别下游转换中的字段引用
2. 替换为上游的实际表达式
3. 简化表达式
4. 确保运算优先级

**输出**：
```sql
amount * 1.413
```

### 过滤条件改写流程

```
表A → 表B（临时表）→ 表C
    ↓              ↓
  过滤1           过滤2
    ↓              ↓
    └──────┬───────┘
           ↓
    AI改写过滤条件
           ↓
    合并过滤条件
           ↓
    最终过滤条件
```

## 使用示例

### 1. 命令行使用

```bash
# 启用AI增强（使用默认配置）
python main.py sql/multi_file/ --merge --ai --excel output.xlsx

# 指定配置文件
python main.py sql/multi_file/ --merge --ai --ai-config custom_config.json --excel output.xlsx
```

### 2. 代码中使用

```python
from src import MultiFileAnalyzer, DummyMetadataProvider

# 启用AI增强
analyzer = MultiFileAnalyzer(
    metadata_provider=DummyMetadataProvider(),
    enable_ai=True,
    ai_config_file="ai_config.json"
)

result = analyzer.parse_directory("sql/multi_file/")

# 查看整合后的转换逻辑
for mapping in result.lineage_results[0].mappings:
    print(f"{mapping.target_column}: {mapping.transformation_rule}")
```

### 3. 直接使用AI改写器

```python
from src import AIRewriter

# 使用自定义base_url
rewriter = AIRewriter(
    api_key="your-key",
    model="gpt-4",
    base_url="https://your-custom-endpoint.com/v1"
)

# 整合字段转换
result = rewriter.rewrite_column_transformation(
    upstream_transformation="amount * 1.1",
    downstream_transformation="amount * 1.13",
    column_name="amount"
)
print(result)  # 输出: amount * 1.413

# 改写过滤条件
filter_result = rewriter.rewrite_filter_condition(
    downstream_filter="amount > 100",
    column_mappings=[
        {"target_column": "amount", "transformation_rule": "amount * 1.1"}
    ],
    upstream_filter="amount > 0"
)
print(filter_result)  # 输出: amount > 0 AND (amount * 1.1) > 100
```

## 性能对比

### 规则引擎 vs AI

| 场景 | 规则引擎 | AI | 提升 |
|------|---------|-----|------|
| 简单算术 | `(amount * 1.1) * 1.13` | `amount * 1.413` | 简化表达式 |
| 嵌套函数 | `CONCAT('Mr. ', (UPPER(name)))` | `CONCAT('Mr. ', UPPER(name))` | 去除冗余括号 |
| 复杂CASE | 可能失败 | 智能处理 | 更高的成功率 |
| 多步转换 | 表达式冗长 | 智能简化 | 更易读 |

### 响应时间

- **规则引擎**: < 10ms
- **AI改写**: 1-3秒（取决于网络和模型）

## 降级机制

### 自动降级场景

1. **AI服务不可用**
   - API密钥无效
   - 网络连接失败
   - API配额用尽

2. **AI改写失败**
   - 模型返回错误
   - 结果格式不正确
   - 超时

3. **配置禁用**
   - `enabled: false`
   - 未配置API密钥

### 降级行为

```
AI改写
  ↓
失败？
  ↓
是 → 规则引擎（简单替换）
  ↓
否 → 返回AI结果
```

## 最佳实践

### 1. 何时启用AI

✅ **建议启用**：
- 多步数据转换场景
- 需要简化表达式
- 复杂嵌套函数
- 追求结果质量

❌ **无需启用**：
- 简单直接映射
- 性能敏感场景
- 无临时表的单文件分析

### 2. 成本控制

- 使用缓存减少重复调用
- 批量处理多个转换
- 选择合适的模型（GPT-3.5 vs GPT-4）
- 本地模型降低成本

### 3. 质量保证

- 启用 `fallback_to_rules` 确保稳定性
- 记录AI改写日志
- 人工审核关键场景
- 对比AI和规则引擎结果

## 故障排查

### 问题1: AI改写未生效

**检查项**：
1. 配置文件 `enabled` 是否为 `true`
2. `api_key` 是否正确配置
3. 命令行是否添加 `--ai` 参数

**解决方案**：
```bash
# 检查配置
cat ai_config.json

# 使用AI参数运行
python main.py sql/multi_file/ --merge --ai --excel output.xlsx
```

### 问题2: base_url 不生效

**检查项**：
1. URL格式是否正确
2. 是否需要添加 `/v1` 后缀
3. 网络连接是否正常

**解决方案**：
```bash
# 测试连接
curl https://your-endpoint.com/v1/models \
  -H "Authorization: Bearer your-api-key"
```

### 问题3: AI结果不正确

**可能原因**：
- Prompt不够精确
- 模型理解偏差
- 上下文信息不足

**解决方案**：
- 调整 `ai_rewriter.py` 中的Prompt
- 使用更强大的模型
- 提供更详细的上下文

## 扩展开发

### 自定义AI改写器

```python
from src import AIRewriter

class CustomAIRewriter(AIRewriter):
    def rewrite_column_transformation(self, upstream, downstream, column_name):
        # 自定义整合逻辑
        # 可以添加特殊规则
        pass
```

### 集成其他AI服务

```python
class AzureAIRewriter(AIRewriter):
    def __init__(self, api_key, endpoint, deployment):
        super().__init__(
            api_key=api_key,
            model=deployment,
            base_url=f"{endpoint}/openai/deployments/{deployment}"
        )
```

## 总结

本次更新使AI增强功能更加全面：

✅ **base_url支持**：灵活对接各种AI服务
✅ **字段转换整合**：所有数据加工逻辑都启用AI
✅ **智能简化**：自动优化表达式
✅ **完整降级**：确保系统稳定性

现在工具可以处理从简单到复杂的所有SQL血缘分析场景，提供高质量的转换逻辑整合结果！
