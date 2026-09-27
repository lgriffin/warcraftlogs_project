"""Raid schema for the RaidRepository methods.

The tables the Postgres backend of ``RaidRepository`` touches, mirroring the desktop SQLite schema
(``wcl_store.sqlite``). Raid groups and the desktop-only query tables come in later revisions.

Revision ID: 0001
Revises:
Create Date: 2026-09-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "characters",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("player_class", sa.Text(), nullable=False),
        sa.Column("first_seen", sa.Text(), nullable=False),
        sa.Column("last_seen", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_characters")),
    )
    op.create_index("uq_characters_lower_name", "characters", [sa.literal_column("lower(name)")], unique=True)
    op.create_table(
        "player_pages",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("server", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.Text(),
            server_default=sa.text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_pages")),
    )
    op.create_index(
        "uq_player_pages_lower_name_server_region",
        "player_pages",
        [sa.literal_column("lower(name)"), sa.literal_column("lower(server)"), sa.literal_column("lower(region)")],
        unique=True,
    )
    op.create_table(
        "raids",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("report_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("raid_date", sa.Text(), nullable=False),
        sa.Column("start_time", sa.BigInteger(), nullable=False),
        sa.Column("end_time", sa.BigInteger(), nullable=True),
        sa.Column(
            "imported_at",
            sa.Text(),
            server_default=sa.text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), server_default="guild", nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("raid_size", sa.Integer(), nullable=True),
        sa.Column("zone", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raids")),
        sa.UniqueConstraint("report_id", name=op.f("uq_raids_report_id")),
    )
    op.create_index(op.f("ix_raids_raid_date"), "raids", ["raid_date"], unique=False)
    op.create_index(op.f("ix_raids_source"), "raids", ["source"], unique=False)
    op.create_table(
        "role_overrides",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("character_name", sa.Text(), nullable=False),
        sa.Column("report_id", sa.Text(), server_default="", nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.Text(),
            server_default=sa.text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('healer', 'tank', 'melee', 'ranged', 'dps')", name=op.f("ck_role_overrides_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_overrides")),
    )
    op.create_index(
        "uq_role_overrides_lower_character_name_report_id",
        "role_overrides",
        [sa.literal_column("lower(character_name)"), "report_id"],
        unique=True,
    )
    op.create_table(
        "cancelled_cast_spells",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("spell_id", sa.BigInteger(), nullable=False),
        sa.Column("spell_name", sa.Text(), server_default="", nullable=False),
        sa.Column("total_casts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cancelled_casts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cancel_rate", sa.Float(), server_default="0", nullable=False),
        sa.Column("timestamps", sa.Text(), nullable=True),
        sa.Column("correlations", sa.Text(), nullable=True),
        sa.Column("next_casts", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], name=op.f("fk_cancelled_cast_spells_character_id_characters")
        ),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"], name=op.f("fk_cancelled_cast_spells_raid_id_raids")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cancelled_cast_spells")),
        sa.UniqueConstraint(
            "character_id", "raid_id", "spell_id", name=op.f("uq_cancelled_cast_spells_character_id_raid_id_spell_id")
        ),
    )
    op.create_index(op.f("ix_cancelled_cast_spells_raid_id"), "cancelled_cast_spells", ["raid_id"], unique=False)
    op.create_table(
        "cancelled_casts",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("total_casts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cancelled_casts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cancel_rate", sa.Float(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], name=op.f("fk_cancelled_casts_character_id_characters")
        ),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"], name=op.f("fk_cancelled_casts_raid_id_raids")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cancelled_casts")),
        sa.UniqueConstraint("character_id", "raid_id", name=op.f("uq_cancelled_casts_character_id_raid_id")),
    )
    op.create_index(op.f("ix_cancelled_casts_raid_id"), "cancelled_casts", ["raid_id"], unique=False)
    op.create_table(
        "consumable_usage",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("consumable_name", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("timestamps", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], name=op.f("fk_consumable_usage_character_id_characters")
        ),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"], name=op.f("fk_consumable_usage_raid_id_raids")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consumable_usage")),
        sa.UniqueConstraint(
            "character_id",
            "raid_id",
            "consumable_name",
            name=op.f("uq_consumable_usage_character_id_raid_id_consumable_name"),
        ),
    )
    op.create_index(op.f("ix_consumable_usage_character_id"), "consumable_usage", ["character_id"], unique=False)
    op.create_index(op.f("ix_consumable_usage_raid_id"), "consumable_usage", ["raid_id"], unique=False)
    op.create_table(
        "dps_performance",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("total_damage", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("active_time_percent", sa.Float(), server_default="0", nullable=True),
        sa.CheckConstraint("role IN ('melee', 'ranged')", name=op.f("ck_dps_performance_role")),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], name=op.f("fk_dps_performance_character_id_characters")
        ),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"], name=op.f("fk_dps_performance_raid_id_raids")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dps_performance")),
        sa.UniqueConstraint("character_id", "raid_id", name=op.f("uq_dps_performance_character_id_raid_id")),
    )
    op.create_index(op.f("ix_dps_performance_character_id"), "dps_performance", ["character_id"], unique=False)
    op.create_index(op.f("ix_dps_performance_raid_id"), "dps_performance", ["raid_id"], unique=False)
    op.create_table(
        "encounters",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("start_time", sa.BigInteger(), nullable=False),
        sa.Column("end_time", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("boss_events", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["raid_id"], ["raids.id"], name=op.f("fk_encounters_raid_id_raids"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_encounters")),
        sa.UniqueConstraint(
            "raid_id", "encounter_id", "start_time", name=op.f("uq_encounters_raid_id_encounter_id_start_time")
        ),
    )
    op.create_table(
        "healer_performance",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("total_healing", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_overhealing", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("overheal_percent", sa.Float(), server_default="0", nullable=False),
        sa.Column("fear_ward_casts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_dispels", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active_time_percent", sa.Float(), server_default="0", nullable=True),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], name=op.f("fk_healer_performance_character_id_characters")
        ),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"], name=op.f("fk_healer_performance_raid_id_raids")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_healer_performance")),
        sa.UniqueConstraint("character_id", "raid_id", name=op.f("uq_healer_performance_character_id_raid_id")),
    )
    op.create_index(op.f("ix_healer_performance_character_id"), "healer_performance", ["character_id"], unique=False)
    op.create_index(op.f("ix_healer_performance_raid_id"), "healer_performance", ["raid_id"], unique=False)
    op.create_table(
        "interrupt_usage",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("spell_id", sa.BigInteger(), nullable=False),
        sa.Column("spell_name", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("timestamps", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], name=op.f("fk_interrupt_usage_character_id_characters")
        ),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"], name=op.f("fk_interrupt_usage_raid_id_raids")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interrupt_usage")),
        sa.UniqueConstraint(
            "character_id", "raid_id", "spell_id", name=op.f("uq_interrupt_usage_character_id_raid_id_spell_id")
        ),
    )
    op.create_index(op.f("ix_interrupt_usage_character_id"), "interrupt_usage", ["character_id"], unique=False)
    op.create_index(op.f("ix_interrupt_usage_raid_id"), "interrupt_usage", ["raid_id"], unique=False)
    op.create_table(
        "player_page_logs",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("player_page_id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column("zone", sa.Text(), nullable=True),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("start_time", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.Text(),
            server_default=sa.text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('added', 'dismissed')", name=op.f("ck_player_page_logs_status")),
        sa.ForeignKeyConstraint(
            ["player_page_id"],
            ["player_pages.id"],
            name=op.f("fk_player_page_logs_player_page_id_player_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_page_logs")),
        sa.UniqueConstraint("player_page_id", "report_id", name=op.f("uq_player_page_logs_player_page_id_report_id")),
    )
    op.create_table(
        "role_override_raids",
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("character_name", sa.Text(), nullable=False),
        sa.Column("detected_role", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"], name=op.f("fk_role_override_raids_raid_id_raids")),
    )
    op.create_index(
        "uq_role_override_raids_raid_id_lower_character_name",
        "role_override_raids",
        ["raid_id", sa.literal_column("lower(character_name)")],
        unique=True,
    )
    op.create_table(
        "tank_performance",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("total_damage_taken", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_mitigated", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("mitigation_percent", sa.Float(), server_default="0", nullable=False),
        sa.Column("active_time_percent", sa.Float(), server_default="0", nullable=True),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], name=op.f("fk_tank_performance_character_id_characters")
        ),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"], name=op.f("fk_tank_performance_raid_id_raids")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tank_performance")),
        sa.UniqueConstraint("character_id", "raid_id", name=op.f("uq_tank_performance_character_id_raid_id")),
    )
    op.create_index(op.f("ix_tank_performance_character_id"), "tank_performance", ["character_id"], unique=False)
    op.create_index(op.f("ix_tank_performance_raid_id"), "tank_performance", ["raid_id"], unique=False)
    op.create_table(
        "aura_uptime",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("encounter_row_id", sa.Integer(), nullable=False),
        sa.Column("spell_id", sa.BigInteger(), nullable=False),
        sa.Column("spell_name", sa.Text(), nullable=False),
        sa.Column("uptime_percent", sa.Float(), server_default="0", nullable=False),
        sa.Column("bands_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["encounter_row_id"],
            ["encounters.id"],
            name=op.f("fk_aura_uptime_encounter_row_id_encounters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["raid_id"], ["raids.id"], name=op.f("fk_aura_uptime_raid_id_raids"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_aura_uptime")),
        sa.UniqueConstraint(
            "raid_id", "encounter_row_id", "spell_id", name=op.f("uq_aura_uptime_raid_id_encounter_row_id_spell_id")
        ),
    )
    op.create_table(
        "dps_abilities",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("dps_performance_id", sa.Integer(), nullable=False),
        sa.Column("spell_id", sa.BigInteger(), nullable=False),
        sa.Column("spell_name", sa.Text(), nullable=False),
        sa.Column("casts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_damage", sa.BigInteger(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["dps_performance_id"],
            ["dps_performance.id"],
            name=op.f("fk_dps_abilities_dps_performance_id_dps_performance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dps_abilities")),
    )
    op.create_index(op.f("ix_dps_abilities_dps_performance_id"), "dps_abilities", ["dps_performance_id"], unique=False)
    op.create_table(
        "encounter_performance",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("encounter_row_id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("total_damage", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("total_healing", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("total_damage_taken", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("active_time_percent", sa.Float(), server_default="0", nullable=True),
        sa.CheckConstraint(
            "role IN ('healer', 'tank', 'melee', 'ranged', 'unknown')", name=op.f("ck_encounter_performance_role")
        ),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], name=op.f("fk_encounter_performance_character_id_characters")
        ),
        sa.ForeignKeyConstraint(
            ["encounter_row_id"],
            ["encounters.id"],
            name=op.f("fk_encounter_performance_encounter_row_id_encounters"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_encounter_performance")),
        sa.UniqueConstraint(
            "encounter_row_id", "character_id", name=op.f("uq_encounter_performance_encounter_row_id_character_id")
        ),
    )
    op.create_table(
        "healer_spells",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("healer_performance_id", sa.Integer(), nullable=False),
        sa.Column("spell_id", sa.BigInteger(), nullable=False),
        sa.Column("spell_name", sa.Text(), nullable=False),
        sa.Column("casts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_healing", sa.BigInteger(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["healer_performance_id"],
            ["healer_performance.id"],
            name=op.f("fk_healer_spells_healer_performance_id_healer_performance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_healer_spells")),
    )
    op.create_index(
        op.f("ix_healer_spells_healer_performance_id"), "healer_spells", ["healer_performance_id"], unique=False
    )
    op.create_table(
        "tank_abilities",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("tank_performance_id", sa.Integer(), nullable=False),
        sa.Column("spell_id", sa.BigInteger(), nullable=False),
        sa.Column("spell_name", sa.Text(), nullable=False),
        sa.Column("casts", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["tank_performance_id"],
            ["tank_performance.id"],
            name=op.f("fk_tank_abilities_tank_performance_id_tank_performance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tank_abilities")),
    )
    op.create_index(
        op.f("ix_tank_abilities_tank_performance_id"), "tank_abilities", ["tank_performance_id"], unique=False
    )
    op.create_table(
        "tank_damage_taken",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("tank_performance_id", sa.Integer(), nullable=False),
        sa.Column("spell_id", sa.BigInteger(), nullable=False),
        sa.Column("spell_name", sa.Text(), nullable=False),
        sa.Column("hits", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["tank_performance_id"],
            ["tank_performance.id"],
            name=op.f("fk_tank_damage_taken_tank_performance_id_tank_performance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tank_damage_taken")),
    )
    op.create_index(
        op.f("ix_tank_damage_taken_tank_performance_id"), "tank_damage_taken", ["tank_performance_id"], unique=False
    )
    op.create_table(
        "totem_uptime",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("encounter_row_id", sa.Integer(), nullable=False),
        sa.Column("spell_id", sa.BigInteger(), nullable=False),
        sa.Column("spell_name", sa.Text(), nullable=False),
        sa.Column("uptime_percent", sa.Float(), server_default="0", nullable=False),
        sa.Column("bands_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["encounter_row_id"],
            ["encounters.id"],
            name=op.f("fk_totem_uptime_encounter_row_id_encounters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["raid_id"], ["raids.id"], name=op.f("fk_totem_uptime_raid_id_raids"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_totem_uptime")),
        sa.UniqueConstraint(
            "raid_id", "encounter_row_id", "spell_id", name=op.f("uq_totem_uptime_raid_id_encounter_row_id_spell_id")
        ),
    )


def downgrade() -> None:
    op.drop_table("totem_uptime")
    op.drop_index(op.f("ix_tank_damage_taken_tank_performance_id"), table_name="tank_damage_taken")
    op.drop_table("tank_damage_taken")
    op.drop_index(op.f("ix_tank_abilities_tank_performance_id"), table_name="tank_abilities")
    op.drop_table("tank_abilities")
    op.drop_index(op.f("ix_healer_spells_healer_performance_id"), table_name="healer_spells")
    op.drop_table("healer_spells")
    op.drop_table("encounter_performance")
    op.drop_index(op.f("ix_dps_abilities_dps_performance_id"), table_name="dps_abilities")
    op.drop_table("dps_abilities")
    op.drop_table("aura_uptime")
    op.drop_index(op.f("ix_tank_performance_raid_id"), table_name="tank_performance")
    op.drop_index(op.f("ix_tank_performance_character_id"), table_name="tank_performance")
    op.drop_table("tank_performance")
    op.drop_index("uq_role_override_raids_raid_id_lower_character_name", table_name="role_override_raids")
    op.drop_table("role_override_raids")
    op.drop_table("player_page_logs")
    op.drop_index(op.f("ix_interrupt_usage_raid_id"), table_name="interrupt_usage")
    op.drop_index(op.f("ix_interrupt_usage_character_id"), table_name="interrupt_usage")
    op.drop_table("interrupt_usage")
    op.drop_index(op.f("ix_healer_performance_raid_id"), table_name="healer_performance")
    op.drop_index(op.f("ix_healer_performance_character_id"), table_name="healer_performance")
    op.drop_table("healer_performance")
    op.drop_table("encounters")
    op.drop_index(op.f("ix_dps_performance_raid_id"), table_name="dps_performance")
    op.drop_index(op.f("ix_dps_performance_character_id"), table_name="dps_performance")
    op.drop_table("dps_performance")
    op.drop_index(op.f("ix_consumable_usage_raid_id"), table_name="consumable_usage")
    op.drop_index(op.f("ix_consumable_usage_character_id"), table_name="consumable_usage")
    op.drop_table("consumable_usage")
    op.drop_index(op.f("ix_cancelled_casts_raid_id"), table_name="cancelled_casts")
    op.drop_table("cancelled_casts")
    op.drop_index(op.f("ix_cancelled_cast_spells_raid_id"), table_name="cancelled_cast_spells")
    op.drop_table("cancelled_cast_spells")
    op.drop_index("uq_role_overrides_lower_character_name_report_id", table_name="role_overrides")
    op.drop_table("role_overrides")
    op.drop_index(op.f("ix_raids_source"), table_name="raids")
    op.drop_index(op.f("ix_raids_raid_date"), table_name="raids")
    op.drop_table("raids")
    op.drop_index("uq_player_pages_lower_name_server_region", table_name="player_pages")
    op.drop_table("player_pages")
    op.drop_index("uq_characters_lower_name", table_name="characters")
    op.drop_table("characters")
