import argparse
from common.data import get_master_data, get_report_metadata
from common.metadata import print_report_metadata
from loader import load_config
from auth import TokenManager
from client import WarcraftLogsClient
from roles.healer import generate_healer_summary
from roles.healer import print_healer_table
from roles.melee import generate_melee_summary
from roles.melee import print_melee_table
from markdown_exporter import export_combined_markdown
import datetime

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--healer", action="store_true", help="Run healer report")
    parser.add_argument("--melee", action="store_true", help="Run melee report")
    parser.add_argument("--all", action="store_true", help="Run all reports")
    parser.add_argument("--md", action="store_true", help="Export Markdown report")
    args = parser.parse_args()

    config = load_config()
    report_id = config["report_id"]

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    metadata = get_report_metadata(client, report_id)
    metadata["report_id"] = report_id  # ensuring this gets passed for the MD file later
    master_actors = get_master_data(client, report_id)

    summaries = {}
    spell_names = {}

    # First: gather data
    if args.healer or args.all:
        healer_summary, healer_spells = generate_healer_summary(client, report_id, master_actors)
        summaries.update(healer_summary)
        spell_names.update(healer_spells)

    if args.melee or args.all:
        melee_summary, melee_spells = generate_melee_summary(client, report_id, master_actors)
        summaries.update(melee_summary)
        spell_names.update(melee_spells)

    # Second: print metadata before any tables
    present_names = [row["name"] for group in summaries.values() for row in group]
    print_report_metadata(metadata, present_names, master_actors)

    # Third: print tables in order
    if args.melee or args.all:
        print_melee_table(melee_summary, melee_spells)
    #small refactor needed here later todo
    if args.healer or args.all:
        print("======== Healing Team ========")
        for class_type in ["Priest", "Paladin", "Druid"]:
            if summaries.get(class_type):
                spells = sorted(spell_names.get(class_type, []))
                print_healer_table(summaries[class_type], spells, class_type)


    if args.md:
        log_date = datetime.datetime.fromtimestamp(metadata["start"] / 1000).strftime("%Y-%m-%d")
        output_path = f"reports/{log_date}.md"
        export_combined_markdown(
            metadata=metadata,
            summaries=summaries,
            spell_names=spell_names,
            include_healer=args.healer or args.all,
            include_melee=args.melee or args.all,
            report_title="Warcraft Logs Granular Report by Hadur<toads>",
            output_path=output_path
        )


if __name__ == "__main__":
    main()