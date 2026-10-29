-- Schema version 2 -> 3: label.cookiewall_seen (a pay option was offered, independent of the code).
-- Only adds a column, changes no row.
ALTER TABLE label ADD COLUMN cookiewall_seen INTEGER;
