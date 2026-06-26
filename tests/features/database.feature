Feature: Database Persistence
  As a raid leader tracking performance over time
  I want to import raid analyses into a database
  So that I can query historical character performance

  Background:
    Given a fresh test database

  Scenario: Import creates a raid record
    Given a raid analysis for report "abc123"
    When the analysis is imported to the database
    Then the raid "abc123" should be marked as imported

  Scenario: Import is idempotent
    Given a raid analysis for report "abc123"
    When the analysis is imported twice
    Then there should be exactly 1 raid record for "abc123"

  Scenario: Healer performance is stored
    Given a raid analysis with healer "HolyPriest" of class "Priest"
    When the analysis is imported to the database
    Then character "HolyPriest" should have healing data

  Scenario: Tank performance is stored
    Given a raid analysis with tank "TankWarrior" of class "Warrior"
    When the analysis is imported to the database
    Then character "TankWarrior" should have mitigation data

  Scenario: DPS performance is stored
    Given a raid analysis with DPS "StabbyRogue" of class "Rogue"
    When the analysis is imported to the database
    Then character "StabbyRogue" should have damage data

  Scenario: Delete raid removes its records
    Given a raid analysis for report "abc123"
    And the analysis has been imported
    When the raid "abc123" is deleted
    Then the raid "abc123" should not be marked as imported

  Scenario: Unknown character returns no history
    When character history is queried for "Unknown"
    Then the character history should be empty
