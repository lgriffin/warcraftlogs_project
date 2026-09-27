Feature: Verified application updates
  The updater shall only stage an update whose SHA-256 matches the entry in the
  release's SHA256SUMS (signed in CI with Sigstore keyless signing).

  @ears_unwanted_behavior @security
  Scenario: REQ-CORE-REL-001 If a downloaded update's digest does not match the signed SHA256SUMS, then the updater shall refuse to stage it and tell the user
    Given a release whose SHA256SUMS lists the update zip
    And the downloaded update zip has been tampered with
    When the user installs the update
    Then the update should be refused with a message containing "does not match the SHA-256"
    And nothing should be staged or launched

  @ears_unwanted_behavior @security
  Scenario: REQ-CORE-REL-001 If a release publishes no SHA256SUMS, then the updater shall refuse the update and tell the user
    Given a release that publishes no SHA256SUMS
    When the user installs the update
    Then the update should be refused with a message containing "does not publish a SHA256SUMS"
    And nothing should be staged or launched

  @ears_event_driven @security
  Scenario: REQ-CORE-REL-001 When the downloaded update matches SHA256SUMS, the updater shall stage it
    Given a release whose SHA256SUMS lists the update zip
    When the user installs the update
    Then the update should be staged and the swap script launched
