Feature: User Authentication
  The system shall manage OAuth2 user tokens with persistence,
  automatic refresh, and clean revocation.

  @ears_state_driven @auth
  Scenario: While no token exists, the user shall not be authenticated
    Given no token file exists
    Then the user should not be authenticated

  @ears_event_driven @auth
  Scenario: When the OAuth flow completes with a valid code, the system shall store the token
    Given no token file exists
    And the token server will respond with access_token "user_abc" and refresh_token "refresh_xyz" expiring in 3600 seconds
    When the auth flow completes with code "auth_code_123"
    Then the user should be authenticated
    And the token file should exist

  @ears_state_driven @auth
  Scenario: While a valid token exists on disk, the user shall be authenticated after reload
    Given a saved token file with access_token "saved_token" expiring in 3600 seconds
    When a new token manager loads from the same path
    Then the user should be authenticated

  @ears_event_driven @auth
  Scenario: When the access token expires but a refresh token exists, the system shall refresh automatically
    Given a saved token file with an expired access_token and refresh_token "refresh_abc"
    And the token server will respond with access_token "refreshed_token" and refresh_token "new_refresh" expiring in 3600 seconds
    When the user requests a token
    Then the token should be "refreshed_token"

  @ears_unwanted_behavior @auth
  Scenario: If the refresh attempt fails, the system shall revoke and require re-authentication
    Given a saved token file with an expired access_token and refresh_token "refresh_abc"
    And the token server will return HTTP 400 on refresh
    When the user requests a token
    Then an authentication error should be raised with message containing "refresh failed"
    And the user should not be authenticated after revocation

  @ears_event_driven @auth
  Scenario: When the user revokes authentication, the token file shall be deleted
    Given a saved token file with access_token "active_token" expiring in 3600 seconds
    When the user revokes authentication
    Then the user should not be authenticated
    And the token file should not exist

  @ears_unwanted_behavior @auth
  Scenario: If the token file is corrupted, the system shall treat it as unauthenticated
    Given a corrupted token file
    Then the user should not be authenticated

  @ears_unwanted_behavior @auth
  Scenario: If the auth server is unreachable during token exchange, the system shall raise an authentication error
    Given no token file exists
    And the token server is unreachable
    When the auth flow completes with code "auth_code_123"
    Then an authentication error should be raised with message containing "Cannot reach"
