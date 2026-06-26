"""
数据交叉验证模块

对采集到的多来源数据进行交叉验证：
- 同一属性的多来源数值偏差比较
- 置信度评分
- 化学合理性检查
- 输出数据质量报告
"""
import json
from pathlib import Path
from typing import Optional, Dict, Any

from loguru import logger


# 各来源的基础可靠性权重
SOURCE_RELIABILITY = {
    "pubchem": 0.85,
    "nist": 0.90,
    "wikipedia_zh": 0.60,
    "wikipedia_en": 0.65,
    "wikipedia": 0.62,
    "manual_gb": 0.80,
    "manual_expert": 0.95,
}

# 各属性可接受的偏差百分比范围
ACCEPTABLE_DEVIATION = {
    "boiling_point": 3.0,
    "melting_point": 5.0,
    "density": 2.0,
    "molecular_weight": 0.1,
    "enthalpy_of_formation": 5.0,
    "entropy": 3.0,
    "heat_capacity": 5.0,
    "gibbs_free_energy": 5.0,
    "vapor_pressure": 10.0,
    "flash_point": 10.0,
    "refractive_index": 1.0,
}


class CrossReferencer:
    """跨来源交叉验证器"""

    def __init__(self, data_dir: str = "./data/substances"):
        self.data_dir = Path(data_dir)

    def validate_all(self) -> list[dict]:
        """验证所有物质数据文件，返回质量报告"""
        reports = []
        json_files = list(self.data_dir.glob("*.json"))
        logger.info(f"开始验证 {len(json_files)} 个数据文件")

        for filepath in sorted(json_files):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            report = self.validate_substance(data)
            reports.append(report)

            # 更新数据文件中的验证信息
            data["validation"] = report["validation"]
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        return reports

    def validate_substance(self, data: dict) -> dict:
        """验证单个物质的数据"""
        cas = data.get("substance", {}).get("cas_number", "unknown")
        name = data.get("substance", {}).get("name_cn", "unknown")
        report = {
            "cas": cas,
            "name": name,
            "checks": [],
            "conflicts": [],
            "validation": {
                "overall_confidence": 0.0,
                "conflicts": [],
            },
        }

        # ---- 检查1：格式验证 ----
        self._check_format(data, report)

        # ---- 检查2：属性数值合理性 ----
        self._check_property_ranges(data, report)

        # ---- 检查3：多来源交叉验证 ----
        self._check_cross_source(data, report)

        # ---- 检查4：化学合理性 ----
        self._check_chemical_consistency(data, report)

        # ---- 计算整体置信度 ----
        confidence = self._compute_confidence(data, report)
        report["validation"]["overall_confidence"] = round(confidence, 2)

        # 汇总
        issues = [c for c in report["checks"] if not c.get("passed", True)]
        conflicts = report["conflicts"]
        logger.info(
            f"[{cas}] {name}: 置信度={confidence:.2f}, "
            f"问题={len(issues)}, 冲突={len(conflicts)}"
        )

        return report

    def _check_format(self, data: dict, report: dict):
        """格式验证"""
        sub = data.get("substance", {})

        # CAS 号存在性
        cas = sub.get("cas_number", "")
        if not cas:
            report["checks"].append({
                "check": "cas_present",
                "passed": False,
                "detail": "缺少 CAS 号",
            })
        else:
            report["checks"].append({
                "check": "cas_present",
                "passed": True,
                "detail": f"CAS={cas}",
            })

        # SMILES 可解析性（简单检查非空）
        smiles = sub.get("smiles", "")
        if not smiles:
            report["checks"].append({
                "check": "smiles_present",
                "passed": False,
                "detail": "缺少 SMILES",
            })
        else:
            report["checks"].append({
                "check": "smiles_present",
                "passed": True,
                "detail": f"SMILES={smiles[:50]}...",
            })

        # 分子量 > 0
        mw = sub.get("molecular_weight")
        if mw is None or (isinstance(mw, (int, float)) and mw <= 0):
            report["checks"].append({
                "check": "molecular_weight_positive",
                "passed": False,
                "detail": f"分子量异常: {mw}",
            })
        else:
            report["checks"].append({
                "check": "molecular_weight_positive",
                "passed": True,
                "detail": f"MW={mw}",
            })

        # 名称存在
        name_cn = sub.get("name_cn", "")
        if not name_cn:
            report["checks"].append({
                "check": "name_cn_present",
                "passed": False,
                "detail": "缺少中文名称",
            })
        else:
            report["checks"].append({
                "check": "name_cn_present",
                "passed": True,
            })

    def _check_property_ranges(self, data: dict, report: dict):
        """属性数值范围合理性检查"""
        properties = data.get("properties", [])

        # 收集熔点和沸点
        mp_values = []
        bp_values = []
        density_values = []

        for prop in properties:
            ptype = prop.get("property_type", "")
            val = prop.get("value")
            if val is None:
                continue
            try:
                val = float(val)
            except (ValueError, TypeError):
                continue

            if ptype == "melting_point":
                mp_values.append(val)
            elif ptype == "boiling_point":
                bp_values.append(val)
            elif ptype == "density":
                density_values.append(val)

        # 沸点 > 熔点 检查
        if mp_values and bp_values:
            mp_avg = sum(mp_values) / len(mp_values)
            bp_avg = sum(bp_values) / len(bp_values)
            if bp_avg <= mp_avg:
                report["checks"].append({
                    "check": "bp_gt_mp",
                    "passed": False,
                    "detail": f"沸点({bp_avg}) <= 熔点({mp_avg})",
                })
            else:
                report["checks"].append({
                    "check": "bp_gt_mp",
                    "passed": True,
                })

        # 密度范围检查 (0.0001 ~ 25 g/cm³)
        for d in density_values:
            if d < 0.0001 or d > 25:
                report["checks"].append({
                    "check": "density_range",
                    "passed": False,
                    "detail": f"密度异常: {d} g/cm³",
                })
                break
        else:
            if density_values:
                report["checks"].append({
                    "check": "density_range",
                    "passed": True,
                })

        # 温度范围检查（-273 ~ 5000°C）
        for val in mp_values + bp_values:
            if val < -273 or val > 5000:
                report["checks"].append({
                    "check": "temperature_range",
                    "passed": False,
                    "detail": f"温度异常: {val}°C",
                })
                break
        else:
            if mp_values or bp_values:
                report["checks"].append({
                    "check": "temperature_range",
                    "passed": True,
                })

    def _check_cross_source(self, data: dict, report: dict):
        """多来源同属性交叉验证"""
        properties = data.get("properties", [])

        # 按 property_type 分组
        from collections import defaultdict
        grouped = defaultdict(list)
        for prop in properties:
            ptype = prop.get("property_type", "")
            if ptype:
                grouped[ptype].append(prop)

        for ptype, props in grouped.items():
            if len(props) < 2:
                continue

            sources = list(set(p.get("source", "unknown") for p in props))
            if len(sources) < 2:
                continue

            # 取数值比较
            values = []
            for p in props:
                val = p.get("value")
                if val is not None:
                    try:
                        values.append((float(val), p.get("source", "unknown")))
                    except (ValueError, TypeError):
                        pass

            if len(values) >= 2:
                # 计算最大偏差百分比
                vals = [v[0] for v in values]
                max_val = max(vals)
                min_val = min(vals)
                if max_val != 0:
                    deviation_pct = abs(max_val - min_val) / abs(max_val) * 100
                else:
                    deviation_pct = abs(max_val - min_val) * 100

                threshold = ACCEPTABLE_DEVIATION.get(ptype, 5.0)

                if deviation_pct > threshold:
                    conflict = {
                        "property": ptype,
                        "values": [{"value": v[0], "source": v[1]} for v in values],
                        "deviation_pct": round(deviation_pct, 2),
                        "threshold": threshold,
                        "severity": "high" if deviation_pct > threshold * 3 else "medium",
                    }
                    report["conflicts"].append(conflict)
                    report["validation"]["conflicts"].append(conflict)
                    logger.warning(
                        f"  ⚠ 冲突 [{ptype}]: 偏差={deviation_pct:.1f}% "
                        f"(阈值={threshold}%), 来源={sources}"
                    )

    def _check_chemical_consistency(self, data: dict, report: dict):
        """化学合理性检查"""
        # 检查反应热力学数据是否大致遵循能量守恒
        thermodynamics = data.get("thermodynamics", [])
        reactions = data.get("reactions", [])

        # 简单检查：如果有生成焓和反应焓，数量级应合理
        formation_enthalpies = [
            t for t in thermodynamics
            if t.get("data_type") == "enthalpy_of_formation"
        ]
        reaction_enthalpies = [
            r for r in reactions
            if r.get("delta_h") is not None
        ]

        if formation_enthalpies and reaction_enthalpies:
            # 生成焓通常应该在一定合理范围内
            for fe in formation_enthalpies:
                val = fe.get("value")
                if val is not None:
                    try:
                        val = float(val)
                    except (ValueError, TypeError):
                        continue
                    # 大多数物质的生成焓在 -5000 ~ 5000 kJ/mol
                    if abs(val) > 10000:
                        report["checks"].append({
                            "check": "enthalpy_magnitude",
                            "passed": False,
                            "detail": f"生成焓异常大: {val} kJ/mol",
                        })
                        break
            else:
                report["checks"].append({
                    "check": "enthalpy_magnitude",
                    "passed": True,
                })

    def _compute_confidence(self, data: dict, report: dict) -> float:
        """计算综合置信度"""
        # 基础分来源的数量和质量
        sources = data.get("validation", {}).get("sources_used", [])
        if not sources:
            return 0.0

        base_conf = sum(SOURCE_RELIABILITY.get(s, 0.5) for s in sources) / len(sources)

        # 来源越多，置信度加权
        if len(sources) >= 3:
            base_conf = min(1.0, base_conf * 1.15)
        elif len(sources) == 2:
            base_conf = min(1.0, base_conf * 1.05)

        # 每个格式问题扣 0.05
        format_issues = sum(
            1 for c in report.get("checks", [])
            if not c.get("passed", True)
        )
        base_conf -= format_issues * 0.05

        # 每个冲突扣 0.1
        conflicts = len(report.get("conflicts", []))
        base_conf -= conflicts * 0.1

        # 数据完整度加分
        sub = data.get("substance", {})
        completeness = 0.0
        if sub.get("smiles"):
            completeness += 0.05
        if sub.get("inchi"):
            completeness += 0.05
        if sub.get("molecular_weight"):
            completeness += 0.05
        if data.get("properties"):
            completeness += min(0.1, len(data["properties"]) * 0.01)
        if data.get("thermodynamics"):
            completeness += 0.05
        if data.get("processes"):
            completeness += 0.1
        if data.get("safety", {}).get("ghs_classifications"):
            completeness += 0.05

        return max(0.0, min(1.0, base_conf + completeness))

    def generate_report(self, reports: list[dict]) -> str:
        """生成数据质量报告（Markdown 格式）"""
        total = len(reports)
        high_conf = sum(1 for r in reports if r["validation"]["overall_confidence"] >= 0.8)
        medium_conf = sum(1 for r in reports if 0.6 <= r["validation"]["overall_confidence"] < 0.8)
        low_conf = sum(1 for r in reports if r["validation"]["overall_confidence"] < 0.6)
        total_conflicts = sum(len(r.get("conflicts", [])) for r in reports)
        total_issues = sum(
            sum(1 for c in r.get("checks", []) if not c.get("passed", True))
            for r in reports
        )

        lines = [
            "# 数据质量报告",
            "",
            f"**统计时间**: 自动生成",
            f"**物质总数**: {total}",
            "",
            "## 置信度分布",
            "",
            f"| 等级 | 数量 | 占比 |",
            f"|------|------|------|",
            f"| 高置信度 (≥0.8) | {high_conf} | {high_conf/total*100:.1f}% |",
            f"| 中置信度 (0.6-0.8) | {medium_conf} | {medium_conf/total*100:.1f}% |",
            f"| 低置信度 (<0.6) | {low_conf} | {low_conf/total*100:.1f}% |",
            "",
            f"**总冲突数**: {total_conflicts}",
            f"**总问题数**: {total_issues}",
            "",
            "## 低置信度物质（需人工审核）",
            "",
        ]

        for r in reports:
            if r["validation"]["overall_confidence"] < 0.6:
                lines.append(f"- **{r['name']}** ({r['cas']}): 置信度={r['validation']['overall_confidence']:.2f}")
                for c in r.get("conflicts", []):
                    lines.append(f"  - ⚠ {c['property']}: 偏差={c['deviation_pct']:.1f}%")

        lines.extend([
            "",
            "## 冲突详情",
            "",
        ])

        for r in reports:
            if r.get("conflicts"):
                lines.append(f"### {r['name']} ({r['cas']})")
                for c in r["conflicts"]:
                    lines.append(f"- **{c['property']}**: 偏差 {c['deviation_pct']}%")
                    for v in c.get("values", []):
                        lines.append(f"  - {v['source']}: {v['value']}")

        return "\n".join(lines)
