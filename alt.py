from .auth import TokenManager
from .client import WarcraftLogsClient, get_healing_data
from .healing import OverallHealing
from .characters import Characters
from .loader import load_config

def get_master_data(client, report_id):
    query = f"""
    {{
      reportData {{
        report(code: "{report_id}") {{
          masterData {{
            actors {{
              id
              name
            }}
          }}
        }}
      }}
    }}
    """
    return client.run_query(query)

def print_healing_summary():
    config = load_config()
    report_id = config["report_id"]

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    # Load characters from JSON
    characters = Characters("characters.json")
    master_data = get_master_data(client, report_id)
    name_to_id = characters.get_name_to_id_map_from_master_data(master_data)

    results = []

    for name, source_id in name_to_id.items():
        try:
            healing_data = get_healing_data(client, report_id, source_id)
            healing_events = healing_data["data"]["reportData"]["report"]["events"]["data"]
            total_healing, total_overhealing = OverallHealing.calculate(healing_events)
            results.append((name, total_healing, total_overhealing))
        except Exception as e:
            print(f"⚠️ Skipping {name}: {e}")

    # Print results as a clean table
    print("\n=== Healing Summary ===")
    print(f"{'Character':<20} {'Healing':>15} {'Overhealing':>15}")
    print("-" * 52)
    for name, healing, overhealing in sorted(results, key=lambda x: x[1], reverse=True):
        print(f"{name:<20} {healing:>15,} {overhealing:>15,}")

if __name__ == "__main__":
    print_healing_summary()
