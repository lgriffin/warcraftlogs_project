Feature: Markdown Report Export
  As a raid leader
  I want to export analysis results as a markdown file
  So that I can share and archive raid performance data

  Scenario: Rendered markdown starts with raid title
    Given a completed raid analysis for "Karazhan Clear"
    When the analysis is rendered to markdown
    Then the markdown should start with "# Karazhan Clear"

  Scenario: Markdown includes raid owner
    Given a completed raid analysis owned by "TestGuild"
    When the analysis is rendered to markdown
    Then the markdown should contain "**Owner:** TestGuild"

  Scenario: Markdown includes composition sections
    Given a completed raid analysis with tanks, healers, and DPS
    When the analysis is rendered to markdown
    Then the markdown should contain "**Tanks**"
    And the markdown should contain "**Healers**"
    And the markdown should contain "**DPS**"

  Scenario: Markdown includes healer summary table
    Given a completed raid analysis with a healer named "HolyPriest"
    When the analysis is rendered to markdown
    Then the markdown should contain "## Healer Summary"
    And the markdown should contain "HolyPriest"

  Scenario: Export writes file to disk
    Given a completed raid analysis for "Karazhan Clear"
    When the analysis is exported to a file
    Then the file should exist
    And the file should contain "# Karazhan Clear"
