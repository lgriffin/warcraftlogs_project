Feature: Configuration Management
  The system shall load configuration from a JSON file and environment
  variables, providing API credentials and customizable role thresholds.

  @ears_event_driven
  Scenario: When a valid config file is loaded, the system shall provide API credentials
    Given a config file with client_id "test_id" and client_secret "test_secret"
    When the configuration is loaded
    Then the API client_id should be "test_id"
    And the API client_secret should be "test_secret"

  @ears_state_driven
  Scenario: While environment variables are set, the system shall use them over file values
    Given a config file with client_id "file_id" and client_secret "file_secret"
    And environment variable "WARCRAFTLOGS_CLIENT_ID" is set to "env_id"
    When the configuration is loaded
    Then the API client_id should be "env_id"

  @ears_ubiquitous
  Scenario: The system shall apply default role thresholds when none are specified
    Given a config file with minimal required fields
    When the configuration is loaded
    Then healer_min_healing should be 900000
    And tank_min_taken should be 150000
    And tank_min_mitigation should be 40

  @ears_event_driven
  Scenario: When custom thresholds are configured, the system shall use them instead of defaults
    Given a config file with healer_min_healing set to 100000
    When the configuration is loaded
    Then healer_min_healing should be 100000

  @ears_ubiquitous
  Scenario: The system shall support idempotent configuration reloading
    Given a config file with minimal required fields
    When the configuration is loaded twice
    Then both loads should return valid config

  @ears_unwanted_behavior
  Scenario: If the config file is missing, then the system shall raise a configuration error
    Given a nonexistent config file path
    When the configuration is loaded
    Then a configuration error should be raised
