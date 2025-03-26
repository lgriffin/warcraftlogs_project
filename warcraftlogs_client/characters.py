import json

class Characters:
    def __init__(self, filepath="characters.json"):
        self.name_to_class = self.load_characters(filepath)

    def load_characters(self, filepath):
        with open(filepath, "r") as file:
            data = json.load(file)
            # Support legacy list format or new dict format
            if isinstance(data.get("characters", []), list) and isinstance(data["characters"][0], dict):
                return {char["name"]: char["class"] for char in data["characters"]}
            else:
                return {name: "Unknown" for name in data.get("characters", [])}

    def get_names(self):
        return list(self.name_to_class.keys())

    def get_class(self, name):
        return self.name_to_class.get(name, "Unknown")

    def get_name_to_id_map_from_master_data(self, report_data):
        actors = report_data["data"]["reportData"]["report"]["masterData"]["actors"]
        return {
            actor["name"]: actor["id"]
            for actor in actors
            if actor["name"] in self.get_names()
        }
