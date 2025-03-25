class OverallHealing:
    @staticmethod
    def calculate(healing_events):
        total_healing = sum(event.get("amount", 0) for event in healing_events)
        total_overhealing = sum(event.get("overheal", 0) for event in healing_events)
        return total_healing, total_overhealing
