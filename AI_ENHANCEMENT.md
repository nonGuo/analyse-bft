# AI增强功能使用指南

## 功能概述

AI增强功能用于处理规则引擎无法覆盖的复杂SQL改写场景，包括：

- **复杂过滤条件**：包含CASE WHEN、嵌套函数、子查询等
- **多步转换**：列经过多次复杂转换后的过滤条件改写
- **语义理解**：基于SQL语义的智能改写

## 配置方法

### 1. 安装依赖

```bash
pip install openai
```

### 2. 配置API密钥

编辑 `ai_config.json` 文件：

```json
{
  "enabled": true,
  "api_key": "your-openai-api-key-here",
  "model": "gpt-4",
  "fallback_to_rules": true
}
```

或者设置环境变量：

```bash
export OPENAI_API_KEY="your-openai-api-key-here"
```

### 3. 使用方式

#### 方式一：命令行启用AI

```bash
python main.py sql/multi_file_complex/ --merge --ai --excel output.xlsx
```

#### 方式二：在代码中使用

```python
from src import MultiFileAnalyzer, DummyMetadataProvider

# 启用AI增强
analyzer = MultiFileAnalyzer(
    metadata_provider=DummyMetadataProvider(),
    enable_ai=True,
    ai_config_file="ai_config.json"
)

result = analyzer.parse_directory("sql/multi_file_complex/")
```

## 工作原理

### 1. 复杂度检测

系统会自动检测过滤条件的复杂度：

**复杂场景指标**：
- 包含 `CASE WHEN`、`EXISTS`、`IN`、`BETWEEN` 等关键字
- 包含嵌套函数调用（如 `COALESCE(CASE WHEN ... END, 0)`）
- 转换逻辑包含多个运算符
- 包含日期函数、字符串函数等

### 2. AI改写流程

```
下游过滤条件 (基于表B)
    ↓
识别列引用
    ↓
查找列转换逻辑 (表A -> 表B)
    ↓
AI理解语义并重写
    ↓
与上游过滤条件合并
    ↓
最终过滤条件 (基于表A)
```

### 3. 降级机制

如果AI改写失败，系统会自动降级到规则引擎：

```
AI改写 → 失败 → 规则引擎 → 简单替换
```

## 示例对比

### 简单场景（规则引擎处理）

**输入**：
- A→B: `amount * 1.1 as amount`
- B→C: `WHERE amount > 100`

**规则引擎输出**：
```sql
(amount * 1.1) > 100
```

### 复杂场景（AI处理）

**输入**：
- A→B: `CASE WHEN amount > 1000 THEN 'HIGH' ELSE 'LOW' END as status`
- B→C: `WHERE status = 'HIGH' AND amount > 100`

**AI改写输出**：
```sql
(CASE WHEN amount > 1000 THEN 'HIGH' ELSE 'LOW' END) = 'HIGH' AND (amount * 1.1) > 100
```

简化后：
```sql
amount > 1000 AND (amount * 1.1) > 100
```

## 支持的AI模型

- **GPT-4**（推荐）：最强的理解和改写能力
- **GPT-3.5-Turbo**：速度快，成本低，适合简单场景
- **其他兼容OpenAI API的模型**

## 成本优化建议

1. **按需启用**：只在处理复杂场景时启用AI
2. **缓存结果**：相同场景的改写结果可以缓存
3. **批量处理**：多个过滤条件可以批量发送给AI
4. **本地模型**：考虑使用本地部署的开源模型降低成本

## 故障排查

### 问题1：AI改写失败

**可能原因**：
- API密钥未配置或无效
- 网络连接问题
- API配额用尽

**解决方案**：
- 检查 `ai_config.json` 配置
- 确认环境变量 `OPENAI_API_KEY` 已设置
- 查看控制台错误日志

### 问题2：改写结果不正确

**可能原因**：
- Prompt不够精确
- 模型理解偏差

**解决方案**：
- 调整 `ai_rewriter.py` 中的Prompt
- 使用更强大的模型（如GPT-4）
- 提供更详细的上下文信息

## 扩展开发

### 自定义AI改写器

可以继承 `AIRewriter` 类实现自定义逻辑：

```python
from src import AIRewriter

class CustomAIRewriter(AIRewriter):
    def rewrite_filter_condition(self, downstream_filter, column_mappings, upstream_filter):
        # 自定义改写逻辑
        pass
```

### 集成其他AI服务

可以修改 `ai_rewriter.py` 集成其他AI服务：

- Azure OpenAI
- Anthropic Claude
- 本地部署的开源模型

## 性能影响

- **规则引擎**：毫秒级响应
- **AI改写**：1-3秒响应（取决于网络和模型）

建议在处理大量文件时，只对复杂场景启用AI。

## 下一步计划

- [ ] 支持批量AI改写
- [ ] 添加改写结果缓存
- [ ] 支持更多AI服务商
- [ ] 提供改写质量评估
- [ ] 支持自定义改写规则模板
