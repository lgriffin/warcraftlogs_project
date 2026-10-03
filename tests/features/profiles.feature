Feature: Raid profiles and Discord identity
  A profile is a named view over the one raid database (TBC, Classic days, Era) and picks where imports come from;
  a linked Discord identity says who runs this app. Each scenario is one requirement from the table in
  guides/identity_and_profiles.md, worded exactly as there; tests/test_spec_audit.py keeps the two the same. Nowhere
  Keep is a raid in a zone the catalogue does not know.

  Background:
    Given a raid database with Molten Core tagged Classic, Karazhan tagged The Burning Crusade and Nowhere Keep untagged

  @ears_event_driven @database
  Scenario: PROF-01 When a raid is imported, the store shall record its game version and expansion without blanking a stored value with an unknown one
    When Karazhan is imported again with no era
    Then Karazhan should still be on "fresh" in "The Burning Crusade"
    When Karazhan is imported again on "classic" in "Classic"
    Then Karazhan should still be on "classic" in "Classic"

  @ears_event_driven @database
  Scenario: PROF-02 When a read takes a `RaidScope`, the store shall return only raids inside it, counting a raid whose era is unknown as inside every scope on that axis
    When the guild raids are read in "The Burning Crusade"
    Then the read should return Nowhere Keep and Karazhan
    When the guild raids are read in "Classic"
    Then the read should return Nowhere Keep and Molten Core

  @ears_event_driven @database
  Scenario: PROF-03 When no profile is active, every service shall behave exactly as before profiles existed
    Given no profile is active
    Then the raid list, raid count and character history should match unscoped reads of all three raids

  @ears_event_driven
  Scenario: PROF-04 When a profile names a game version whose site is known, the context shall import from that site; any other profile keeps the configured host
    When a profile on "classic" is activated
    Then imports should come from "https://classic.warcraftlogs.com/api/v2/client"
    When a profile on "forever" is activated
    Then imports should come from "https://fresh.warcraftlogs.com/api/v2/client"

  @ears_event_driven @auth
  Scenario: PROF-05 When a profile is created while an identity is linked, the profile shall carry that Discord id as its owner
    Given the Discord account "123456789" is linked
    When a profile named "TBC" is created
    Then the profile should be owned by "123456789"

  @ears_event_driven @database
  Scenario: PROF-06 When raids stored before this change are backfilled, the service shall tag each from its zone and the configured host, leaving an unknown zone's expansion unset
    Given the raids were stored before eras were read
    When the stored raids are backfilled
    Then Molten Core should be on "fresh" in "Classic"
    And Karazhan should be on "fresh" in "The Burning Crusade"
    And Nowhere Keep should be on "fresh" with no expansion

  @ears_ubiquitous @database
  Scenario: PROF-07 Each raid-reading service shall use the active scope at read time
    Given the services were built before any profile was active
    When the "Classic" profile becomes active
    Then the raid list, raid count and character history should hold only Nowhere Keep and Molten Core

  @ears_ubiquitous
  Scenario: PROF-08 The desktop and CLI shall start in the saved active profile
    Given "Classic" on "classic" is saved as the active profile
    When the desktop and CLI context starts
    Then its active profile should be "Classic"
    When the CLI runs the consumes command
    Then the command should import from "https://classic.warcraftlogs.com/api/v2/client"

  @ears_ubiquitous @auth
  Scenario: IDENT-01 The desktop sign-in shall use Authorization Code with PKCE and the `identify` scope only, holding no client secret
    When the user signs in with Discord in the browser for the application "app"
    Then the browser should have asked for the code with an S256 challenge and the identify scope only
    And the code should have been exchanged with the challenge's verifier and no client secret
    And the Discord account "123456789" should be linked

  @ears_unwanted_behavior @auth
  Scenario Outline: IDENT-02 If the callback's state differs from the one issued, or carries an error, then the service shall link nothing
    When the Discord callback comes back <answer>
    Then the sign-in should fail with "<message>"
    And no Discord account should be linked

    Examples:
      | answer                   | message        |
      | with a forged state      | wrong state    |
      | with access denied       | access_denied  |
      | with nothing             | timed out      |

  @ears_event_driven @auth
  Scenario: IDENT-04 When `DISCORD_OAUTH_URL` is set, the flow shall use that site, so the Toads fake Discord serves development
    Given DISCORD_OAUTH_URL is "http://localhost:8099/"
    When the user signs in with Discord in the browser for the application "app"
    Then the browser should have opened "http://localhost:8099/oauth2/authorize"
