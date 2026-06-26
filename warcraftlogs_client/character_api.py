import json
import logging
import os

import requests

from . import paths
from .client import WarcraftLogsClient

logger = logging.getLogger(__name__)

CACHE_FILE = str(paths.get_cache_dir() / "character_specs.json")

QUERY_TEMPLATE = """
query {{
  characterData {{
    character(name: \"{name}\", serverSlug: \"{server}\", serverRegion: \"{region}\") {{
      classID
      specID
    }}
  }}
}}
"""


def enrich_actors_with_specs(
    actors: list[dict],
    client: WarcraftLogsClient | None = None,
    region: str = "EU",
    server: str = "gehennas",
) -> list[dict]:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    cache = {}

    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache = json.load(f)

    updated = []
    cache_updated = False

    for actor in actors:
        name = actor.get("name")
        if actor.get("specID") is not None:
            updated.append(actor)
            continue

        if name in cache:
            actor["specID"] = cache[name]["specID"]
            actor["classID"] = cache[name]["classID"]
            updated.append(actor)
            continue

        if client is None:
            updated.append(actor)
            continue

        query = QUERY_TEMPLATE.format(name=name, server=server, region=region)

        try:
            result = client.run_query(query, use_cache=False)
            character = result["data"]["characterData"]["character"]
            if character:
                spec_id = character.get("specID")
                class_id = character.get("classID")
                actor["specID"] = spec_id
                actor["classID"] = class_id
                cache[name] = {"specID": spec_id, "classID": class_id}
                cache_updated = True
                logger.info("Fetched %s: specID=%s, classID=%s", name, spec_id, class_id)
            else:
                logger.warning("No character data for %s", name)
        except (requests.RequestException, KeyError, TypeError) as e:
            logger.error("Failed to fetch %s: %s", name, e)

        updated.append(actor)

    if cache_updated:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)

    return updated
