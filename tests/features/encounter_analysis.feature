Feature: Encounter Analysis
  The system shall analyze individual boss encounters within a raid,
  filtering out trash fights and merging damage, healing, and
  damage-taken data per player.

  @ears_event_driven @api
  Scenario: When a raid contains boss kills, the system shall produce encounter summaries
    Given a mock WCL client
    And the client returns fights with 1 boss kill named "Attumen"
    When encounters are analyzed for report "abc123"
    Then there should be 1 encounter summary
    And the encounter should be named "Attumen"

  @ears_ubiquitous @api
  Scenario: The system shall filter out trash fights
    Given a mock WCL client
    And the client returns fights with 1 boss kill and 2 trash fights
    When encounters are analyzed for report "abc123"
    Then there should be 1 encounter summary

  @ears_ubiquitous @api
  Scenario: The system shall filter out wipes
    Given a mock WCL client
    And the client returns fights with 1 boss kill and 1 wipe
    When encounters are analyzed for report "abc123"
    Then there should be 1 encounter summary

  @ears_event_driven @api
  Scenario: When encounter data includes damage and healing, the system shall merge them per player
    Given a mock WCL client
    And the client returns a boss fight with "StabbyRogue" dealing 200000 damage and "HolyPriest" doing 100000 healing
    When encounters are analyzed for report "abc123"
    Then player "StabbyRogue" should have 200000 total damage
    And player "HolyPriest" should have 100000 total healing

  @ears_ubiquitous @api
  Scenario: The system shall exclude pet entries from encounter summaries
    Given a mock WCL client
    And the client returns a boss fight with a player and a pet
    When encounters are analyzed for report "abc123"
    Then there should be 1 player in the encounter

  @ears_unwanted_behavior @api
  Scenario: If the API fails for one encounter, the system shall skip it and continue
    Given a mock WCL client
    And the client returns 2 boss fights where the first errors
    When encounters are analyzed for report "abc123"
    Then there should be 1 encounter summary

  @ears_event_driven @database
  Scenario: When encounters are imported to the database, they shall be retrievable
    Given a fresh test database
    And a raid analysis with an encounter named "Attumen"
    When the encounter analysis is imported to the database
    Then the database should contain encounter "Attumen"

  @ears_event_driven @database
  Scenario: When a raid is deleted, its encounter data shall be cascaded
    Given a fresh test database
    And a raid analysis with an encounter named "Attumen"
    And the encounter analysis has been imported
    When the raid "test_report" is deleted from the database
    Then the database should have no encounter records
