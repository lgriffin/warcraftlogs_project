Feature: Raid Analysis
  The system shall analyze Warcraft Logs reports to classify players
  into roles (tank, healer, melee DPS, ranged DPS) based on
  performance thresholds and class-specific heuristics.

  @ears_event_driven @api
  Scenario: When a player exceeds tank thresholds, the system shall classify them as a tank
    Given a master actor "TankWarrior" of class "Warrior" with id 2
    And "TankWarrior" took 200000 damage and mitigated 600000
    When tanks are identified with min_taken 150000 and min_mitigation 40
    Then "TankWarrior" should be identified as a tank

  @ears_unwanted_behavior @api
  Scenario: If a player is below the tank damage threshold, then the system shall not classify them as a tank
    Given a master actor "WeakWarrior" of class "Warrior" with id 2
    And "WeakWarrior" took 50000 damage and mitigated 10000
    When tanks are identified with min_taken 150000 and min_mitigation 40
    Then no tanks should be identified

  @ears_event_driven @api
  Scenario: When a player exceeds the healing threshold, the system shall classify them as a healer
    Given a master actor "HolyPriest" of class "Priest" with id 1
    And "HolyPriest" did 300000 total healing
    When healers are identified with threshold 200000
    Then "HolyPriest" should be identified as a healer

  @ears_unwanted_behavior @api
  Scenario: If a player is below the healing threshold, then the system shall not classify them as a healer
    Given a master actor "ShadowPriest" of class "Priest" with id 1
    And "ShadowPriest" did 5000 total healing
    When healers are identified with threshold 200000
    Then no healers should be identified

  @ears_ubiquitous @api
  Scenario: The system shall classify Rogue as melee DPS
    Given a master actor "StabbyRogue" of class "Rogue" with id 3
    When the composition is identified
    Then "StabbyRogue" should be classified as "melee"

  @ears_ubiquitous @api
  Scenario: The system shall classify Mage as ranged DPS
    Given a master actor "FrostMage" of class "Mage" with id 4
    When the composition is identified
    Then "FrostMage" should be classified as "ranged"

  @ears_event_driven @api
  Scenario: When a hybrid class deals majority spell damage, the system shall classify them as ranged
    Given a master actor "BoomDruid" of class "Druid" with id 6
    And "BoomDruid" deals 100 melee damage and 900 spell damage
    When the hybrid role is classified
    Then the role should be "ranged"

  @ears_event_driven @api
  Scenario: When a hybrid class deals majority melee damage, the system shall classify them as melee
    Given a master actor "FeralDruid" of class "Druid" with id 7
    And "FeralDruid" deals 800 melee damage and 200 spell damage
    When the hybrid role is classified
    Then the role should be "melee"

  @ears_event_driven @api
  Scenario: When a full raid analysis is executed, the system shall produce a structured result with metadata and composition
    Given a mock client with report data for "r1"
    When the full raid analysis is run for "r1"
    Then the result should contain metadata with report id "r1"
    And the result should have a composition
