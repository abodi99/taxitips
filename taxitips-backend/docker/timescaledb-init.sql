-- Körs en gång av postgres-imagen vid första uppstart av en tom volym
-- (mountad på /docker-entrypoint-initdb.d/). Gör tillägget tillgängligt för
-- framtida realtidsdata -- ingen hypertable skapas här, det finns inget
-- tidsseriedata-schema att göra en av än.
CREATE EXTENSION IF NOT EXISTS timescaledb;
