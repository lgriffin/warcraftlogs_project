import argparse

from .auth import TokenManager
from .client import WarcraftLogsClient
from .config import load_config
from .analysis import analyze_raid
from .renderers.console import render_raid_analysis
from .spell_manager import reset_spell_manager


def run_unified_report(args):
    reset_spell_manager()
    config = load_config()
    report_id = config["report_id"]
    role_thresholds = config.get("role_thresholds", {})

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    print("Pulling data from the report")
    print("Initially going to try identify roles dynamically")

    analysis = analyze_raid(
        client, report_id,
        healer_threshold=role_thresholds.get("healer_min_healing", 40000),
        tank_min_taken=role_thresholds.get("tank_min_taken", 150000),
        tank_min_mitigation=role_thresholds.get("tank_min_mitigation", 40),
        healer_threshold_10=role_thresholds.get("healer_min_healing_10", 400000),
        tank_min_taken_10=role_thresholds.get("tank_min_taken_10", 300000),
    )

    render_raid_analysis(analysis)

    if args.md:
        from .renderers.markdown import export_raid_analysis
        path = export_raid_analysis(analysis)
        print(f"\nMarkdown report exported to: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified Warcraft Logs Role Classifier")
    parser.add_argument("--md", action="store_true", help="Export summary markdown report")
    args = parser.parse_args()
    run_unified_report(args)
