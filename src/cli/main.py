"""
CLI 命令行入口

用法:
    chemdb collect [--tier 1]              # 采集数据
    chemdb validate [--cas 7664-93-9]      # 验证数据
    chemdb report                           # 生成质量报告
    chemdb serve                            # 启动 API 服务（后续）
"""
import asyncio
import csv
import json
import sys
from pathlib import Path

import click
from loguru import logger

# 配置 logger
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


@click.group()
def cli_group():
    """工业化学物质数据库 CLI 工具"""
    pass


@cli_group.command()
@click.option("--tier", "-t", type=int, default=0, help="只采集指定 tier (0=全部)")
@click.option("--concurrency", "-c", type=int, default=3, help="并发数")
@click.option("--csv", "csv_path", default="config/substance_target_list.csv", help="物质列表 CSV")
@click.option("--config", "config_path", default="config/config.yaml", help="配置文件路径")
def collect(tier: int, concurrency: int, csv_path: str, config_path: str):
    """采集化学物质数据"""
    from src.collectors.orchestrator import CollectionOrchestrator

    orch = CollectionOrchestrator(config_path)
    substances = orch.load_substance_list(csv_path)

    if tier > 0:
        substances = [s for s in substances if s["tier"] == tier]
        logger.info(f"筛选 Tier {tier}: {len(substances)} 种物质")

    asyncio.run(orch.collect_batch(substances, concurrency=concurrency))


@cli_group.command()
@click.option("--data-dir", default="./data/substances", help="数据文件目录")
@click.option("--output", "-o", default="./data/quality_report.md", help="报告输出路径")
def validate(data_dir: str, output: str):
    """验证采集的数据，生成质量报告"""
    from src.validation.cross_referencer import CrossReferencer

    ref = CrossReferencer(data_dir)
    reports = ref.validate_all()
    report_md = ref.generate_report(reports)

    # 输出报告
    with open(output, "w", encoding="utf-8") as f:
        f.write(report_md)
    logger.info(f"质量报告已保存到: {output}")

    # 也输出到控制台
    print(report_md)


@cli_group.command()
@click.option("--data-dir", default="./data/substances", help="数据文件目录")
def stats(data_dir: str):
    """显示数据统计信息"""
    data_path = Path(data_dir)
    json_files = list(data_path.glob("*.json"))
    logger.info(f"数据文件总数: {len(json_files)}")

    total_props = 0
    total_thermo = 0
    total_rxns = 0
    total_processes = 0
    confidences = []

    for fp in sorted(json_files):
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        sub = data.get("substance", {})
        val = data.get("validation", {})
        total_props += len(data.get("properties", []))
        total_thermo += len(data.get("thermodynamics", []))
        total_rxns += len(data.get("reactions", []))
        total_processes += len(data.get("processes", []))
        conf = val.get("overall_confidence", 0)
        confidences.append(conf)

        logger.info(
            f"  {sub.get('name_cn', '?'):12s} | "
            f"物性:{len(data.get('properties', [])):3d} | "
            f"热力:{len(data.get('thermodynamics', [])):3d} | "
            f"反应:{len(data.get('reactions', [])):2d} | "
            f"工艺:{len(data.get('processes', [])):2d} | "
            f"置信度:{conf:.2f}"
        )

    if confidences:
        avg_conf = sum(confidences) / len(confidences)
        logger.info(f"\n平均置信度: {avg_conf:.2f}")
        logger.info(f"物性总数: {total_props}, 热力学数据总数: {total_thermo}")
        logger.info(f"反应方程总数: {total_rxns}, 工业工艺总数: {total_processes}")


if __name__ == "__main__":
    cli_group()
