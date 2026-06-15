"""
AI增强模块 - 使用大语言模型处理复杂SQL改写场景
"""
import os
from typing import Optional
import json


class AIRewriter:
    """AI驱动的SQL改写器"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4", base_url: Optional[str] = None):
        """
        初始化AI改写器
        
        Args:
            api_key: OpenAI API密钥，如果不提供则从环境变量OPENAI_API_KEY读取
            model: 使用的模型名称，默认gpt-4
            base_url: API基础URL，用于自定义端点（如Azure OpenAI、本地模型等）
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.base_url = base_url
        
        if not self.api_key:
            raise ValueError("请提供API密钥或设置环境变量OPENAI_API_KEY")
    
    def rewrite_filter_condition(self, downstream_filter: str, 
                                column_mappings: list[dict],
                                upstream_filter: str) -> str:
        """
        使用AI改写过滤条件
        
        Args:
            downstream_filter: 下游过滤条件
            column_mappings: 列映射关系列表，每项包含:
                - target_column: 目标列名
                - transformation_rule: 转换规则
            upstream_filter: 上游过滤条件
            
        Returns:
            改写后的过滤条件
        """
        try:
            from openai import OpenAI
            
            if self.base_url:
                client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            else:
                client = OpenAI(api_key=self.api_key)
            
            mappings_desc = "\n".join([
                f"  - {m['target_column']}: {m['transformation_rule']}"
                for m in column_mappings
                if m.get('transformation_rule') and m['transformation_rule'] != m['target_column']
            ])
            
            prompt = f"""你是一个SQL专家。请帮我改写SQL过滤条件。

场景：
- 表A的数据经过加工后写入表B，表B的数据再经过加工后写入表C
- 现在需要将表B到表C的过滤条件改写为基于表A的过滤条件

列映射关系（表B的列 <- 表A的转换逻辑）：
{mappings_desc if mappings_desc else "  （无转换，直接映射）"}

上游过滤条件（表A到表B）：
{upstream_filter if upstream_filter else "（无）"}

下游过滤条件（表B到表C，基于表B的列）：
{downstream_filter}

请完成以下任务：
1. 将下游过滤条件中的列引用替换为表A的实际表达式
2. 如果转换规则包含运算或函数，用括号包裹以确保优先级正确
3. 将改写后的下游过滤条件与上游过滤条件用AND合并
4. 只返回最终的过滤条件表达式，不要包含WHERE关键字，不要有其他解释

示例：
如果下游过滤是 "amount > 100"，而amount的转换是 "amount * 1.1"
则改写为 "(amount * 1.1) > 100"

最终答案："""

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个SQL专家，专注于过滤条件的改写和合并。请只返回SQL表达式，不要有任何额外说明。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            result = response.choices[0].message.content.strip()
            
            if result.startswith("```"):
                lines = result.split("\n")
                result = "\n".join(lines[1:-1]) if len(lines) > 2 else result
            
            return result
            
        except ImportError:
            print("Warning: openai package not installed. Install with: pip install openai")
            return self._fallback_rewrite(downstream_filter, column_mappings, upstream_filter)
        except Exception as e:
            print(f"Warning: AI rewrite failed: {e}")
            return self._fallback_rewrite(downstream_filter, column_mappings, upstream_filter)
    
    def rewrite_column_transformation(self, upstream_transformation: str,
                                     downstream_transformation: str,
                                     column_name: str) -> str:
        """
        使用AI整合字段转换逻辑
        
        Args:
            upstream_transformation: 上游转换逻辑（表A到表B）
            downstream_transformation: 下游转换逻辑（表B到表C）
            column_name: 字段名
            
        Returns:
            整合后的转换逻辑（表A到表C）
        """
        try:
            from openai import OpenAI
            
            if self.base_url:
                client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            else:
                client = OpenAI(api_key=self.api_key)
            
            prompt = f"""你是一个SQL专家。请帮我整合两个字段的转换逻辑。

场景：
- 表A的字段经过转换后写入表B
- 表B的字段再经过转换后写入表C
- 现在需要将两个转换逻辑整合为表A直接到表C的转换

字段名: {column_name}

上游转换逻辑（表A → 表B）:
{upstream_transformation if upstream_transformation else "（直接映射，无转换）"}

下游转换逻辑（表B → 表C）:
{downstream_transformation if downstream_transformation else "（直接映射，无转换）"}

请完成以下任务：
1. 将下游转换中的字段引用替换为上游的实际表达式
2. 简化表达式，去除冗余的括号和运算
3. 确保运算优先级正确
4. 只返回最终的转换表达式，不要有任何解释

示例：
上游: amount * 1.1
下游: amount * 1.13
结果: amount * 1.1 * 1.13

上游: UPPER(name)
下游: CONCAT('Mr. ', name)
结果: CONCAT('Mr. ', UPPER(name))

最终答案："""

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个SQL专家，专注于字段转换逻辑的整合和简化。请只返回SQL表达式，不要有任何额外说明。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=300
            )
            
            if not response or not response.choices or len(response.choices) == 0:
                raise Exception("Empty response from AI")
            
            result = response.choices[0].message.content
            
            if not result:
                raise Exception("Empty content in AI response")
            
            result = result.strip()
            
            if result.startswith("```"):
                lines = result.split("\n")
                result = "\n".join(lines[1:-1]) if len(lines) > 2 else result
            
            return result
            
        except Exception as e:
            print(f"Warning: AI column transformation rewrite failed: {e}")
            return self._fallback_column_rewrite(upstream_transformation, downstream_transformation)
    
    def _fallback_column_rewrite(self, upstream_transformation: str,
                                downstream_transformation: str) -> str:
        """
        字段转换整合的降级方案
        """
        import re
        
        if not upstream_transformation or upstream_transformation == "（直接映射，无转换）":
            return downstream_transformation
        if not downstream_transformation or downstream_transformation == "（直接映射，无转换）":
            return upstream_transformation
        
        col_name_match = re.search(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', downstream_transformation)
        if col_name_match:
            col_name = col_name_match.group(1)
            result = re.sub(r'\b' + re.escape(col_name) + r'\b', f"({upstream_transformation})", downstream_transformation)
            return result
        
        return f"({upstream_transformation}) * ({downstream_transformation})"
    
    def _fallback_rewrite(self, downstream_filter: str, 
                         column_mappings: list[dict],
                         upstream_filter: str) -> str:
        """
        规则引擎的降级方案
        """
        import re
        
        if not downstream_filter:
            return upstream_filter
        
        column_transform_map = {}
        for mapping in column_mappings:
            if mapping.get('transformation_rule') and mapping['transformation_rule'] != mapping['target_column']:
                column_transform_map[mapping['target_column']] = mapping['transformation_rule']
        
        if not column_transform_map:
            if upstream_filter:
                return f"{upstream_filter} AND {downstream_filter}"
            return downstream_filter
        
        try:
            rewritten_filter = downstream_filter
            for col_name, transform_expr in column_transform_map.items():
                pattern = r'\b' + re.escape(col_name) + r'\b'
                if re.search(pattern, rewritten_filter):
                    if any(op in transform_expr for op in ['(', '*', '/', '+', '-']):
                        replacement = f"({transform_expr})"
                    else:
                        replacement = transform_expr
                    rewritten_filter = re.sub(pattern, replacement, rewritten_filter)
            
            if upstream_filter:
                return f"{upstream_filter} AND {rewritten_filter}"
            return rewritten_filter
        except Exception:
            if upstream_filter:
                return f"{upstream_filter} AND {downstream_filter}"
            return downstream_filter
    
    def explain_lineage(self, source_table: str, target_table: str, 
                       transformations: list[str]) -> str:
        """
        使用AI解释血缘关系
        
        Args:
            source_table: 源表名
            target_table: 目标表名
            transformations: 转换逻辑列表
            
        Returns:
            血缘关系的自然语言解释
        """
        try:
            from openai import OpenAI
            
            if self.base_url:
                client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            else:
                client = OpenAI(api_key=self.api_key)
            
            trans_desc = "\n".join([f"  {i+1}. {t}" for i, t in enumerate(transformations)])
            
            prompt = f"""请用简洁的中文解释以下数据血缘关系：

从表 {source_table} 到表 {target_table} 的转换逻辑：
{trans_desc}

请说明：
1. 数据经过了哪些主要处理步骤
2. 关键的转换逻辑是什么
3. 最终数据的特征

回答要求：简洁明了，不超过200字。"""

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个数据分析专家，擅长解释数据血缘关系。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=300
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            return f"AI解释失败: {e}"


class AIRewriterConfig:
    """AI改写器配置"""
    
    def __init__(self, config_file: str = "ai_config.json"):
        self.config_file = config_file
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        """加载配置文件"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "enabled": False,
            "api_key": "",
            "model": "gpt-4",
            "base_url": "",
            "fallback_to_rules": True
        }
    
    def save_config(self):
        """保存配置文件"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def is_enabled(self) -> bool:
        """检查AI功能是否启用"""
        return self.config.get("enabled", False) and bool(self.config.get("api_key"))
    
    def get_rewriter(self) -> Optional[AIRewriter]:
        """获取AI改写器实例"""
        if not self.is_enabled():
            return None
        
        try:
            base_url = self.config.get("base_url", "")
            return AIRewriter(
                api_key=self.config["api_key"],
                model=self.config.get("model", "gpt-4"),
                base_url=base_url if base_url else None
            )
        except Exception as e:
            print(f"Warning: Failed to initialize AI rewriter: {e}")
            return None
