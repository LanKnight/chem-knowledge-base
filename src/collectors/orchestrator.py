"""
采集编排器

协调 PubChem、NIST、Wikipedia 三个采集器，批量采集化学物质数据，
并将多来源数据合并为统一的结构化 JSON 文件。
"""
import asyncio
import csv
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

import yaml
from loguru import logger

from .pubchem_collector import PubChemCollector
from .nist_collector import NistCollector
from .wiki_collector import WikipediaCollector


class CollectionOrchestrator:
    """数据采集编排器"""

    def __init__(self, config_path: str = "config/config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        output_dir = self.config.get("scraping", {}).get("output_dir", "./data/substances")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.pubchem = PubChemCollector(self.config, str(self.output_dir / "pubchem"))
        self.nist = NistCollector(self.config, str(self.output_dir / "nist"))
        self.wikipedia = WikipediaCollector(self.config, str(self.output_dir / "wikipedia"))

    def load_substance_list(self, csv_path: str) -> list[dict]:
        """从 CSV 加载目标物质列表"""
        substances = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                substances.append({
                    "tier": int(row.get("tier", 0)),
                    "cas_number": row["cas_number"].strip(),
                    "name_cn": row.get("name_cn", "").strip(),
                    "name_en": row.get("name_en", "").strip(),
                    "molecular_formula": row.get("molecular_formula", "").strip(),
                    "substance_type": row.get("substance_type", "").strip(),
                })
        logger.info(f"加载了 {len(substances)} 种目标物质")
        return substances

    async def collect_single(self, sub: dict) -> Optional[Dict[str, Any]]:
        """
        采集单个物质：并行运行三个采集器，合并结果。
        """
        cas = sub["cas_number"]
        name_cn = sub.get("name_cn", "")
        name_en = sub.get("name_en", "")

        logger.info(f"开始采集: {cas} ({name_cn})")

        # 并行采集
        pubchem_task = self.pubchem.collect(cas, name_cn, name_en)
        # NIST 和 Wikipedia 也并行
        nist_task = self.nist.collect(cas, name_cn, name_en)
        wiki_task = self.wikipedia.fetch_by_names(name_en, name_cn) if (name_en or name_cn) else None
        if wiki_task is None:
            wiki_task = asyncio.sleep(0)  # no-op

        pubchem_data, nist_data = await asyncio.gather(pubchem_task, nist_task)
        # Wikipedia 用不同的方法
        wiki_result = await self.wikipedia.fetch_by_names(name_en, name_cn) if (name_en or name_cn) else None

        # 合并数据
        merged = self._merge_data(sub, pubchem_data, nist_data, wiki_result)

        # 保存最终结果
        filepath = self.output_dir / f"{cas.replace('-', '_')}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存合并数据: {filepath}")

        return merged

    async def collect_batch(self, substances: list[dict], concurrency: int = 3) -> list[dict]:
        """批量采集（并发控制）"""
        sem = asyncio.Semaphore(concurrency)

        async def _collect_one(sub):
            async with sem:
                return await self.collect_single(sub)

        tasks = [_collect_one(s) for s in substances]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        cleaned = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"采集异常 [{substances[i].get('cas_number', '?')}]: {r}")
                cleaned.append(None)
            else:
                cleaned.append(r)

        # 统计
        success = sum(1 for r in cleaned if r is not None)
        logger.info(f"批量采集完成: {success}/{len(substances)} 成功")

        return [r for r in cleaned if r is not None]

    def _merge_data(
        self,
        target: dict,
        pubchem: Optional[dict],
        nist: Optional[dict],
        wiki: Optional[dict],
    ) -> dict:
        """合并三个来源的数据为统一 JSON 格式"""

        sources_used = []
        if pubchem:
            sources_used.append("pubchem")
        if nist:
            sources_used.append("nist")
        if wiki:
            sources_used.append("wikipedia")

        merged = {
            "substance": {
                "cas_number": target["cas_number"],
                "name_cn": target.get("name_cn", ""),
                "name_en": target.get("name_en", ""),
                "molecular_formula": target.get("molecular_formula", ""),
                "molecular_weight": None,
                "smiles": None,
                "inchi": None,
                "inchikey": None,
                "substance_type": target.get("substance_type", ""),
                "chemical_class": "",
                "state_at_25c": "",
            },
            "names": [],
            "properties": [],
            "thermodynamics": [],
            "reactions": [],
            "processes": [],
            "safety": {},
            "dexpi_equipment": [],
            "validation": {
                "sources_used": sources_used,
                "overall_confidence": 0.0,
                "conflicts": [],
            },
        }

        # ---- PubChem 数据合并 ----
        if pubchem:
            pc_id = pubchem.get("identifiers", {})
            sub = merged["substance"]

            sub["molecular_formula"] = sub["molecular_formula"] or pc_id.get("molecular_formula")
            sub["molecular_weight"] = pc_id.get("molecular_weight")
            sub["smiles"] = pc_id.get("canonical_smiles") or pc_id.get("isomeric_smiles")
            sub["inchi"] = pc_id.get("inchi")
            sub["inchikey"] = pc_id.get("inchikey")
            sub["exact_mass"] = pc_id.get("exact_mass")

            if pc_id.get("iupac_name_en"):
                merged["names"].append({
                    "name": pc_id["iupac_name_en"],
                    "language": "en",
                    "name_type": "iupac",
                })

            for syn in pc_id.get("synonyms", [])[:10]:
                if syn and syn != sub["name_en"]:
                    merged["names"].append({
                        "name": syn,
                        "language": "en",
                        "name_type": "synonym",
                    })

            merged["properties"].extend(pubchem.get("properties", []))

            if pubchem.get("safety"):
                merged["safety"] = pubchem["safety"]

        # ---- NIST 数据合并 ----
        if nist:
            # 热力学数据
            for key in ["gas_phase_thermochemistry", "condensed_phase_thermochemistry"]:
                for entry in nist.get(key, []):
                    if entry.get("data_type"):
                        merged["thermodynamics"].append(entry)

            # 相变数据合并到 properties
            for entry in nist.get("phase_change_data", []):
                if entry.get("property_type"):
                    merged["properties"].append({
                        "property_type": entry["property_type"],
                        "value": entry["value"],
                        "unit": entry["unit"],
                        "source": "nist",
                    })

            # 反应热化学
            for entry in nist.get("reaction_thermochemistry", []):
                merged["reactions"].append({
                    "equation": entry.get("reaction", ""),
                    "delta_h": entry.get("value") if "enthalpy" in str(entry.get("data_type", "")).lower() else None,
                    "unit": entry.get("unit"),
                    "source": "nist",
                })

        # ---- Wikipedia 数据合并 ----
        if wiki:
            merged_wiki = wiki.get("merged", {}) or {}

            if merged_wiki.get("name_cn") and merged_wiki["name_cn"] != merged["substance"]["name_cn"]:
                merged["names"].append({
                    "name": merged_wiki["name_cn"],
                    "language": "zh",
                    "name_type": "wiki_title",
                })

            # 合并中文章节
            zh_sections = merged_wiki.get("zh_sections", {})
            for section_title, content in zh_sections.items():
                if any(kw in section_title for kw in ["制备", "生产", "制造", "合成", "工业"]):
                    if not merged["processes"]:
                        merged["processes"].append({
                            "process_name_cn": f"{merged['substance']['name_cn']}的工业制备",
                            "description_cn": content,
                            "source": "wikipedia_zh",
                        })
                    else:
                        merged["processes"][0]["description_cn"] = (
                            (merged["processes"][0].get("description_cn", "") or "") + "\n\n" + content
                        )

                if "安全" in section_title or "危险" in section_title:
                    if not merged["safety"].get("description_cn"):
                        merged["safety"]["description_cn"] = content

            # 合并英文工业章节
            en_sections = merged_wiki.get("en_sections", {})
            for section_title, content in en_sections.items():
                if any(kw in section_title.lower() for kw in ["preparation", "production", "synthesis", "industrial"]):
                    if merged["processes"]:
                        merged["processes"][0]["description_en"] = content
                    else:
                        merged["processes"].append({
                            "process_name_en": f"Production of {merged['substance']['name_en']}",
                            "description_en": content,
                            "source": "wikipedia_en",
                        })
                    merged["processes"][-1]["source"] = "wikipedia_en"

            # 合并反应方程式
            wiki_reactions = merged_wiki.get("reactions", [])
            for r in wiki_reactions:
                existing_eqs = {mr.get("equation", "") for mr in merged["reactions"]}
                if r["equation"] not in existing_eqs:
                    merged["reactions"].append({
                        "equation": r["equation"],
                        "format": r.get("format", "plain_text"),
                        "source": "wikipedia",
                    })

            # 合并别名
            if wiki.get("zh_wiki") and wiki["zh_wiki"].get("aliases"):
                for alias in wiki["zh_wiki"]["aliases"]:
                    merged["names"].append({
                        "name": alias["name"],
                        "language": "zh",
                        "name_type": alias.get("type", "synonym"),
                    })

            if wiki.get("en_wiki") and wiki["en_wiki"].get("aliases"):
                for alias in wiki["en_wiki"]["aliases"]:
                    merged["names"].append({
                        "name": alias["name"],
                        "language": "en",
                        "name_type": alias.get("type", "synonym"),
                    })

        # ---- 计算初始置信度 ----
        merged["validation"]["overall_confidence"] = self._compute_initial_confidence(sources_used)

        return merged

    def _compute_initial_confidence(self, sources_used: list[str]) -> float:
        """基于使用的来源数量计算初始置信度"""
        base = {
            "pubchem": 0.85,
            "nist": 0.90,
            "wikipedia": 0.60,
        }
        if not sources_used:
            return 0.0
        confidences = [base.get(s, 0.5) for s in sources_used]
        # 多来源 → 加权平均后乘以放大系数
        avg = sum(confidences) / len(confidences)
        if len(sources_used) >= 3:
            return min(1.0, avg * 1.15)
        elif len(sources_used) == 2:
            return min(1.0, avg * 1.05)
        return avg


# ---- CLI 入口 ----
async def main():
    """命令行入口：运行采集编排器"""
    import sys

    csv_path = sys.argv[1] if len(sys.argv) > 1 else "config/substance_target_list.csv"
    config_path = sys.argv[2] if len(sys.argv) > 2 else "config/config.yaml"

    orchestrator = CollectionOrchestrator(config_path)
    substances = orchestrator.load_substance_list(csv_path)

    # 按 tier 分批执行
    for tier in [1, 2, 3]:
        batch = [s for s in substances if s["tier"] == tier]
        if not batch:
            continue
        logger.info(f"\n{'='*60}\n开始采集 Tier {tier} ({len(batch)} 种物质)\n{'='*60}")
        await orchestrator.collect_batch(batch, concurrency=3)

    logger.info("全部采集完成！")


if __name__ == "__main__":
    asyncio.run(main())
