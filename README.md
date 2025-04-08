# Warcraft Logs Healing Report Generator

This tool analyzes healing data from Warcraft Logs and produces class-specific reports for your raid team. It supports both static character lists and dynamic role detection, and it can export results to Markdown for easy sharing.

## ✨ Features

- Per-character healing and overhealing summaries
- Class-specific views: **PriestView**, **PaladinView**, **DruidView**
- Spell-level breakdowns with counts and effectiveness
- Utility spell and dispel tracking (e.g., Fear Ward, Cleanse)
- Resource usage summaries (e.g., Major Mana Potion, Dark Rune)
- Optional **Markdown export** for publishing or sharing
- Optional **dynamic role inference** from logs (no need for a manual character list)
- Default ability to define a characters.json to just look for individual characters we care about

## Running the program

Temporary way to run this is using new_main for the entry as the project is a moving target. Optional flags are included
python -m warcraftlogs_client.new_main --use-dynamic-roles --md


## Config

Keeping my credentials in for simple testing, replace the client ID and secret with your own app if you so wish. The report ID is the main configuration to change as that drives the usage. TODO will be to add the report_id to the command line

{
    "client_id": "9e7bfab5-7623-4300-8f56-d02c2d555a33",
    "client_secret": "mQ0wVlyF8QDYgqCHVpEgytPZ8icx5rkWggWGFzFL",
    "report_id": "VAmqJ2v1FwraQKyL"
}


## 🛠 Requirements

Install dependencies with:

```bash
pip install -r requirements.txt


