"""${message}

创建工业化学物质数据库全部 12 张核心表。

Revision ID: 001
Revises: None
Create Date: 2026-06-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 启用扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ===================================================================
    # 表10：data_sources（先建，被其他表 FK 引用）
    # ===================================================================
    op.create_table(
        "data_sources",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name_cn", sa.String(200)),
        sa.Column("name_en", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("base_url", sa.String(500)),
        sa.Column("api_version", sa.String(20)),
        sa.Column("access_method", sa.String(50)),
        sa.Column("rate_limit", sa.String(50)),
        sa.Column("auth_required", sa.Boolean, default=False),
        sa.Column("reliability", sa.String(20)),
        sa.Column("last_fetched", sa.DateTime(timezone=True)),
        sa.Column("fetch_frequency", sa.String(30)),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ===================================================================
    # 表1：substances
    # ===================================================================
    op.create_table(
        "substances",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("cas_number", sa.String(20), unique=True, nullable=False),
        sa.Column("inchikey", sa.String(27)),
        sa.Column("molecular_formula", sa.String(100)),
        sa.Column("molecular_weight", sa.Numeric(10, 4)),
        sa.Column("smiles", sa.String(500)),
        sa.Column("inchi", sa.Text),
        sa.Column("name_cn", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200)),
        sa.Column("iupac_name_cn", sa.String(500)),
        sa.Column("iupac_name_en", sa.String(500)),
        sa.Column("substance_type", sa.String(50)),
        sa.Column("chemical_class", sa.String(100)),
        sa.Column("state_at_25c", sa.String(20)),
        sa.Column("exact_mass", sa.Numeric(10, 6)),
        sa.Column("monoisotopic_mass", sa.Numeric(10, 6)),
        sa.Column("charge", sa.Integer),
        sa.Column("complexity", sa.Integer),
        sa.Column("data_quality", sa.String(20), server_default="pending"),
        sa.Column("overall_confidence", sa.Numeric(3, 2), server_default="0.00"),
        sa.Column("source_id", UUID, sa.ForeignKey("data_sources.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        # embedding column for pgvector — added via raw SQL for vector type support
    )
    op.execute("ALTER TABLE substances ADD COLUMN embedding vector(768)")
    op.create_index("idx_substances_cas", "substances", ["cas_number"])
    op.create_index("idx_substances_name_cn", "substances", ["name_cn"])
    op.create_index("idx_substances_name_en", "substances", ["name_en"])
    op.create_index("idx_substances_formula", "substances", ["molecular_formula"])
    op.create_index("idx_substances_type", "substances", ["substance_type"])
    op.create_index("idx_substances_quality", "substances", ["data_quality"])
    op.execute(
        "CREATE INDEX idx_substances_name_cn_trgm ON substances USING gin (name_cn gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX idx_substances_name_en_trgm ON substances USING gin (name_en gin_trgm_ops)"
    )

    # ===================================================================
    # 表2：substance_names
    # ===================================================================
    op.create_table(
        "substance_names",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("substance_id", UUID, sa.ForeignKey("substances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="zh"),
        sa.Column("name_type", sa.String(50), nullable=False, server_default="synonym"),
        sa.Column("is_preferred", sa.Boolean, default=False),
        sa.Column("source_id", UUID, sa.ForeignKey("data_sources.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_substance_names_substance", "substance_names", ["substance_id"])
    op.create_index("idx_substance_names_name", "substance_names", ["name"])
    op.create_index("idx_substance_names_lang", "substance_names", ["language"])
    op.execute(
        "CREATE INDEX idx_substance_names_name_trgm ON substance_names USING gin (name gin_trgm_ops)"
    )

    # ===================================================================
    # 表3：physicochemical_properties
    # ===================================================================
    op.create_table(
        "physicochemical_properties",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("substance_id", UUID, sa.ForeignKey("substances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_type", sa.String(50), nullable=False),
        sa.Column("value", sa.Numeric(15, 6)),
        sa.Column("value_min", sa.Numeric(15, 6)),
        sa.Column("value_max", sa.Numeric(15, 6)),
        sa.Column("unit", sa.String(30)),
        sa.Column("value_text", sa.Text),
        sa.Column("condition_temp", sa.Numeric(8, 2)),
        sa.Column("condition_pressure", sa.Numeric(8, 2)),
        sa.Column("condition_ph", sa.Numeric(4, 2)),
        sa.Column("reference", sa.Text),
        sa.Column("confidence", sa.Numeric(3, 2), server_default="0.50"),
        sa.Column("source_id", UUID, sa.ForeignKey("data_sources.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("value IS NOT NULL OR value_text IS NOT NULL", name="at_least_one_value"),
    )
    op.create_index("idx_physprop_substance", "physicochemical_properties", ["substance_id"])
    op.create_index("idx_physprop_type", "physicochemical_properties", ["property_type"])
    op.create_index("idx_physprop_substance_type", "physicochemical_properties", ["substance_id", "property_type"])

    # ===================================================================
    # 表5：chemical_reactions (先于 thermodynamic_data 和 reaction_participants)
    # ===================================================================
    op.create_table(
        "chemical_reactions",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("equation_text", sa.Text, nullable=False),
        sa.Column("equation_html", sa.Text),
        sa.Column("reaction_type", sa.String(50)),
        sa.Column("reversible", sa.Boolean, default=False),
        sa.Column("delta_h", sa.Numeric(12, 4)),
        sa.Column("delta_h_unit", sa.String(20), server_default="kJ/mol"),
        sa.Column("delta_s", sa.Numeric(12, 4)),
        sa.Column("delta_g", sa.Numeric(12, 4)),
        sa.Column("equilibrium_constant", sa.Numeric(20, 10)),
        sa.Column("eq_constant_temp", sa.Numeric(8, 2)),
        sa.Column("is_industrial", sa.Boolean, default=False),
        sa.Column("name_cn", sa.String(200)),
        sa.Column("name_en", sa.String(200)),
        sa.Column("description", sa.Text),
        sa.Column("source_id", UUID, sa.ForeignKey("data_sources.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ===================================================================
    # 表4：thermodynamic_data
    # ===================================================================
    op.create_table(
        "thermodynamic_data",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("substance_id", UUID, sa.ForeignKey("substances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column("value", sa.Numeric(15, 4), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("phase", sa.String(20)),
        sa.Column("temperature", sa.Numeric(8, 2)),
        sa.Column("pressure", sa.Numeric(10, 4)),
        sa.Column("standard_state", sa.Boolean, default=True),
        sa.Column("reaction_id", UUID, sa.ForeignKey("chemical_reactions.id")),
        sa.Column("pre_exponential", sa.Numeric(20, 6)),
        sa.Column("activation_energy", sa.Numeric(10, 3)),
        sa.Column("rate_constant", sa.Numeric(20, 10)),
        sa.Column("reference", sa.Text),
        sa.Column("uncertainty", sa.String(50)),
        sa.Column("confidence", sa.Numeric(3, 2), server_default="0.50"),
        sa.Column("source_id", UUID, sa.ForeignKey("data_sources.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_thermo_substance", "thermodynamic_data", ["substance_id"])
    op.create_index("idx_thermo_type", "thermodynamic_data", ["data_type"])
    op.create_index("idx_thermo_reaction", "thermodynamic_data", ["reaction_id"])

    # ===================================================================
    # 表6：reaction_participants
    # ===================================================================
    op.create_table(
        "reaction_participants",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("reaction_id", UUID, sa.ForeignKey("chemical_reactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("substance_id", UUID, sa.ForeignKey("substances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("stoichiometry", sa.Numeric(8, 4)),
        sa.Column("phase", sa.String(10)),
        sa.Column("is_catalyst", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("reaction_id", "substance_id", "role", name="uq_rxn_participant"),
    )
    op.create_index("idx_rxnpart_reaction", "reaction_participants", ["reaction_id"])
    op.create_index("idx_rxnpart_substance", "reaction_participants", ["substance_id"])

    # ===================================================================
    # 表7：industrial_processes
    # ===================================================================
    op.create_table(
        "industrial_processes",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("substance_id", UUID, sa.ForeignKey("substances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("process_name_cn", sa.String(300), nullable=False),
        sa.Column("process_name_en", sa.String(300)),
        sa.Column("description_cn", sa.Text),
        sa.Column("description_en", sa.Text),
        sa.Column("process_flow", sa.Text),
        sa.Column("temperature_min", sa.Numeric(8, 2)),
        sa.Column("temperature_max", sa.Numeric(8, 2)),
        sa.Column("temperature_opt", sa.Numeric(8, 2)),
        sa.Column("pressure_min", sa.Numeric(10, 4)),
        sa.Column("pressure_max", sa.Numeric(10, 4)),
        sa.Column("pressure_opt", sa.Numeric(10, 4)),
        sa.Column("catalyst", sa.String(500)),
        sa.Column("catalyst_detail", sa.Text),
        sa.Column("yield_pct", sa.Numeric(5, 2)),
        sa.Column("selectivity_pct", sa.Numeric(5, 2)),
        sa.Column("conversion_rate_pct", sa.Numeric(5, 2)),
        sa.Column("raw_materials", JSONB),
        sa.Column("byproducts", JSONB),
        sa.Column("energy_consumption", sa.String(100)),
        sa.Column("primary_reaction_id", UUID, sa.ForeignKey("chemical_reactions.id")),
        sa.Column("side_reactions", ARRAY(UUID)),
        sa.Column("industrial_significance", sa.Text),
        sa.Column("annual_production", sa.String(50)),
        sa.Column("production_rank", sa.Integer),
        sa.Column("source_id", UUID, sa.ForeignKey("data_sources.id")),
        sa.Column("confidence", sa.Numeric(3, 2), server_default="0.50"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_indproc_substance", "industrial_processes", ["substance_id"])
    op.create_index("idx_indproc_name", "industrial_processes", ["process_name_cn"])

    # ===================================================================
    # 表8：safety_data
    # ===================================================================
    op.create_table(
        "safety_data",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("substance_id", UUID, sa.ForeignKey("substances.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("ghs_classifications", JSONB),
        sa.Column("hazard_class", sa.String(100)),
        sa.Column("hazard_level", sa.String(20)),
        sa.Column("signal_word", sa.String(20)),
        sa.Column("h_codes", ARRAY(sa.Text)),
        sa.Column("p_codes", ARRAY(sa.Text)),
        sa.Column("eu_h_codes", ARRAY(sa.Text)),
        sa.Column("ld50_oral", sa.Numeric(12, 4)),
        sa.Column("ld50_dermal", sa.Numeric(12, 4)),
        sa.Column("lc50_inhalation", sa.Numeric(12, 4)),
        sa.Column("toxicity_route", sa.String(50)),
        sa.Column("toxicity_note", sa.Text),
        sa.Column("oel", sa.String(100)),
        sa.Column("mac", sa.String(100)),
        sa.Column("pc_twa", sa.String(100)),
        sa.Column("pc_stel", sa.String(100)),
        sa.Column("flash_point", sa.Numeric(8, 2)),
        sa.Column("autoignition_temp", sa.Numeric(8, 2)),
        sa.Column("explosion_limits", JSONB),
        sa.Column("nfpa_health", sa.Integer),
        sa.Column("nfpa_fire", sa.Integer),
        sa.Column("nfpa_reactivity", sa.Integer),
        sa.Column("nfpa_special", sa.String(10)),
        sa.Column("storage_condition", sa.Text),
        sa.Column("transport_info", sa.Text),
        sa.Column("packing_group", sa.String(10)),
        sa.Column("un_number", sa.String(10)),
        sa.Column("source_id", UUID, sa.ForeignKey("data_sources.id")),
        sa.Column("confidence", sa.Numeric(3, 2), server_default="0.50"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_safety_substance", "safety_data", ["substance_id"])

    # ===================================================================
    # 表9：dexpi_equipment
    # ===================================================================
    op.create_table(
        "dexpi_equipment",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("substance_id", UUID, sa.ForeignKey("substances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("process_id", UUID, sa.ForeignKey("industrial_processes.id")),
        sa.Column("dexpi_class", sa.String(100)),
        sa.Column("dexpi_stereotype", sa.String(100)),
        sa.Column("dexpi_version", sa.String(10), server_default="2.0"),
        sa.Column("equipment_tag", sa.String(50)),
        sa.Column("equipment_name_cn", sa.String(200)),
        sa.Column("equipment_name_en", sa.String(200)),
        sa.Column("material", sa.String(200)),
        sa.Column("material_standard", sa.String(100)),
        sa.Column("pipe_spec", JSONB),
        sa.Column("instrument_list", JSONB),
        sa.Column("operating_temp", sa.Numeric(8, 2)),
        sa.Column("operating_press", sa.Numeric(10, 4)),
        sa.Column("design_temp", sa.Numeric(8, 2)),
        sa.Column("design_press", sa.Numeric(10, 4)),
        sa.Column("pid_drawing", sa.String(200)),
        sa.Column("dexpi_xmi_path", sa.String(300)),
        sa.Column("dexpi_element_id", sa.String(100)),
        sa.Column("description_cn", sa.Text),
        sa.Column("source_id", UUID, sa.ForeignKey("data_sources.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_dexpi_substance", "dexpi_equipment", ["substance_id"])
    op.create_index("idx_dexpi_process", "dexpi_equipment", ["process_id"])
    op.create_index("idx_dexpi_class", "dexpi_equipment", ["dexpi_class"])
    op.create_index("idx_dexpi_tag", "dexpi_equipment", ["equipment_tag"])

    # ===================================================================
    # 表11：data_validations
    # ===================================================================
    op.create_table(
        "data_validations",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("substance_id", UUID, sa.ForeignKey("substances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_name", sa.String(50), nullable=False),
        sa.Column("record_id", UUID, nullable=False),
        sa.Column("property_name", sa.String(50)),
        sa.Column("source_a_id", UUID, sa.ForeignKey("data_sources.id")),
        sa.Column("source_b_id", UUID, sa.ForeignKey("data_sources.id")),
        sa.Column("value_a", sa.Text),
        sa.Column("value_b", sa.Text),
        sa.Column("deviation", sa.Numeric(15, 6)),
        sa.Column("deviation_pct", sa.Numeric(8, 4)),
        sa.Column("is_consistent", sa.Boolean),
        sa.Column("resolution", sa.String(50)),
        sa.Column("validator_notes", sa.Text),
        sa.Column("confidence_adjustment", sa.Numeric(3, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_val_substance", "data_validations", ["substance_id"])
    op.create_index("idx_val_consistent", "data_validations", ["is_consistent"])

    # ===================================================================
    # 表12：chinese_standards
    # ===================================================================
    op.create_table(
        "chinese_standards",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("substance_id", UUID, sa.ForeignKey("substances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("standard_type", sa.String(50), nullable=False),
        sa.Column("standard_code", sa.String(50)),
        sa.Column("category_info", JSONB),
        sa.Column("is_hazardous", sa.Boolean),
        sa.Column("hazard_category", sa.String(100)),
        sa.Column("permit_required", sa.Boolean),
        sa.Column("key_monitored", sa.Boolean),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_cnstd_substance", "chinese_standards", ["substance_id"])
    op.create_index("idx_cnstd_type", "chinese_standards", ["standard_type"])


def downgrade() -> None:
    op.drop_table("chinese_standards")
    op.drop_table("data_validations")
    op.drop_table("dexpi_equipment")
    op.drop_table("safety_data")
    op.drop_table("industrial_processes")
    op.drop_table("reaction_participants")
    op.drop_table("thermodynamic_data")
    op.drop_table("chemical_reactions")
    op.drop_table("physicochemical_properties")
    op.drop_table("substance_names")
    op.drop_table("substances")
    op.drop_table("data_sources")
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
