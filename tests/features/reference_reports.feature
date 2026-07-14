Feature: Reference Report Comparison
  The system shall support importing reference raids separately from
  guild raids, enabling side-by-side performance comparison while
  maintaining strict data isolation.

  Background:
    Given a fresh test database

  @ears_event_driven @database @reference
  Scenario: When a raid is imported as a reference, it shall not appear in the guild raid list
    Given a raid analysis for report "ref_001"
    When the analysis is imported as "reference"
    Then the guild raid list should have 0 entries
    And the reference raid list should have 1 entry

  @ears_ubiquitous @database @reference
  Scenario: The system shall default to guild when no source is specified
    Given a raid analysis for report "guild_001"
    When the analysis is imported without specifying source
    Then the guild raid list should have 1 entry

  @ears_ubiquitous @database @reference
  Scenario: The system shall exclude reference-only characters from the guild character list
    Given a raid analysis for report "ref_001" with healer "RefHealer"
    And a raid analysis for report "guild_001" with healer "GuildHealer"
    When "ref_001" is imported as "reference"
    And "guild_001" is imported as "guild"
    Then character "RefHealer" should not appear in guild characters
    And character "GuildHealer" should appear in guild characters

  @ears_ubiquitous @database @reference
  Scenario: The system shall count only guild raids in character history
    Given a raid analysis for report "ref_001" with healer "SharedHealer"
    And a raid analysis for report "guild_001" with healer "SharedHealer"
    When "ref_001" is imported as "reference"
    And "guild_001" is imported as "guild"
    Then the guild raid count for "SharedHealer" should be 1

  @ears_event_driven @database @reference
  Scenario: When comparison aggregates are computed, they shall be scoped by source
    Given a raid analysis for report "guild_001" with healing 500000
    And a raid analysis for report "ref_001" with healing 800000
    When "guild_001" is imported as "guild"
    And "ref_001" is imported as "reference"
    Then the guild average healing should differ from the reference average healing

  @ears_event_driven @database @reference
  Scenario: When guild and reference raids share an encounter, the system shall find common encounters
    Given a raid analysis for report "guild_001" with encounter "Attumen" id 658
    And a raid analysis for report "ref_001" with encounter "Attumen" id 658
    When "guild_001" is imported as "guild"
    And "ref_001" is imported as "reference"
    Then there should be 1 common encounter

  @ears_unwanted_behavior @database @reference
  Scenario: If the same report is reimported, the original source shall be preserved
    Given a raid analysis for report "raid_001"
    When the analysis is imported as "reference"
    And the analysis is imported as "guild"
    Then the source for "raid_001" should be "reference"

  @ears_event_driven @database @reference
  Scenario: When a label is set on a reference raid, it shall be retrievable
    Given a raid analysis for report "ref_001"
    And the analysis is imported as "reference"
    When the label "Top Guild Run" is set on "ref_001"
    Then the label for "ref_001" should be "Top Guild Run"
