Feature: Database Persistence
  The system shall persist raid analysis results to a SQLite database,
  enabling historical performance queries per character.

  Background:
    Given a fresh test database

  @ears_event_driven
  Scenario: When a raid analysis is imported, the system shall create a raid record
    Given a raid analysis for report "abc123"
    When the analysis is imported to the database
    Then the raid "abc123" should be marked as imported

  @ears_ubiquitous
  Scenario: The system shall not create duplicate records on repeated imports
    Given a raid analysis for report "abc123"
    When the analysis is imported twice
    Then there should be exactly 1 raid record for "abc123"

  @ears_event_driven
  Scenario: When a raid with healers is imported, the system shall store healer performance data
    Given a raid analysis with healer "HolyPriest" of class "Priest"
    When the analysis is imported to the database
    Then character "HolyPriest" should have healing data

  @ears_event_driven
  Scenario: When a raid with tanks is imported, the system shall store tank mitigation data
    Given a raid analysis with tank "TankWarrior" of class "Warrior"
    When the analysis is imported to the database
    Then character "TankWarrior" should have mitigation data

  @ears_event_driven
  Scenario: When a raid with DPS is imported, the system shall store DPS damage data
    Given a raid analysis with DPS "StabbyRogue" of class "Rogue"
    When the analysis is imported to the database
    Then character "StabbyRogue" should have damage data

  @ears_event_driven
  Scenario: When a raid is deleted, the system shall remove its records
    Given a raid analysis for report "abc123"
    And the analysis has been imported
    When the raid "abc123" is deleted
    Then the raid "abc123" should not be marked as imported

  @ears_unwanted_behavior
  Scenario: If a character is unknown, then the system shall return empty history
    When character history is queried for "Unknown"
    Then the character history should be empty
