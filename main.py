import argparse
import os
import re
import sys
from pathlib import Path

from src import (
    preprocess_sql,
    LineageAnalyzer,
    LocalFileMetadataProvider,
    DummyMetadataProvider,
    export_to_excel,
    export_to_html,
    ParseResult,
)
from src.multi_file_analyzer import MultiFileAnalyzer


def _find_leaf_folders(root: Path) -> list[Path]:
    leaf_folders = []
    for dirpath, dirnames, filenames in os.walk(root):
        folder = Path(dirpath)
        has_sql = any(f.endswith('.sql') for f in filenames)
        has_subdirs = len(dirnames) > 0
        if has_sql and not has_subdirs:
            leaf_folders.append(folder)
    leaf_folders.sort()
    return leaf_folders


def _validate_no_mixed_folders(root: Path) -> list[str]:
    errors = []
    for dirpath, dirnames, filenames in os.walk(root):
        has_sql = any(f.endswith('.sql') for f in filenames)
        has_subdirs = len(dirnames) > 0
        if has_sql and has_subdirs:
            rel = Path(dirpath).relative_to(root)
            errors.append(
                f"文件夹 {rel} 同时包含SQL文件和子文件夹，不支持此结构。"
                f"请将SQL文件移入子文件夹，或移除子文件夹。"
            )
    return errors


def _get_sorted_sql_files(directory: Path) -> list[Path]:
    sql_files = []
    for f in directory.iterdir():
        if f.is_file() and f.name.endswith('.sql'):
            match = re.match(r'^(\d+)_(.+)\.sql$', f.name)
            if match:
                sql_files.append((int(match.group(1)), f))
    sql_files.sort(key=lambda x: x[0])
    return [f[1] for f in sql_files]


def main():
    parser = argparse.ArgumentParser(
        description="SQL加工脚本解析工具 - 提取表级与字段级血缘关系"
    )
    parser.add_argument(
        "input",
        help="输入SQL文件路径或目录"
    )
    parser.add_argument(
        "-o", "--output",
        default="output",
        help="输出目录 (默认: output)"
    )
    parser.add_argument(
        "-m", "--metadata",
        default=None,
        help="元数据目录路径 (用于SELECT *展开)"
    )
    parser.add_argument(
        "--excel",
        default="lineage_mapping.xlsx",
        help="Excel输出文件名 (默认: lineage_mapping.xlsx)"
    )
    parser.add_argument(
        "--html",
        default="lineage_dag.html",
        help="HTML数据流图输出文件名 (默认: lineage_dag.html)"
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="多文件血缘合并模式 (移除中间临时表，合并转换逻辑)"
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help="启用AI增强功能 (需要配置API密钥)"
    )
    parser.add_argument(
        "--ai-config",
        default="ai_config.json",
        help="AI配置文件路径 (默认: ai_config.json)"
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.metadata:
        metadata_provider = LocalFileMetadataProvider(args.metadata)
    else:
        metadata_provider = DummyMetadataProvider()

    if args.merge and input_path.is_dir():
        print(f"多文件血缘合并模式")
        if args.ai:
            print(f"AI增强功能: 已启用")
        print(f"扫描目录: {input_path}")

        leaf_folders = _find_leaf_folders(input_path)
        if not leaf_folders:
            print("\n错误: 未找到包含SQL文件的文件夹")
            sys.exit(1)

        errors = _validate_no_mixed_folders(input_path)
        if errors:
            for err in errors:
                print(f"错误: {err}")
            sys.exit(1)

        print(f"发现 {len(leaf_folders)} 个SQL文件夹:")
        for folder in leaf_folders:
            print(f"  - {folder.relative_to(input_path)}")

        parse_result = ParseResult()

        for folder in leaf_folders:
            sql_files = _get_sorted_sql_files(folder)
            if not sql_files:
                continue

            rel_path = folder.relative_to(input_path)
            print(f"\n处理文件夹: {rel_path}")
            print(f"  SQL文件: {len(sql_files)} 个")

            analyzer = MultiFileAnalyzer(
                metadata_provider=metadata_provider,
                enable_ai=args.ai,
                ai_config_file=args.ai_config
            )
            folder_result = analyzer.parse_files(
                [str(f) for f in sql_files],
                label=str(rel_path),
            )

            for lr in folder_result.lineage_results:
                parse_result.lineage_results.append(lr)
            parse_result.errors.extend(folder_result.errors)
        
        if not parse_result.lineage_results:
            print("\n警告: 未提取到任何血缘关系")
            return
        
        excel_path = output_dir / args.excel
        print(f"\n导出Excel: {excel_path}")
        export_to_excel(parse_result, str(excel_path))
        
        html_path = output_dir / args.html
        print(f"导出数据流图: {html_path}")
        export_to_html(parse_result, str(html_path))
        
        print("\n处理完成!")
        print(f"  总计处理: {len(parse_result.lineage_results)} 个目标表")
        print(f"  字段映射: {sum(len(l.mappings) for l in parse_result.lineage_results)} 个")
        print(f"  表依赖: {sum(len(l.dependencies) for l in parse_result.lineage_results)} 个")
        
        if parse_result.errors:
            print(f"\n发生 {len(parse_result.errors)} 个错误:")
            for error in parse_result.errors:
                print(f"  - {error}")
    else:
        sql_files = []
        if input_path.is_file():
            sql_files.append(input_path)
        elif input_path.is_dir():
            sql_files.extend(input_path.glob("**/*.sql"))
        else:
            print(f"错误: 输入路径不存在: {input_path}")
            sys.exit(1)

        if not sql_files:
            print(f"错误: 未找到SQL文件: {input_path}")
            sys.exit(1)

        print(f"找到 {len(sql_files)} 个SQL文件")

        analyzer = LineageAnalyzer(metadata_provider)
        parse_result = ParseResult()

        for sql_file in sql_files:
            print(f"\n处理文件: {sql_file}")
            try:
                with open(sql_file, 'r', encoding='utf-8') as f:
                    sql_content = f.read()

                statements = preprocess_sql(sql_content)
                print(f"  提取到 {len(statements)} 条SQL语句")

                for idx, stmt in enumerate(statements, 1):
                    print(f"  解析语句 {idx}/{len(statements)}...")
                    lineage = analyzer.parse(stmt)

                    if lineage.target_table:
                        print(f"    目标表: {lineage.target_table}")
                        print(f"    字段映射: {len(lineage.mappings)} 个")
                        print(f"    表依赖: {len(lineage.dependencies)} 个")
                        parse_result.lineage_results.append(lineage)

                        if lineage.warnings:
                            for warning in lineage.warnings:
                                print(f"    警告: {warning}")
                    else:
                        print(f"    跳过: 无法识别目标表")

            except Exception as e:
                error_msg = f"处理文件 {sql_file} 时出错: {str(e)}"
                print(f"  错误: {error_msg}")
                parse_result.errors.append(error_msg)

        if not parse_result.lineage_results:
            print("\n警告: 未提取到任何血缘关系")
            return

        excel_path = output_dir / args.excel
        print(f"\n导出Excel: {excel_path}")
        export_to_excel(parse_result, str(excel_path))

        html_path = output_dir / args.html
        print(f"导出数据流图: {html_path}")
        export_to_html(parse_result, str(html_path))

        print("\n处理完成!")
        print(f"  总计处理: {len(parse_result.lineage_results)} 个目标表")
        print(f"  字段映射: {sum(len(l.mappings) for l in parse_result.lineage_results)} 个")
        print(f"  表依赖: {sum(len(l.dependencies) for l in parse_result.lineage_results)} 个")

        if parse_result.errors:
            print(f"\n发生 {len(parse_result.errors)} 个错误:")
            for error in parse_result.errors:
                print(f"  - {error}")


if __name__ == "__main__":
    main()
