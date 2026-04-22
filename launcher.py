"""PyInstaller entry point — uses absolute imports to avoid package-context issues."""

from warcraftlogs_client.gui.app import run

if __name__ == "__main__":
    run()
