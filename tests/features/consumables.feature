Feature: Consumables Analysis
  As a raid leader
  I want to track consumable usage across raids
  So that I can ensure players are properly prepared

  Scenario: Consumable usage is recorded in analysis
    Given a raid analysis with consumable usage
    Then the consumables list should not be empty

  Scenario: Consumable tracks player name and item
    Given a raid analysis where "HolyPriest" used "Super Mana Potion"
    Then the consumable record should have player "HolyPriest"
    And the consumable record should have name "Super Mana Potion"

  Scenario: Consumable count matches usage
    Given a raid analysis where "HolyPriest" used 3 "Super Mana Potion"
    Then the consumable count should be 3

  Scenario: Consumable timestamps are recorded
    Given a raid analysis where "HolyPriest" used potions at timestamps 60000 and 180000
    Then the consumable should have 2 timestamps

  Scenario: Multiple players can have consumable records
    Given a raid analysis with consumables for "Player1" and "Player2"
    Then there should be 2 consumable records
