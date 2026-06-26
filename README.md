# 工业化学物质知识库 (Industrial Chemistry Knowledge Base)

AI 辅助 P&ID 自动生成系统的结构化化学数据库。

## 项目简介

本知识库为工业化学品提供结构化、多维度的数据支撑，覆盖 **50 种核心工业化学品** 的物理化学性质、热力学数据、工业制备工艺、安全性信息和 DEXPI/P&ID 设备关联。数据来源于 PubChem、NIST Chemistry WebBook、Wikipedia 等公开权威源，经多来源交叉验证确保准确性。

## 技术栈

| 技术 | 用途 |
|------|------|
| **PostgreSQL 16 + pgvector** | 结构化数据存储 + 向量语义搜索 |
| **SQLAlchemy + Alembic** | ORM + 数据库迁移管理 |
| **FastAPI** | RESTful 查询 API |
| **httpx + BeautifulSoup4** | 在线数据采集 |
| **Pydantic** | 数据模型验证 |
| **Click** | CLI 命令行工具 |
| **Python 3.11+** | 开发语言 |

## 数据库 Schema（12 张核心表）

```
substances                  — 物质主表（CAS / 分子式 / SMILES / 中英文名称 / 分类 / 置信度）
substance_names             — 多语言别名（同义词 / 商品名 / IUPAC 命名）
physicochemical_properties  — 物理化学属性（密度 / 熔沸点 / 溶解度 / 蒸气压 / pKa 等）
thermodynamic_data          — 热力学 / 动力学数据（生成焓 / 熵 / 吉布斯自由能 / 活化能 / 平衡常数）
chemical_reactions          — 化学反应方程式（含 ΔH / ΔS / ΔG 及 LaTeX 渲染）
reaction_participants       — 反应物 / 产物 / 催化剂关联（含化学计量系数）
industrial_processes        — 工业制备工艺（温度 / 压力 / 催化剂 / 产率 / 原料 / 副产物 / 中英文描述）
safety_data                 — 安全性数据（GHS 分类 / H&P 代码 / LD50 / 闪点 / 爆炸极限 / NFPA 704 / UN 编号）
dexpi_equipment             — DEXPI / P&ID 设备关联（设备类型 / 材质 / 管材 / 仪表 / 位号）
data_sources                — 数据来源追踪（URL / API / 可靠性评级 / 最后抓取时间）
data_validations            — 跨来源交叉验证记录（偏差 / 一致性判定 / 置信度调整）
chinese_standards           — 中国标准关联（GB 标准 / 危险化学品目录 / 许可要求）
```

## 数据覆盖范围（50 种工业化学品）

### 第一梯队 — 15 种无机基础化工
H₂SO₄ · NH₃ · NaOH · HNO₃ · HCl · H₃PO₄ · Na₂CO₃ · Cl₂ · H₂ · N₂ · O₂ · CO₂ · CaO · Ca(OH)₂ · NaCl

### 第二梯队 — 20 种有机基础化工
C₂H₄ · C₃H₆ · CH₄ · C₂H₅OH · CH₃OH · C₆H₆ · C₂H₂ · CH₂O · C₂H₄O · CH₃COOH · C₆H₅CH₃ · C₈H₁₀ · C₂H₆ · C₃H₈ · C₂H₄Cl₂ · C₃H₆O · CH₂=CHCl · C₆H₁₂ · C₆H₁₂O₆ · 淀粉

### 第三梯队 — 15 种工业催化剂与中间体
Fe · V₂O₅ · Al₂O₃ · SiO₂ · Fe₂O₃ · Ni · Pd · Pt · SO₂ · SO₃ · NH₄NO₃ · (NH₄)₂SO₄ · Ca₅(PO₄)₃(OH) · CO · KOH

## 项目结构

```
chem-knowledge-base/
├── README.md
├── pyproject.toml
├── config/
│   ├── config.yaml                     # 采集器 + 数据库配置
│   └── substance_target_list.csv       # 50 种目标物质 CAS 列表
├── alembic/
│   └── versions/
│       └── 001_initial_schema.py       # 12 张表完整 DDL 迁移
├── src/
│   ├── db/
│   │   └── models.py                   # SQLAlchemy ORM 模型（12 张表）
│   ├── collectors/
│   │   ├── base.py                     # 采集器基类（速率限制 / 重试 / 缓存）
│   │   ├── pubchem_collector.py        # PubChem REST API 采集器
│   │   ├── nist_collector.py           # NIST WebBook HTML 解析采集器
│   │   ├── wiki_collector.py           # Wikipedia 中英文采集器
│   │   └── orchestrator.py             # 三源并行采集编排 + 数据合并
│   ├── validation/
│   │   └── cross_referencer.py         # 跨来源交叉验证 + 置信度评分
│   ├── api/                            # FastAPI 查询接口（骨架）
│   ├── utils/
│   │   └── cas_validator.py            # CAS 号校验
│   └── cli/
│       └── main.py                     # Click CLI（collect / validate / stats）
├── data/
│   └── substances/                     # 50 个结构化 JSON 数据文件
└── docs/
```

## 快速开始

### 环境要求
- Python 3.11+
- PostgreSQL 16+（含 pgvector 扩展）

### 安装

```bash
cd chem-knowledge-base
pip install -e .
```

### 数据库初始化（暂不执行）

```bash
# 1. 创建 PostgreSQL 数据库
createdb industrial_chem

# 2. 启用扩展
psql -d industrial_chem -c "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"

# 3. 执行迁移
alembic upgrade head
```

### CLI 命令

```bash
# 采集数据（需配置数据库后运行）
chemdb collect --tier 1

# 验证数据质量
chemdb validate --data-dir ./data/substances

# 查看统计
chemdb stats --data-dir ./data/substances
```

## 数据格式

每个物质的 JSON 文件结构：

```json
{
  "substance": {
    "cas_number": "7664-93-9",
    "name_cn": "硫酸",
    "name_en": "Sulfuric acid",
    "molecular_formula": "H2SO4",
    "molecular_weight": 98.079,
    "smiles": "OS(=O)(=O)O",
    "substance_type": "inorganic",
    "chemical_class": "acid",
    "state_at_25c": "liquid"
  },
  "names": [
    {"name": "Oil of vitriol", "language": "en", "name_type": "trade"}
  ],
  "properties": [
    {"property_type": "boiling_point", "value": 337, "unit": "°C", "source": "web_search"},
    {"property_type": "density", "value": 1.84, "unit": "g/cm3", "condition_temp": 25}
  ],
  "thermodynamics": [
    {"data_type": "enthalpy_of_formation", "value": -814.0, "unit": "kJ/mol", "phase": "l", "standard_state": true}
  ],
  "reactions": [
    {"equation": "2SO2(g) + O2(g) ⇌ 2SO3(g)", "delta_h": -196.6, "delta_h_unit": "kJ/mol", "source": "web_search"}
  ],
  "processes": [
    {
      "process_name_cn": "接触法制硫酸",
      "process_name_en": "Contact Process",
      "description_cn": "以硫磺或硫铁矿为原料，经造气、催化氧化、吸收三步制得硫酸...",
      "temperature_min": 400, "temperature_max": 600,
      "catalyst": "V2O5 (五氧化二钒)",
      "yield_pct": 99
    }
  ],
  "safety": {
    "ghs_classifications": [{"code": "GHS05", "label": "腐蚀性"}],
    "signal_word": "Danger",
    "h_codes": ["H314: Causes severe skin burns and eye damage"],
    "nfpa_health": 3, "nfpa_fire": 0, "nfpa_reactivity": 2,
    "un_number": "1830"
  },
  "validation": {
    "sources_used": ["web_search"],
    "overall_confidence": 0.85,
    "conflicts": []
  }
}
```

## 数据来源

| 维度 | 首选来源 | 验证来源 |
|------|---------|----------|
| 基本物性 | PubChem REST API | NIST Chemistry WebBook |
| 热力学 | NIST Chemistry WebBook | CRC Handbook |
| 工业工艺 | Wikipedia（中英文） | Ullmann's Encyclopedia |
| 安全 / GHS | PubChem GHS 数据 | 中国《危险化学品目录》 |
| 中文名称 / GB | 中国危险化学品目录 | 全国标准信息服务平台 |
| DEXPI | 项目内 XMI 文件 | ISO 15926 规范 |

## 数据验证策略

1. **格式验证**：CAS 校验位 / SMILES 可解析性 / 分子量合理性
2. **来源交叉验证**：多来源同属性数值偏差对比（偏差 < 5% → 一致，> 20% → 标记待审）
3. **化学合理性**：热力学能量守恒 / 相变关系 / 键能数量级检查
4. **置信度评分**：加权多来源可靠性，自动标记低置信度数据供人工审核

## License

本项目为湖南铼硙科技有限公司内部项目。

---

Built with ❤️ using Python, PostgreSQL, and Claude Code.
