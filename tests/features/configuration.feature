Feature: Configuration Management
  As a user of the Warcraft Logs analyzer
  I want to configure the tool via a JSON file and environment variables
  So that I can provide API credentials and customize thresholds

  Scenario: Load valid configuration file
    Given a config file with client_id "test_id" and client_secret "test_secret"
    When the configuration is loaded
    Then the API client_id should be "test_id"
    And the API client_secret should be "test_secret"

  Scenario: Environment variables override file values
    Given a config file with client_id "file_id" and client_secret "file_secret"
    And environment variable "WARCRAFTLOGS_CLIENT_ID" is set to "env_id"
    When the configuration is loaded
    Then the API client_id should be "env_id"

  Scenario: Default role thresholds are applied
    Given a config file with minimal required fields
    When the configuration is loaded
    Then healer_min_healing should be 40000
    And tank_min_taken should be 150000
    And tank_min_mitigation should be 40

  Scenario: Custom role thresholds override defaults
    Given a config file with healer_min_healing set to 100000
    When the configuration is loaded
    Then healer_min_healing should be 100000

  Scenario: Configuration can be reloaded without error
    Given a config file with minimal required fields
    When the configuration is loaded twice
    Then both loads should return valid config

  Scenario: Missing config file raises error
    Given a nonexistent config file path
    When the configuration is loaded
    Then a configuration error should be raised
