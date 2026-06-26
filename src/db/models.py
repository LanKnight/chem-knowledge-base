"""
SQLAlchemy ORM 模型定义 — 工业化学物质数据库
共 12 张核心表，覆盖物质标识、物性、热力学、反应、工艺、安全、DEXPI、溯源与验证。
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ===========================================================================
# 辅助函数
# ===========================================================================

def gen_uuid():
    return str(uuid4())


def now():
    return datetime.utcnow()


# ===========================================================================
# 表1：物质主表
# ===========================================================================
class Substance(Base):
    __tablename__ = "substances"

    id                = Column(UUID, primary_key=True, default=gen_uuid)
    cas_number        = Column(String(20), unique=True, nullable=False, index=True)
    inchikey          = Column(String(27))
    molecular_formula = Column(String(100), index=True)
    molecular_weight  = Column(Numeric(10, 4))
    smiles            = Column(String(500))
    inchi             = Column(Text)

    name_cn           = Column(String(200), nullable=False, index=True)
    name_en           = Column(String(200), index=True)
    iupac_name_cn     = Column(String(500))
    iupac_name_en     = Column(String(500))

    substance_type    = Column(String(50), index=True)   # inorganic/organic/polymer
    chemical_class    = Column(String(100))              # acid/base/salt/oxide/...
    state_at_25c      = Column(String(20))               # solid/liquid/gas

    exact_mass         = Column(Numeric(10, 6))
    monoisotopic_mass  = Column(Numeric(10, 6))
    charge             = Column(Integer)
    complexity         = Column(Integer)

    data_quality       = Column(String(20), default="pending", index=True)  # pending/verified/reviewed/contested
    overall_confidence = Column(Numeric(3, 2), default=0.00)

    source_id          = Column(UUID, ForeignKey("data_sources.id"))
    created_at         = Column(DateTime, default=now)
    updated_at         = Column(DateTime, default=now, onupdate=now)

    # 关系
    names                  = relationship("SubstanceName", back_populates="substance", cascade="all, delete-orphan")
    properties             = relationship("PhysicochemicalProperty", back_populates="substance", cascade="all, delete-orphan")
    thermodynamics         = relationship("ThermodynamicData", back_populates="substance", cascade="all, delete-orphan")
    safety                 = relationship("SafetyData", back_populates="substance", uselist=False, cascade="all, delete-orphan")
    processes              = relationship("IndustrialProcess", back_populates="substance", cascade="all, delete-orphan")
    dexpi_equipment_list   = relationship("DexpiEquipment", back_populates="substance", cascade="all, delete-orphan")
    reaction_participants  = relationship("ReactionParticipant", back_populates="substance", cascade="all, delete-orphan")
    validations            = relationship("DataValidation", back_populates="substance", cascade="all, delete-orphan")
    standards              = relationship("ChineseStandard", back_populates="substance", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_substances_name_cn_trgm", "name_cn", postgresql_using="gin",
              postgresql_ops={"name_cn": "gin_trgm_ops"}),
        Index("idx_substances_name_en_trgm", "name_en", postgresql_using="gin",
              postgresql_ops={"name_en": "gin_trgm_ops"}),
    )


# ===========================================================================
# 表2：物质别名
# ===========================================================================
class SubstanceName(Base):
    __tablename__ = "substance_names"

    id            = Column(UUID, primary_key=True, default=gen_uuid)
    substance_id  = Column(UUID, ForeignKey("substances.id", ondelete="CASCADE"), nullable=False, index=True)
    name          = Column(String(500), nullable=False)
    language      = Column(String(10), nullable=False, default="zh")   # zh/en/la
    name_type     = Column(String(50), nullable=False, default="synonym")  # synonym/trade/brand/systematic/abbreviation
    is_preferred  = Column(Boolean, default=False)
    source_id     = Column(UUID, ForeignKey("data_sources.id"))
    created_at    = Column(DateTime, default=now)

    substance = relationship("Substance", back_populates="names")

    __table_args__ = (
        Index("idx_substance_names_name_trgm", "name", postgresql_using="gin",
              postgresql_ops={"name": "gin_trgm_ops"}),
    )


# ===========================================================================
# 表3：物理化学属性 (EAV 模式)
# ===========================================================================
class PhysicochemicalProperty(Base):
    __tablename__ = "physicochemical_properties"

    id               = Column(UUID, primary_key=True, default=gen_uuid)
    substance_id     = Column(UUID, ForeignKey("substances.id", ondelete="CASCADE"), nullable=False, index=True)
    property_type    = Column(String(50), nullable=False, index=True)  # boiling_point/melting_point/density/solubility...
    value            = Column(Numeric(15, 6))
    value_min        = Column(Numeric(15, 6))
    value_max        = Column(Numeric(15, 6))
    unit             = Column(String(30))
    value_text       = Column(Text)
    condition_temp   = Column(Numeric(8, 2))
    condition_pressure = Column(Numeric(8, 2))
    condition_ph     = Column(Numeric(4, 2))
    reference        = Column(Text)
    confidence       = Column(Numeric(3, 2), default=0.50)
    source_id        = Column(UUID, ForeignKey("data_sources.id"))
    created_at       = Column(DateTime, default=now)
    updated_at       = Column(DateTime, default=now, onupdate=now)

    substance = relationship("Substance", back_populates="properties")

    __table_args__ = (
        CheckConstraint("value IS NOT NULL OR value_text IS NOT NULL", name="at_least_one_value"),
        Index("idx_physprop_substance_type", "substance_id", "property_type"),
    )


# ===========================================================================
# 表4：热力学/动力学数据
# ===========================================================================
class ThermodynamicData(Base):
    __tablename__ = "thermodynamic_data"

    id               = Column(UUID, primary_key=True, default=gen_uuid)
    substance_id     = Column(UUID, ForeignKey("substances.id", ondelete="CASCADE"), nullable=False, index=True)
    data_type        = Column(String(50), nullable=False, index=True)  # enthalpy_of_formation/entropy/gibbs_free_energy/...
    value            = Column(Numeric(15, 4), nullable=False)
    unit             = Column(String(30), nullable=False)
    phase            = Column(String(20))              # s/l/g/aq/cr
    temperature      = Column(Numeric(8, 2))
    pressure         = Column(Numeric(10, 4))
    standard_state   = Column(Boolean, default=True)   # 是否为标准态 (298.15K, 100kPa)
    reaction_id      = Column(UUID, ForeignKey("chemical_reactions.id"))
    pre_exponential  = Column(Numeric(20, 6))          # 指前因子 A
    activation_energy = Column(Numeric(10, 3))         # 活化能 Ea (kJ/mol)
    rate_constant    = Column(Numeric(20, 10))         # 速率常数 k
    reference        = Column(Text)
    uncertainty      = Column(String(50))
    confidence       = Column(Numeric(3, 2), default=0.50)
    source_id        = Column(UUID, ForeignKey("data_sources.id"))
    created_at       = Column(DateTime, default=now)

    substance = relationship("Substance", back_populates="thermodynamics")
    reaction  = relationship("ChemicalReaction", back_populates="thermodynamics")


# ===========================================================================
# 表5：化学反应
# ===========================================================================
class ChemicalReaction(Base):
    __tablename__ = "chemical_reactions"

    id                  = Column(UUID, primary_key=True, default=gen_uuid)
    equation_text       = Column(Text, nullable=False)   # 反应方程式（LaTeX/MathJax 格式）
    equation_html       = Column(Text)
    reaction_type       = Column(String(50))             # synthesis/decomposition/combustion/oxidation/...
    reversible          = Column(Boolean, default=False)
    delta_h             = Column(Numeric(12, 4))         # kJ/mol
    delta_h_unit        = Column(String(20), default="kJ/mol")
    delta_s             = Column(Numeric(12, 4))         # J/(mol·K)
    delta_g             = Column(Numeric(12, 4))         # kJ/mol
    equilibrium_constant = Column(Numeric(20, 10))
    eq_constant_temp    = Column(Numeric(8, 2))          # °C
    is_industrial       = Column(Boolean, default=False)
    name_cn             = Column(String(200))
    name_en             = Column(String(200))
    description         = Column(Text)
    source_id           = Column(UUID, ForeignKey("data_sources.id"))
    created_at          = Column(DateTime, default=now)
    updated_at          = Column(DateTime, default=now, onupdate=now)

    participants    = relationship("ReactionParticipant", back_populates="reaction", cascade="all, delete-orphan")
    thermodynamics  = relationship("ThermodynamicData", back_populates="reaction")
    processes       = relationship("IndustrialProcess", back_populates="primary_reaction")


# ===========================================================================
# 表6：反应物-产物关联
# ===========================================================================
class ReactionParticipant(Base):
    __tablename__ = "reaction_participants"

    id            = Column(UUID, primary_key=True, default=gen_uuid)
    reaction_id   = Column(UUID, ForeignKey("chemical_reactions.id", ondelete="CASCADE"), nullable=False, index=True)
    substance_id  = Column(UUID, ForeignKey("substances.id", ondelete="CASCADE"), nullable=False, index=True)
    role          = Column(String(20), nullable=False)    # reactant/product/catalyst/solvent/intermediate/inhibitor
    stoichiometry = Column(Numeric(8, 4))                 # 化学计量系数
    phase         = Column(String(10))                    # s/l/g/aq
    is_catalyst   = Column(Boolean, default=False)
    created_at    = Column(DateTime, default=now)

    reaction  = relationship("ChemicalReaction", back_populates="participants")
    substance = relationship("Substance", back_populates="reaction_participants")

    __table_args__ = (
        UniqueConstraint("reaction_id", "substance_id", "role", name="uq_rxn_participant"),
    )


# ===========================================================================
# 表7：工业制备工艺
# ===========================================================================
class IndustrialProcess(Base):
    __tablename__ = "industrial_processes"

    id                = Column(UUID, primary_key=True, default=gen_uuid)
    substance_id      = Column(UUID, ForeignKey("substances.id", ondelete="CASCADE"), nullable=False, index=True)
    process_name_cn   = Column(String(300), nullable=False)
    process_name_en   = Column(String(300))
    description_cn    = Column(Text)
    description_en    = Column(Text)
    process_flow      = Column(Text)
    temperature_min   = Column(Numeric(8, 2))
    temperature_max   = Column(Numeric(8, 2))
    temperature_opt   = Column(Numeric(8, 2))
    pressure_min      = Column(Numeric(10, 4))
    pressure_max      = Column(Numeric(10, 4))
    pressure_opt      = Column(Numeric(10, 4))
    catalyst          = Column(String(500))
    catalyst_detail   = Column(Text)
    yield_pct         = Column(Numeric(5, 2))
    selectivity_pct   = Column(Numeric(5, 2))
    conversion_rate_pct = Column(Numeric(5, 2))
    raw_materials     = Column(JSONB)
    byproducts        = Column(JSONB)
    energy_consumption = Column(String(100))
    primary_reaction_id = Column(UUID, ForeignKey("chemical_reactions.id"))
    side_reactions    = Column(ARRAY(UUID))
    industrial_significance = Column(Text)
    annual_production = Column(String(50))
    production_rank   = Column(Integer)
    source_id         = Column(UUID, ForeignKey("data_sources.id"))
    confidence        = Column(Numeric(3, 2), default=0.50)
    created_at        = Column(DateTime, default=now)
    updated_at        = Column(DateTime, default=now, onupdate=now)

    substance        = relationship("Substance", back_populates="processes")
    primary_reaction = relationship("ChemicalReaction", back_populates="processes")


# ===========================================================================
# 表8：安全性数据
# ===========================================================================
class SafetyData(Base):
    __tablename__ = "safety_data"

    id                  = Column(UUID, primary_key=True, default=gen_uuid)
    substance_id        = Column(UUID, ForeignKey("substances.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    ghs_classifications = Column(JSONB)
    hazard_class        = Column(String(100))
    hazard_level        = Column(String(20))
    signal_word         = Column(String(20))     # Danger / Warning
    h_codes             = Column(ARRAY(Text))
    p_codes             = Column(ARRAY(Text))
    eu_h_codes          = Column(ARRAY(Text))
    ld50_oral           = Column(Numeric(12, 4)) # mg/kg
    ld50_dermal         = Column(Numeric(12, 4))
    lc50_inhalation     = Column(Numeric(12, 4)) # mg/L
    toxicity_route      = Column(String(50))
    toxicity_note       = Column(Text)
    oel                 = Column(String(100))
    mac                 = Column(String(100))    # 最高容许浓度 (中国)
    pc_twa              = Column(String(100))    # 时间加权平均容许浓度
    pc_stel             = Column(String(100))    # 短时间接触容许浓度
    flash_point         = Column(Numeric(8, 2))  # °C
    autoignition_temp   = Column(Numeric(8, 2))  # °C
    explosion_limits    = Column(JSONB)          # [{lower, upper, unit}]
    nfpa_health         = Column(Integer, CheckConstraint("nfpa_health BETWEEN 0 AND 4"))
    nfpa_fire           = Column(Integer, CheckConstraint("nfpa_fire BETWEEN 0 AND 4"))
    nfpa_reactivity     = Column(Integer, CheckConstraint("nfpa_reactivity BETWEEN 0 AND 4"))
    nfpa_special        = Column(String(10))
    storage_condition   = Column(Text)
    transport_info      = Column(Text)
    packing_group       = Column(String(10))
    un_number           = Column(String(10))
    source_id           = Column(UUID, ForeignKey("data_sources.id"))
    confidence          = Column(Numeric(3, 2), default=0.50)
    created_at          = Column(DateTime, default=now)
    updated_at          = Column(DateTime, default=now, onupdate=now)

    substance = relationship("Substance", back_populates="safety")


# ===========================================================================
# 表9：DEXPI/P&ID 设备关联
# ===========================================================================
class DexpiEquipment(Base):
    __tablename__ = "dexpi_equipment"

    id                = Column(UUID, primary_key=True, default=gen_uuid)
    substance_id      = Column(UUID, ForeignKey("substances.id", ondelete="CASCADE"), nullable=False, index=True)
    process_id        = Column(UUID, ForeignKey("industrial_processes.id"))
    dexpi_class       = Column(String(100), index=True)   # Reactor/DistillationColumn/HeatExchanger/...
    dexpi_stereotype  = Column(String(100))
    dexpi_version     = Column(String(10), default="2.0")
    equipment_tag     = Column(String(50))                 # P&ID 位号，如 R-101
    equipment_name_cn = Column(String(200))
    equipment_name_en = Column(String(200))
    material          = Column(String(200))                # 设备材质
    material_standard = Column(String(100))
    pipe_spec         = Column(JSONB)
    instrument_list   = Column(JSONB)
    operating_temp    = Column(Numeric(8, 2))
    operating_press   = Column(Numeric(10, 4))
    design_temp       = Column(Numeric(8, 2))
    design_press      = Column(Numeric(10, 4))
    pid_drawing       = Column(String(200))
    dexpi_xmi_path    = Column(String(300))
    dexpi_element_id  = Column(String(100))
    description_cn    = Column(Text)
    source_id         = Column(UUID, ForeignKey("data_sources.id"))
    created_at        = Column(DateTime, default=now)
    updated_at        = Column(DateTime, default=now, onupdate=now)

    substance = relationship("Substance", back_populates="dexpi_equipment_list")
    process   = relationship("IndustrialProcess")


# ===========================================================================
# 表10：数据来源
# ===========================================================================
class DataSource(Base):
    __tablename__ = "data_sources"

    id              = Column(UUID, primary_key=True, default=gen_uuid)
    name_cn         = Column(String(200))
    name_en         = Column(String(200), nullable=False)
    source_type     = Column(String(50), nullable=False)   # api/scrape/manual/reference
    base_url        = Column(String(500))
    api_version     = Column(String(20))
    access_method   = Column(String(50))                   # rest/sparql/ftp/file
    rate_limit      = Column(String(50))
    auth_required   = Column(Boolean, default=False)
    reliability     = Column(String(20))                   # high/medium/low
    last_fetched    = Column(DateTime)
    fetch_frequency = Column(String(30))                   # daily/weekly/monthly/once
    notes           = Column(Text)
    created_at      = Column(DateTime, default=now)


# ===========================================================================
# 表11：数据验证日志
# ===========================================================================
class DataValidation(Base):
    __tablename__ = "data_validations"

    id                  = Column(UUID, primary_key=True, default=gen_uuid)
    substance_id        = Column(UUID, ForeignKey("substances.id", ondelete="CASCADE"), nullable=False, index=True)
    table_name          = Column(String(50), nullable=False)
    record_id           = Column(UUID, nullable=False)
    property_name       = Column(String(50))
    source_a_id         = Column(UUID, ForeignKey("data_sources.id"))
    source_b_id         = Column(UUID, ForeignKey("data_sources.id"))
    value_a             = Column(Text)
    value_b             = Column(Text)
    deviation           = Column(Numeric(15, 6))
    deviation_pct       = Column(Numeric(8, 4))
    is_consistent       = Column(Boolean, index=True)
    resolution          = Column(String(50))   # preferred/merged/flagged/unresolved
    validator_notes     = Column(Text)
    confidence_adjustment = Column(Numeric(3, 2))
    created_at          = Column(DateTime, default=now)

    substance = relationship("Substance", back_populates="validations")


# ===========================================================================
# 表12：中国标准分类
# ===========================================================================
class ChineseStandard(Base):
    __tablename__ = "chinese_standards"

    id                = Column(UUID, primary_key=True, default=gen_uuid)
    substance_id      = Column(UUID, ForeignKey("substances.id", ondelete="CASCADE"), nullable=False, index=True)
    standard_type     = Column(String(50), nullable=False, index=True)  # gb_number/hazardous_chemicals_catalog/...
    standard_code     = Column(String(50))     # GB/T 3634.1-2006
    category_info     = Column(JSONB)
    is_hazardous      = Column(Boolean)
    hazard_category   = Column(String(100))
    permit_required   = Column(Boolean)
    key_monitored     = Column(Boolean)        # 是否重点监管危险化学品
    created_at        = Column(DateTime, default=now)
    updated_at        = Column(DateTime, default=now, onupdate=now)

    substance = relationship("Substance", back_populates="standards")
