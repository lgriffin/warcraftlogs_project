import os
import json
import time
from typing import List
from .client import run_graphql_query

CACHE_FILE = ".cache/character_specs.json"

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

def enrich_actors_with_specs(actors: List[dict]) -> List[dict]:
    os.makedirs(".cache", exist_ok=True)
    cache = {}

    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
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

        # Try to fetch from API
        # TODO: infer region/server dynamically or default from config
        region = "EU"
        server = "gehennas"

        query = QUERY_TEMPLATE.format(name=name, server=server, region=region)

        try:
            result = run_graphql_query(query)
            character = result["data"]["characterData"]["character"]
            if character:
                spec_id = character.get("specID")
                class_id = character.get("classID")
                actor["specID"] = spec_id
                actor["classID"] = class_id
                cache[name] = {"specID": spec_id, "classID": class_id}
                cache_updated = True
                print(f"[FETCHED] {name}: specID={spec_id}, classID={class_id}")
            else:
                print(f"[MISSING] No character data for {name}")
        except Exception as e:
            print(f"[ERROR] Failed to fetch {name}: {e}")

        updated.append(actor)
        time.sleep(0.5)  # Be nice to the API

    if cache_updated:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)

    return updated
