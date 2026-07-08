Feature: Markdown Report Export
  The system shall export analysis results as markdown, including
  raid title, owner, composition, and role summaries.

  @ears_ubiquitous
  Scenario: The system shall start markdown output with the raid title as heading
    Given a completed raid analysis for "Karazhan Clear"
    When the analysis is rendered to markdown
    Then the markdown should start with "# Karazhan Clear"

  @ears_ubiquitous
  Scenario: The system shall include the raid owner in markdown output
    Given a completed raid analysis owned by "TestGuild"
    When the analysis is rendered to markdown
    Then the markdown should contain "**Owner:** TestGuild"

  @ears_ubiquitous
  Scenario: The system shall include composition role sections in markdown output
    Given a completed raid analysis with tanks, healers, and DPS
    When the analysis is rendered to markdown
    Then the markdown should contain "**Tanks**"
    And the markdown should contain "**Healers**"
    And the markdown should contain "**DPS**"

  @ears_ubiquitous
  Scenario: The system shall include a healer summary section in markdown output
    Given a completed raid analysis with a healer named "HolyPriest"
    When the analysis is rendered to markdown
    Then the markdown should contain "## Healer Summary"
    And the markdown should contain "HolyPriest"

  @ears_event_driven
  Scenario: When analysis is exported to file, the system shall write valid markdown to disk
    Given a completed raid analysis for "Karazhan Clear"
    When the analysis is exported to a file
    Then the file should exist
    And the file should contain "# Karazhan Clear"
