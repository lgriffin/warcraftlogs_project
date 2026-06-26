# dynamic_role_parser.py

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def group_players_by_class(master_actors):
    class_groups = defaultdict(list)

    for actor in master_actors:
        if actor.get("type") == "Player":
            class_name = actor.get("subType", "Unknown")
            class_groups[class_name].append(
                {
                    "name": actor["name"],
                    "id": actor["id"],
                    "subType": class_name,  # ✅ Add this line
                }
            )

    logger.debug("Players Grouped by Class:")
    for class_name, players in class_groups.items():
        logger.debug("Class: %s", class_name)
        for player in players:
            logger.debug("  - %s (ID: %s)", player["name"], player["id"])
    return class_groups


def identify_healers(master_actors, healing_totals, threshold):
    healing_classes = {"Priest", "Paladin", "Druid", "Shaman"}

    healers = []
    for actor in master_actors:
        if actor.get("type") != "Player":
            continue

        class_name = actor.get("subType", "Unknown")
        if class_name not in healing_classes:
            continue

        actor_name = actor["name"]
        total_healing = healing_totals.get(actor_name, 0)

        if total_healing > threshold:
            healers.append(
                {
                    "name": actor_name,
                    "id": actor["id"],
                    "class": class_name,
                    "healing": total_healing,
                }
            )

    # print("\n💉 Identified Healers (Healing > 50,000):")
    # for healer in healers:
    #     print(f"- {healer['name']} ({healer['class']}): {healer['healing']:,} healing")
    # print("\n💉 Excluding anyone that hasn't breached 50k healing:")
    return healers
