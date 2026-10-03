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

  @ears_state_driven
  Scenario: PROF-10 While a profile is active, the guild list shall show only its guild and era
    Given Warcraft Logs lists Molten Core, Karazhan and Nowhere Keep for guild 9
    When the "The Burning Crusade" profile for guild 9 becomes active
    Then the guild report list should hold Karazhan and Nowhere Keep, asked of guild 9

  @ears_event_driven @database
  Scenario: PROF-11 When a profile imports a raid, the profile shall list it without a backfill
    Given Warcraft Logs lists Molten Core, Karazhan and Nowhere Keep for guild 9
    And no raid is stored
    When the "The Burning Crusade" profile for guild 9 becomes active
    And Karazhan is fetched from Warcraft Logs and saved
    Then Karazhan should be on "fresh" in "The Burning Crusade"
    And the profile's raid list should hold Karazhan only

  @ears_unwanted_behavior
  Scenario: PROF-12 If a profile's site is not the client's, then the service shall import nothing
    Given Warcraft Logs lists Molten Core, Karazhan and Nowhere Keep for guild 9
    When a profile on "forever" is activated
    Then importing the guild's new reports should fail without asking Warcraft Logs anything

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

  @ears_event_driven @auth
  Scenario: IDENT-05 When a member redeems a code from the bot, the app shall link to the Hub and publish its profiles
    Given the Toads bot gave "123456789" a link code
    And this app has the profiles "TBC" and "Era" with "TBC" active
    When the code is redeemed in this app
    Then the app should be linked to the Hub as "123456789"
    And the Hub should hold the profiles "TBC" and "Era" for "123456789"

  @ears_event_driven @auth
  Scenario: IDENT-06 When the bot sees a Discord user, the bridge shall resolve them to their named or active profile
    Given the Toads bot gave "123456789" a link code
    And this app has the profiles "TBC" and "Era" with "TBC" active
    When the code is redeemed in this app
    Then the bot should resolve "123456789" to "TBC", and to "Era" when asked for "era"
    And the bot should resolve "555" to no profile

  @ears_unwanted_behavior @auth
  Scenario: IDENT-07 If a code was issued to another Discord user than the linked one, then the app shall link nothing
    Given the Discord account "123456789" is linked
    And the Toads bot gave "555" a link code
    When the code is redeemed in this app
    Then the link should be refused as someone else's
    And the app should not be linked to the Hub
