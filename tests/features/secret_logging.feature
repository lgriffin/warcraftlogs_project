Feature: Secrets never reach the logs
  The client secret, access token and refresh token are held as SecretStr and
  shall never appear in any log record, at any level, on success or failure.

  @ears_ubiquitous @security @auth
  Scenario: REQ-CORE-SEC-001 The system shall not write a client secret, access token or refresh token to any log record
    Given every logger is capturing at DEBUG level
    And the client secret is supplied through the environment
    When the app authenticates with client credentials and queries the API
    And the user completes the OAuth flow and the token is later refreshed
    Then the credential flows should have logged activity
    And no log record at any level should contain a client secret, access token or refresh token

  @ears_unwanted_behavior @security @auth
  Scenario: REQ-CORE-SEC-001 If authentication fails, then the system shall report the failure without logging any secret
    Given every logger is capturing at DEBUG level
    And the client secret is supplied through the environment
    When the token server rejects the client credentials and the OAuth code exchange
    Then the authentication failures should have been logged
    And no log record at any level should contain a client secret, access token or refresh token
