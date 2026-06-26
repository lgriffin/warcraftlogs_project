Feature: Command Line Interface
  As a user of the Warcraft Logs analyzer
  I want to use CLI subcommands
  So that I can run different types of analysis from the terminal

  Scenario Outline: Subcommand is parsed correctly
    When the CLI is invoked with "<subcommand>"
    Then the parsed command should be "<subcommand>"

    Examples:
      | subcommand |
      | unified    |
      | healer     |
      | tank       |
      | melee      |
      | ranged     |

  Scenario: Unified with markdown export flag
    When the CLI is invoked with "unified --md"
    Then the md flag should be true

  Scenario: Unified with save flag
    When the CLI is invoked with "unified --save"
    Then the save flag should be true

  Scenario: Unified with report-id override
    When the CLI is invoked with "unified --report-id abc123"
    Then the report_id should be "abc123"

  Scenario: Consumes with multiple raid IDs
    When the CLI is invoked with "consumes id1 id2 id3"
    Then the parsed command should be "consumes"
    And the raid_ids should contain "id1" and "id2" and "id3"

  Scenario: History with character name
    When the CLI is invoked with "history PlayerName"
    Then the parsed command should be "history"
    And the character_name should be "PlayerName"

  Scenario: Verbose flag enables info logging
    When the CLI is invoked with "--verbose unified"
    Then the verbose flag should be true

  Scenario: Debug flag enables debug logging
    When the CLI is invoked with "--debug unified"
    Then the debug flag should be true
