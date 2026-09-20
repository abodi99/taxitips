-- Radantal per tabell i scheman som bär TaxiTips data (tabb-separerat).
-- Används före dump och efter återställning; se restore_test.sh.
select table_schema || '.' || table_name,
       (xpath('/row/n/text()',
              query_to_xml(format('select count(*) as n from %I.%I', table_schema, table_name), false, true, '')
       ))[1]::text::bigint
from information_schema.tables
where table_schema in ('public', 'auth')
  and table_type = 'BASE TABLE'
order by 1;
