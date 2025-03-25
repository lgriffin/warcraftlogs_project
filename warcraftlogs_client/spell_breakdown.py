from collections import defaultdict

class SpellBreakdown:
    @staticmethod
    def calculate(healing_events):
        spells = defaultdict(int)
        print(f"Total healing events received: {len(healing_events)}")

        for event in healing_events:
            ability_id = event.get("abilityGameID")
            amount = event.get("amount")

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
        entries = raw_table.get("data", {}).get("entries", [])

        id_to_name = {}
        id_to_casts = {}

        for entry in entries:
            guid = entry.get("guid")
            name = entry.get("name")
            casts = entry.get("total")  # Total number of times cast (usually hitCount)

            if guid and name:
                id_to_name[guid] = name
                id_to_casts[guid] = casts
            # Manually patch missing spell names (if not provided by the API)
        id_to_name[17543] = "Fire Protection"
        id_to_name[27805] = "Holy Nova"
        id_to_name[15290] = "Vampiric Embrace"

        
        return id_to_name, id_to_casts, entries
    
    @staticmethod
    def get_fear_ward_usage(cast_entries):
        for entry in cast_entries:
            if entry.get("guid") == 6346:
                return {
                    "spell": "Fear Ward",
                    "casts": entry.get("total", 0)
                }
        return None

    @staticmethod
    def calculate_dispels(cast_entries):
        dispel_ids = {
            988: "Dispel Magic",
            552: "Abolish Disease"
        }

        dispels = {}
        for entry in cast_entries:
            spell_id = entry.get("guid")
            if spell_id in dispel_ids:
                dispels[dispel_ids[spell_id]] = entry.get("total", 0)

        return dispels






