from collections import defaultdict

class SpellBreakdown:
    @staticmethod
    def calculate(healing_events):
        spells = defaultdict(int)
        print(f"Total healing events received: {len(healing_events)}")

        for event in healing_events:
            ability_id = event.get("abilityGameID")
            amount = event.get("amount")

            # Exclude unwanted abilities
            if ability_id == 20343:
                continue

            if ability_id is not None and amount is not None:
                spells[ability_id] += amount
            else:
                print(f"Skipping event: missing abilityGameID or amount: {event}")

        return dict(spells)

    @staticmethod
    def get_spell_id_to_name_map(client, report_id, source_id):
        query = f"""
        {{
        reportData {{
            report(code: "{report_id}") {{
                table(dataType: Casts, sourceID: {source_id}, startTime: 0, endTime: 999999999)
            }}
        }}
        }}
        """
        result = client.run_query(query)
        raw_table = result["data"]["reportData"]["report"]["table"]

        entries = []
        if isinstance(raw_table, dict):
            if "data" in raw_table and "entries" in raw_table["data"]:
                entries = raw_table["data"]["entries"]
            elif "entries" in raw_table:
                entries = raw_table["entries"]

        id_to_name = {}
        id_to_casts = {}

        spell_id_aliases = {
            27801: 27805,    # Holy Nova
            19943: 19993,    # Flash of Light
            20930: 25903,    # Holy Shock variant
            25914: 25903,    # Another Holy Shock variant
            10329: 19968     # Holy Light
        }

        for entry in entries:
            guid = entry.get("guid")
            name = entry.get("name")
            canonical_guid = spell_id_aliases.get(guid, guid)

            if guid == 20343:
                continue

            casts = entry.get("hitCount", entry.get("total", 0))

            if canonical_guid and name:
                id_to_name[canonical_guid] = name
                id_to_casts[canonical_guid] = id_to_casts.get(canonical_guid, 0) + casts

        # Manually patch known IDs
        id_to_name[17543] = "Fire Protection"
        id_to_name[27805] = "Holy Nova"
        id_to_name[15290] = "Vampiric Embrace"
        id_to_name[19968] = "Holy Light"
        id_to_name[19993] = "Flash of Light"
        id_to_name[25903] = "Holy Shock"
        id_to_name[7242]  = "Shadow Protection"
        id_to_name[10901] = "Power Word: Shield"

        return id_to_name, id_to_casts, entries

    @staticmethod
    def get_resources_used(cast_entries):
        resources = {
            17531: "Major Mana Potion",
            27869: "Dark Rune"
        }

        used = {}
        for entry in cast_entries:
            spell_id = entry.get("guid")
            if spell_id in resources:
                used[resources[spell_id]] = entry.get("hitCount") or entry.get("total", 0)

        return used

    @staticmethod
    def get_fear_ward_usage(cast_entries):
        for entry in cast_entries:
            if entry.get("guid") == 6346:
                return {
                    "spell": "Fear Ward",
                    "casts": entry.get("total") or entry.get("hitCount", 0)
                }
        return None

    @staticmethod
    def calculate_dispels(cast_entries, class_type):
        dispel_ids = {
            988: "Dispel Magic",         # Priest
            552: "Abolish Disease",      # Priest
            4987: "Cleanse",             # Paladin
            2782: "Remove Curse",        # Druid
            2893: "Abolish Poison"       # Druid
        }

        dispels = {}
        for entry in cast_entries:
            spell_id = entry.get("guid")
            if spell_id in dispel_ids:
                dispels[dispel_ids[spell_id]] = entry.get("total") or entry.get("hitCount", 0)

        return dispels
