Feature: API Authentication
  The system shall acquire and cache OAuth2 client credentials tokens,
  automatically refreshing them before expiry.

  @ears_event_driven @auth
  Scenario: When the first API call is made, the system shall acquire a token
    Given a token manager with client_id "test_id" and client_secret "test_secret"
    And the auth server will respond with token "abc_token" expiring in 3600 seconds
    When a token is requested
    Then the token should be "abc_token"

  @ears_ubiquitous @auth
  Scenario: The system shall cache the token and not re-request while valid
    Given a token manager with client_id "test_id" and client_secret "test_secret"
    And the auth server will respond with token "cached_token" expiring in 3600 seconds
    When a token is requested twice
    Then the auth server should have been called once

  @ears_event_driven @auth
  Scenario: When the cached token expires, the system shall acquire a new one
    Given a token manager with an expired token "old_token"
    And the auth server will respond with token "new_token" expiring in 3600 seconds
    When a token is requested
    Then the token should be "new_token"

  @ears_unwanted_behavior @auth
  Scenario: If the auth server returns HTTP 401, the system shall raise an authentication error
    Given a token manager with client_id "test_id" and client_secret "test_secret"
    And the auth server will return HTTP 401
    When a token is requested
    Then an authentication error should be raised with message containing "Authentication failed"

  @ears_unwanted_behavior @auth
  Scenario: If the auth server is unreachable, the system shall raise a connection error
    Given a token manager with client_id "test_id" and client_secret "test_secret"
    And the auth server is unreachable
    When a token is requested
    Then an authentication error should be raised with message containing "Cannot reach"

  @ears_unwanted_behavior @auth
  Scenario: If the auth server times out, the system shall raise a timeout error
    Given a token manager with client_id "test_id" and client_secret "test_secret"
    And the auth server will time out
    When a token is requested
    Then an authentication error should be raised with message containing "timed out"

  @ears_unwanted_behavior @auth
  Scenario: If the auth server returns invalid JSON, the system shall raise an error
    Given a token manager with client_id "test_id" and client_secret "test_secret"
    And the auth server will return invalid JSON
    When a token is requested
    Then an authentication error should be raised with message containing "invalid response"
