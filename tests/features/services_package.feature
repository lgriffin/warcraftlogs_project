Feature: Services package
  The application services live in wcl-app (packages/wcl-app) so the desktop app, the CLI and the Toads Hub
  worker share one set of use cases. A headless host installs wcl-core, wcl-store and wcl-app, passes its own
  Warcraft Logs client and storage, and never needs the desktop app, Qt, SQLite or a config.json.

  @ears_ubiquitous @integration
  Scenario: REQ-CORE-APP-001 The services package shall install and run without the desktop app
    Given a Python process where the desktop app, Qt and sqlite3 cannot be imported
    When a host imports every wcl_app module and analyses a raid with its own client and storage
    Then the analysis should use the host's client and the saved role overrides
    And the raid should be stored through the host's storage
    And no desktop app, Qt or sqlite3 module should have been loaded
