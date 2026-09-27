Feature: Storage contract
  Raid data lives behind one RaidRepository contract so the desktop app (SQLite) and the Toads Hub
  (Postgres) store and read it the same way. tests/test_store_contract.py is that contract: one module,
  parametrized over every backend, that exercises every protocol method.

  @ears_ubiquitous @database
  Scenario Outline: REQ-CORE-STORE-001 The storage contract test module shall pass unchanged on the <backend> backend
    Given the <backend> storage backend is available
    When the storage contract test module runs against the <backend> backend
    Then every contract test should pass with none skipped

    Examples:
      | backend  |
      | sqlite   |
      | postgres |

  @ears_ubiquitous @database
  Scenario: REQ-CORE-STORE-001 The SQLite and Postgres backends shall return the same results for the same writes
    Given the postgres storage backend is available
    When the same raids, player pages and role overrides are written to both backends
    Then every read method should return the same rows on both
