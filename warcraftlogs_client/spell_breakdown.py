from collections import defaultdict

class SpellBreakdown:
    spell_id_aliases = {
        27801: 27805, 23458: 27805, 27803: 27805,
        19943: 19993, 20930: 25903, 25914: 25903, 10329: 19968,
        20569: 15663, 15754: 15663, 19983: 15663, 19632: 15663, 20605: 15663,
        20602: 23462, 19627: 11351,
        -4: 1, -32: 1,
        22336: 21077, 24668: 21077, 19728: 21077,
        22665: 20741,
        22985: 22979, 22980: 22979,
        19644: 19730, 22591: 19730,
        24333: 24317, 15502: 24317, 11597: 24317,
        19460: 20603,
        369330: 19717
    }
    @staticmethod
    def calculate(healing_events):
        spells = defaultdict(int)
        print(f"Total healing events received: {len(healing_events)}")

        for event in healing_events:
            ability_id = event.get("abilityGameID")
            amount = event.get("amount")

            # Exclude unwanted abilities
            if ability_id == 20343: # Judgement of Light
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

        for entry in entries:
            guid = entry.get("guid")
            name = entry.get("name")
            canonical_guid = SpellBreakdown.spell_id_aliases.get(guid, guid)

            if guid == 20343:
                continue

            casts = entry.get("hitCount", entry.get("total", 0))

            if canonical_guid and name:
                id_to_name[canonical_guid] = name
                id_to_casts[canonical_guid] = id_to_casts.get(canonical_guid, 0) + casts

        # Manually patch known IDs as the casts table often only returns the ID
        id_to_name[17543] = "Fire Protection"
        id_to_name[17548] = "Shadow Protection"
        id_to_name[17549] = "Arcane Protection"
        id_to_name[27805] = "Holy Nova"
        id_to_name[27803] = "Holy Nova"
        id_to_name[15290] = "Vampiric Embrace"
        id_to_name[19968] = "Holy Light"
        id_to_name[19993] = "Flash of Light"
        id_to_name[25903] = "Holy Shock"
        id_to_name[25914] = "Holy Shock" #temp putting this here as that's now 3x IDs using it
        id_to_name[7242]  = "Shadow Protection"
        id_to_name[10901] = "Power Word: Shield"
        id_to_name[11337] = "Instant Poison VI"
        id_to_name[11354] = "Deadly Poison IV"
        id_to_name[22482] = "Blade Flurry"
        id_to_name[15851] = "Dragonbreath Chili"
        id_to_name[11351] = "Fire Shield"
        id_to_name[23267] = "Firebolt"
        id_to_name[1]     = "Melee"
        id_to_name[20647] = "Execute"
        id_to_name[11601] = "Revenge"
        id_to_name[1680] = "Whirlwind"
        id_to_name[12721] = "Deep Wound"
        id_to_name[20615] = "Intercept"
        id_to_name[7922] = "Charge"
        id_to_name[5530] = "Mace Stun"
        id_to_name[10461] = "Healing Stream"
        id_to_name[19364] = "Ground Stomp"
        id_to_name[26363] = "Lightning Shield"
        id_to_name[19729] = "Shadow Bolt"
        id_to_name[21140] = "Fatal Wound"
        id_to_name[22845] = "Frenzied Regeneration"
        id_to_name[21151] = "Gutgore Ripper"
        id_to_name[23894] = "Bloodthirst"
        id_to_name[24388] = "Brain Damage"
        id_to_name[11201] = "Crippling Poison"
        id_to_name[16624] = "Thorium Shield Spike"
        id_to_name[9910] = "Thorns"
        id_to_name[11374] = "Gift of Arthras"
        id_to_name[694] = "Mocking Blow"
        id_to_name[7373] = "Hamstring"
        id_to_name[7919] = "Shoot Crossbow"
        id_to_name[22600] = "Force Reactive Disk"
        id_to_name[11682] = "Hellfire"
        id_to_name[3009] = "Claw"
        id_to_name[355] = "Taunt"
        id_to_name[14921] = "Growl"
        id_to_name[24579] = "Screech"
        id_to_name[17800] = "Shadow Vulnerability"
        id_to_name[14268] = "Wing Clip"
        id_to_name[21992] = "Thunderfury"
        id_to_name[13237] = "Goblin Mortar"
        id_to_name[18104] = "Wrath"
        id_to_name[20253] = "Intercept Stun"
        id_to_name[23687] = "Lightning Strike"
        id_to_name[12579] = "Winter's Chill"
        id_to_name[14315] = "Explosive Trap"
        id_to_name[17261] = "Bite"
        id_to_name[17258] = "Bite"
        id_to_name[3010] = "Claw"
        id_to_name[25012] = "Lightning Breath"
        id_to_name[26654] = "Sweeping Strikes"
        id_to_name[20004] = "Life Steal"
        id_to_name[18398] = "Frost Blast"
        id_to_name[11567] = "Heroic Strike"


        
        id_to_name[19675] = "Feral Charge"
        id_to_name[2480] = "Shoot Bow"
        id_to_name[23063] = "Dense Dynamite"
  
        id_to_name[11556] = "Demoralising Shout"
        id_to_name[20560] = "Mocking Blow"
        id_to_name[20240] = "Retaliation"
        id_to_name[20569] = "Cleave"
        id_to_name[23454] = "Stun"
        id_to_name[1161] = "Challenging Shout"

        # Damage Received abilities (BWL centric)
        id_to_name[22442] = "Growing Flames"
        id_to_name[22275] = "Flamestrike"
        id_to_name[23341] = "Flame Buffet"
        id_to_name[22311] = "Brood Power Bronze"
        id_to_name[15663] = "Cleave"
        id_to_name[19366] = "Cauterizing Flames"

        id_to_name[15754] = "Cleave" #2nd cleave ID
        id_to_name[16806] = "Conflagration"
        id_to_name[20623] = "Fireblast"
        id_to_name[22979] = "Shadow Flame"
        id_to_name[22985] = "Shadow Flame" #2nd shadow flame ID
        id_to_name[23023] = "Conflagration" #2nd conflag
        id_to_name[23462] = "Fire Nova"
        id_to_name[24585] = "Drain Life"
        id_to_name[22980] = "Shadow Flame" #3rd shadow flame ID
        id_to_name[22687] = "Veil of Shadow"
        id_to_name[22665] = "Shadow Bolt Volley"
        id_to_name[13496] = "Dazed"
        id_to_name[13897] = "Fiery Weapon"
        id_to_name[14157] = "Ruthlessness"
        id_to_name[24251] = "Zulian Slice"
        
        id_to_name[13241] = "Goblin Sapper Charge"
        id_to_name[24375] = "War Stomp"
        id_to_name[22289] = "Brood Power Green"
        id_to_name[369330] = "Rain of Fire"
        id_to_name[19717] = "Rain of Fire"
        id_to_name[22436] = "Aura of Flames"
        id_to_name[22334] = "Bomb"
        id_to_name[22559] = "Brood Power: Blue"
        id_to_name[22336] = "Shadow Bolt"
        id_to_name[22539] = "Shadow Flame"
        id_to_name[22290] = "Brood Power Blue"
        id_to_name[15580] = "Strike"

        id_to_name[22433] = "Flame Buffet"
        id_to_name[22273] = "Arcane Missiles"
        id_to_name[22425] = "Fireball Volley"
        id_to_name[24573] = "Mortal Strike"
        id_to_name[18670] = "Knock Away"
        id_to_name[23331] = "Blast Wave"
        id_to_name[23339] = "Wing Buffet"
        id_to_name[23187] = "Frost Burn"
        id_to_name[22560] = "Brood Power Black"
        id_to_name[23169] = "Brood Affliction Green"
        id_to_name[22284] = "Brood Power Red"
        id_to_name[23154] = "Brood Affliction: Black"
        id_to_name[23155] = "Brood Affliction: Red"
        id_to_name[23153] = "Brood Affliction: Blue"
        id_to_name[23603] = "Wild Polymorph"

        id_to_name[22686] = "Bellowing Roar"
        id_to_name[17290] = "Fireball"
        id_to_name[22271] = "Arcane Explosion"
        id_to_name[19632] = "Cleave"
        id_to_name[6788] = "Weakened Soul"
        id_to_name[22975] = "Shadow Flame"
        id_to_name[23315] = "Ignite Flesh"
        id_to_name[23402] = "Corrupted Healing"
        id_to_name[22423] = "Flame Shock"
        id_to_name[23189] = "Forst Burn"
        id_to_name[23364] = "Tail Lash"
       


        id_to_name[23461] = "Flame Breath"
        id_to_name[19983] = "Cleave"
        id_to_name[17289] = "Shadow Shock"
        id_to_name[16636] = "Berserker Charge"
        id_to_name[15622] = "Cleave"
        id_to_name[16782] = "Lightning Bolt"
        id_to_name[22335] = "Bottle of Poison"
        id_to_name[23316] = "Ignite Flesh"
        id_to_name[22312] = "Brood Power Black"
        id_to_name[22424] = "Blast Wave"

        # MC Centric Abilities
        id_to_name[19771] = "Serrated Blade"
        id_to_name[-4] = "Melee"
        id_to_name[13880] = "Magma Splash"
        id_to_name[15502] = "Sunder Armor"
        id_to_name[11597] = "Sunder Armor"
        id_to_name[15732] = "Immolate"
        id_to_name[18944] = "Smash"
        id_to_name[18945] = "Knock Away"
        id_to_name[19129] = "Massive Tremor"
        id_to_name[19196] = "Surge"
        id_to_name[19272] = "Lava Breath"
        id_to_name[19319] = "Lava Burst"
        id_to_name[19393] = "Soul Burn"
        id_to_name[19428] = "Conflagration"
        id_to_name[19497] = "Eruption"
        id_to_name[19627] = "Fire Shield"
        id_to_name[19628] = "Flames"
        id_to_name[19630] = "Cone of Fire"
        id_to_name[19631] = "Melt Armor"
        id_to_name[19641] = "Pyroclast Barrage"
        id_to_name[19642] = "Cleave"
        id_to_name[19644] = "Strike"
        id_to_name[19698] = "Inferno"
        id_to_name[19712] = "Arcane Explosion"
        id_to_name[19730] = "Strike"
        id_to_name[19771] = "Serrated Blade"
        id_to_name[19780] = "Hand of Ragnaros"
        id_to_name[19781] = "Flame Spear"
        id_to_name[19820] = "Mangle"
        id_to_name[20276] = "Knockdown" #done
        id_to_name[20277] = "Fist of Ragnaros"
        id_to_name[20564] = "Elemental Fire"
        id_to_name[20602] = "Fire Nova"
        id_to_name[20603] = "Shadow Shock"
        id_to_name[21155] = "Intense Heat"
        id_to_name[21158] = "Lava Burst"
        id_to_name[21333] = "Lava Breath"
        id_to_name[19450] = "Magma Spit"

        id_to_name[19460] = "Shadow Shock"
        id_to_name[19728] = "Shadow Bolt"
        id_to_name[20229] = "Blast Wave"
        id_to_name[19408] = "Panic"
        id_to_name[19496] = "Magma Shackles"
        id_to_name[20476] = "Explosion"
        id_to_name[19635] = "Incite Flames"
        id_to_name[20605] = "Cleave"
        id_to_name[19367] = "Withering Heat"
        id_to_name[20294] = "Immolate"
        id_to_name[19777] = "Dark Strike"
        id_to_name[19776] = "Shadow Word Pain"
        id_to_name[3] = "Falling Damage"
        id_to_name[6] = "Lava Damage"
        id_to_name[5] = "Fire Damage"
        id_to_name[19369] = "Ancient Despair"
        id_to_name[19785] = "Throw"
        id_to_name[19365] = "Ancient Dread"
        id_to_name[20420] = "Fireball"
        id_to_name[19637] = "Fire Blossom"
        id_to_name[19659] = "Ignite Mana"
        id_to_name[21077] = "Shadow Bolt"


        #ZG

        id_to_name[-32] = "Melee" # a few odd ones like this
        id_to_name[3604] = "Tendon Rip"
        id_to_name[8355] = "Exploit Weakness"
        id_to_name[11130] = "Knock Away"
        id_to_name[12097] = "Pierce Armor"
        id_to_name[12540] = "Gouge"
        id_to_name[12723] = "Sweeping Strikes"
        id_to_name[12826] = "Polymorph"
        id_to_name[13445] = "Rend"
        id_to_name[13730] = "Demoralizing Shout"
        id_to_name[14290] = "Multi Shot"
        id_to_name[15232] = "Shadow Bolt"
        id_to_name[15588] = "Thunderclap"
        id_to_name[15589] = "Whirlwind"
        id_to_name[15614] = "Kick"
        id_to_name[15655] = "Shield Slam"
        id_to_name[15708] = "Mortal Strike"
        id_to_name[16790] = "Knockdown"
        id_to_name[16856] = "Mortal Strike"
        id_to_name[20545] = "Lightning Shield"
        id_to_name[20741] = "Shadow Bolt Volley"
        id_to_name[21390] = "Multi Shot"
        id_to_name[22412] = "Virulent Poison"
        id_to_name[22591] = "Strike"
        id_to_name[22644] = "Blood Leech"
        id_to_name[22859] = "Mortal Cleave"
        id_to_name[22886] = "Berserker Charge"
        id_to_name[22887] = "Throw"
        id_to_name[22908] = "Volley"
        id_to_name[23858] = "Holy Nova"
        id_to_name[23861] = "Poison Cloud"
        id_to_name[23918] = "Sonic Burst"
        id_to_name[23919] = "Swoop"
        id_to_name[23979] = "Holy Wrath"
        id_to_name[24011] = "Venom Spit"
        id_to_name[24023] = "Charge"
        id_to_name[24048] = "Whirling Trip"
        id_to_name[24049] = "Impale"
        id_to_name[24050] = "Sonic Burst"
        id_to_name[24097] = "Poison"
        id_to_name[24099] = "Poison Bolt Volley"
        id_to_name[24189] = "Force Punch"
        id_to_name[24192] = "Speed Slash"
        id_to_name[24306] = "Delusions of Jin'do"
        id_to_name[24317] = "Sunder Armor"
        id_to_name[24321] = "Poisonous Blood"
        id_to_name[24332] = "Rake"
        id_to_name[24339] = "Infected Bite"
        id_to_name[24407] = "Overpower"
        id_to_name[24437] = "Blood Leech"
        id_to_name[24611] = "Fireball"
        id_to_name[24612] = "Flamestrike"
        id_to_name[24616] = "Shadow Shock"
        id_to_name[24668] = "Shadow Bolt"
        id_to_name[24669] = "Rain of Fire"
        id_to_name[24671] = "Snap Kick"
        id_to_name[24685] = "Earth Shock"
        id_to_name[24673] = "Curse of Blood"
        id_to_name[16496] = "Magma Shackles"
        id_to_name[23860] = "Holy Fire"
        id_to_name[24333] = "Ravage"
        id_to_name[15801] = "Lightning Bolt"
        id_to_name[24003] = "Tranquilizing Poison"
        id_to_name[24016] = "Exploit Weakness"
        id_to_name[24071] = "Axe Flurry"
        id_to_name[19448] = "Poison"
        id_to_name[24674] = "Veil of Shadow"
        id_to_name[15581] = "Sinsiter Strike"
        id_to_name[24300] = "Drain Life"
        id_to_name[16508] = "Intimidating Roar"
        id_to_name[19716] = "Gehennas' Curse"



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

    @staticmethod
    def log_cleave_ids(events):
        print("\n[CLEAVE ID CHECK] Scanning damage taken for known and unknown Cleave IDs:")
        for e in events:
            if e.get("type") == "damage":
                spell_id = e.get("abilityGameID")
                if spell_id in SpellBreakdown.spell_id_aliases and SpellBreakdown.spell_id_aliases[spell_id] == 15663:
                    print(f"  - Found mapped Cleave ID: {spell_id} -> 15663")
                elif spell_id == 15663:
                    print(f"  - Found direct Cleave ID: {spell_id}")
                elif "cleave" in str(e.get("ability", "")).lower():
                    print(f"  - Potential Cleave variant: {spell_id} — name: {e.get('ability')}")
