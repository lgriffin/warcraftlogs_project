import datetime

def print_report_metadata(metadata, present_names, master_actors):
    print("\n========================")
    print("📝 Report Metadata")
    print("========================")
    print(f"📄 Title: {metadata['title']}")
    print(f"👤 Owner: {metadata['owner']}")
    dt = datetime.datetime.fromtimestamp(metadata['start'] / 1000)
    print(f"📆 Date: {dt.strftime('%A, %d %B %Y %H:%M:%S')}")

    all_names = [a["name"] for a in master_actors]
    absent = [n for n in all_names if n not in present_names]
    print(f"👥 Present: {', '.join(sorted(present_names))}")
    if absent:
        print(f"🚫 Absent: {', '.join(sorted(absent))}")
