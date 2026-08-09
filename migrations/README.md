This folder contains simple SQL migration stubs for manual application against an existing database.

To add the `error_hint` column to an existing database, run the SQL in `0001_add_error_hint.sql` against your DB. Example (SQLite):

sqlite3 infrapilot.db < 0001_add_error_hint.sql

For PostgreSQL, use psql with the DATABASE_URL or connect and run the ALTER TABLE statement.
