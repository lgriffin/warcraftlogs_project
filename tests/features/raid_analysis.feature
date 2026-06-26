Feature: Raid Analysis
  As a raid leader
  I want to analyze a Warcraft Logs report
  So that I can evaluate player performance across roles

  Scenario: Identify tanks by damage taken threshold
    Given a master actor "TankWarrior" of class "Warrior" with id 2
    And "TankWarrior" took 200000 damage and mitigated 600000
    When tanks are identified with min_taken 150000 and min_mitigation 40
    Then "TankWarrior" should be identified as a tank

  Scenario: Reject player below tank damage threshold
    Given a master actor "WeakWarrior" of class "Warrior" with id 2
    And "WeakWarrior" took 50000 damage and mitigated 10000
    When tanks are identified with min_taken 150000 and min_mitigation 40
    Then no tanks should be identified

  Scenario: Identify healers by healing output
    Given a master actor "HolyPriest" of class "Priest" with id 1
    And "HolyPriest" did 300000 total healing
    When healers are identified with threshold 200000
    Then "HolyPriest" should be identified as a healer

  Scenario: Reject player below healing threshold
    Given a master actor "ShadowPriest" of class "Priest" with id 1
    And "ShadowPriest" did 5000 total healing
    When healers are identified with threshold 200000
    Then no healers should be identified

  Scenario: Classify Rogue as melee DPS
    Given a master actor "StabbyRogue" of class "Rogue" with id 3
    When the composition is identified
    Then "StabbyRogue" should be classified as "melee"

  Scenario: Classify Mage as ranged DPS
    Given a master actor "FrostMage" of class "Mage" with id 4
    When the composition is identified
    Then "FrostMage" should be classified as "ranged"

  Scenario: Hybrid with mostly spell damage classified as ranged
    Given a master actor "BoomDruid" of class "Druid" with id 6
    And "BoomDruid" deals 100 melee damage and 900 spell damage
    When the hybrid role is classified
    Then the role should be "ranged"

  Scenario: Hybrid with mostly melee damage classified as melee
    Given a master actor "FeralDruid" of class "Druid" with id 7
    And "FeralDruid" deals 800 melee damage and 200 spell damage
    When the hybrid role is classified
    Then the role should be "melee"

  Scenario: Full raid analysis produces structured result
    Given a mock client with report data for "r1"
    When the full raid analysis is run for "r1"
    Then the result should contain metadata with report id "r1"
    And the result should have a composition
