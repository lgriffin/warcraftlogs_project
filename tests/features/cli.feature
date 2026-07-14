Feature: Command Line Interface
  The system shall provide CLI subcommands for running different
  types of analysis from the terminal.

  @ears_event_driven
  Scenario Outline: When the CLI receives a subcommand, the system shall parse it correctly
    When the CLI is invoked with "<subcommand>"
    Then the parsed command should be "<subcommand>"

    Examples:
      | subcommand |
      | unified    |
      | healer     |
      | tank       |
      | melee      |
      | ranged     |

  @ears_event_driven
  Scenario: When the --md flag is provided, the system shall enable markdown export
    When the CLI is invoked with "unified --md"
    Then the md flag should be true

  @ears_event_driven
  Scenario: When the --save flag is provided, the system shall enable save mode
    When the CLI is invoked with "unified --save"
    Then the save flag should be true

  @ears_event_driven
  Scenario: When --report-id is provided, the system shall use the specified report ID
    When the CLI is invoked with "unified --report-id abc123"
    Then the report_id should be "abc123"

  @ears_event_driven
  Scenario: When consumes is invoked with multiple IDs, the system shall capture all raid IDs
    When the CLI is invoked with "consumes id1 id2 id3"
    Then the parsed command should be "consumes"
    And the raid_ids should contain "id1" and "id2" and "id3"

  @ears_event_driven
  Scenario: When history is invoked with a name, the system shall capture the character name
    When the CLI is invoked with "history PlayerName"
    Then the parsed command should be "history"
    And the character_name should be "PlayerName"

  @ears_event_driven
  Scenario: When --verbose is provided, the system shall enable verbose mode
    When the CLI is invoked with "--verbose unified"
    Then the verbose flag should be true

  @ears_event_driven
  Scenario: When --debug is provided, the system shall enable debug mode
    When the CLI is invoked with "--debug unified"
    Then the debug flag should be true
