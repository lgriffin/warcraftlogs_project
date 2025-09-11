# 📊 Warcraft Logs Casts-Focused Report Tool

## 🧠 Project Purpose

This project analyzes **Warcraft Logs** reports with a focus on **spell casts and utility usage**, rather than just raw healing or damage numbers. Traditional metrics are heavily influenced by gear, but **casts and abilities** offer a clearer view of player behavior, decision-making, and contribution to the raid. By analyzing **what players cast, when, and how often**, this tool provides more **meaningful insights into raid performance**.

---

## 🛠️ Getting Started (No Python Experience Needed)

This section will walk you through running the tool from scratch — no prior Python experience required.

### 1. ✅ Install Python

- Go to [https://www.python.org/downloads/](https://www.python.org/downloads/)
- Download Python 3.10 or newer for your operating system.
- During installation, **check the box that says “Add Python to PATH”**.

### 2. 📂 Clone or Download the Project

You can use Git or just download the ZIP.

```bash
git clone https://github.com/your-username/warcraftlogs-client.git
cd warcraftlogs-client
```

—or download the ZIP from GitHub and extract it.

### 3. 📦 Install Required Python Libraries

From a terminal or command prompt:

```bash
python -m pip install -r requirements.txt
```

### 4. 🔐 Set Your Warcraft Logs API Token

Make sure you’ve set up a valid `config.json` with your Warcraft Logs API credentials and `report_id`. To obtain API credentials login to the [client management page](https://www.warcraftlogs.com/api/clients/) and create a client

Example `config.json`:

```json
{
  "client_id": "your_client_id_here",
  "client_secret": "your_client_secret_here",
  "report_id": "abcdEFGHijkl1234"
}
```

---

## 🚀 Running the Report

From the command line, navigate to the project folder and run:

```bash
python -m warcraftlogs_client.cli
```

Or for specific analysis modes:

```bash
python -m warcraftlogs_client.cli unified --md    # Complete analysis with markdown
python -m warcraftlogs_client.cli healer          # Healer-focused analysis
python -m warcraftlogs_client.cli tank            # Tank mitigation analysis
python -m warcraftlogs_client.cli melee           # Melee DPS analysis
python -m warcraftlogs_client.cli ranged          # Ranged DPS analysis
```

This will generate a `.md` file inside the `reports/` folder, ready for upload, sharing, or analysis. To open a markdown file install a tool like VSCode and open it in preview, you want to view the pretty formatted version Vs the raw data. Markdown is also incredibly useful to pass to a GPT for analysis, allowing you do raid over raid comparisons. 

---

## 🧪 Main Analysis Modes

The project offers **4 role-specific views** to break down raid contributions more clearly and allows you choose which role you care about:

### 1. 🩺 Healer Main
- Focuses on **healing spells**, **overhealing**, and **spell usage frequency**
- Tracks utility spells like **Fear Ward**, **Abolish Disease**, and **Major Mana Potion**

### 2. 🛡️ Tank Main
- Captures **damage taken**, **mitigation abilities**, and **active defensive usage**
- Highlights spell casts and cooldown discipline

### 3. 🔫 Melee Main
- Analyzes melee **damage abilities**, **cooldowns**, and **weapon-based effects**
- Casts are used to understand pacing, energy/rage usage, and uptime

### 4. 🌽 Ranged Main
- Targets **Mages**, **Warlocks**, and **Hunters**
- Focuses on **spell casts**, **rotational consistency**, and **utility (e.g., decurse, traps)**


As a note, Classic WoW makes it really difficult to identify roles, so we have to do an element of guess work to identify tanks or healers. If you look at the config.json you can play around with the numbers to correctly idenfify by role.
```json
{
    "role_thresholds": {
    "healer_min_healing": 50000,
    "tank_min_taken": 150000,
    "tank_min_mitigation": 40
}
```

The attempt here is to look holistically at the overall log and NOT at individual fights, so players that swap spec or role will be very hard to detect. Similarly non standard or meme specs are not fully implemented yet. So Ret Paladin, Shadow Priest, Boomkin etc. will undoubtedly have problems. Horde needs more testing, so anyone spotting something missing from the Horde side just raise an issue or a PR.

## 🔮 Spell Management System

Classic WoW uses multiple spell IDs for the same ability (different ranks, etc.). Our new **configurable spell system** automatically handles this without requiring code changes.

### Adding Missing Spells (Non-Developers Welcome!)

**When you see `(ID 12345)` instead of a spell name:**

1. Use the management utility:
```bash
python manage_spells.py add-name 12345 "Actual Spell Name" warrior_abilities
```

2. Or edit `spell_data/spell_names.json` directly:
```json
"warrior_abilities": {
  "12345": "Actual Spell Name"
}
```

**When you see duplicate spells that should be merged:**

1. Use the management utility:
```bash
python manage_spells.py add-alias 12001,12002,12003 12000 new_spell_variants
```

2. Or edit `spell_data/spell_aliases.json` directly:
```json
"new_spell_variants": {
  "12001": 12000,  // All map to canonical ID 12000
  "12002": 12000,
  "12003": 12000
}
```

### Spell Management Commands

```bash
python manage_spells.py validate           # Check configuration
python manage_spells.py search "Flash Heal" # Find spells
python manage_spells.py list-categories    # Show categories
python manage_spells.py list-groups        # Show alias groups
```

The system automatically validates your changes and prevents errors like circular aliases. **No programming knowledge required!**

## 🌐 Unified Analysis

The new unified CLI provides **all-in-one analysis** across all roles:

```bash
python -m warcraftlogs_client.cli unified --md
```

This will:
- Automatically classify players into Healer, Tank, Melee, or Ranged
- Generate **individual role reports** and a **final unified summary**  
- Output everything to a clean Markdown file in the `/reports` folder

For healer-specific analysis with dynamic role detection:

```bash
python -m warcraftlogs_client.cli healer --use-dynamic-roles --md
```

---

## 📁 Output

All results are saved in the `reports/` directory, with filenames taken directly from the Logs Report:

```
healing_report_2025-06-06.md
```

You can have a logo.png in the same folder as the output to customise for your guild etc.
