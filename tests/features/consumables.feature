Feature: Consumables Analysis
  The system shall track consumable usage across raids, recording
  player names, item names, counts, and timestamps.

  @ears_event_driven
  Scenario: When a raid has consumable usage, the system shall record consumable entries
    Given a raid analysis with consumable usage
    Then the consumables list should not be empty

  @ears_ubiquitous
  Scenario: The system shall track player name and item name for each consumable
    Given a raid analysis where "HolyPriest" used "Super Mana Potion"
    Then the consumable record should have player "HolyPriest"
    And the consumable record should have name "Super Mana Potion"

  @ears_ubiquitous
  Scenario: The system shall record the exact count of consumable uses
    Given a raid analysis where "HolyPriest" used 3 "Super Mana Potion"
    Then the consumable count should be 3

  @ears_ubiquitous
  Scenario: The system shall record timestamps for each consumable use
    Given a raid analysis where "HolyPriest" used potions at timestamps 60000 and 180000
    Then the consumable should have 2 timestamps

  @ears_ubiquitous
  Scenario: The system shall support consumable records for multiple players
    Given a raid analysis with consumables for "Player1" and "Player2"
    Then there should be 2 consumable records
