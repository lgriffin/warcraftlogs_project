import json

class Characters:
    def __init__(self, filepath="characters.json"):
        self.character_names = self.load_characters(filepath)

    def load_characters(self, filepath):
        with open(filepath, "r") as file:
            data = json.load(file)
            return data.get("characters", [])

    def get_name_to_id_map_from_master_data(self, report_data):
        actors = report_data["data"]["reportData"]["report"]["masterData"]["actors"]
        return {
            actor["name"]: actor["id"]
            for actor in actors
            if actor["name"] in self.character_names
        }


