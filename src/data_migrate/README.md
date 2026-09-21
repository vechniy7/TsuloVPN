# Миграция Upstash → SQLite

`from_rdb.json.gz` — снимок пользователей/заказов из Upstash RDB.
При первом старте с пустой БД `/data/tsulovpn.db` данные импортируются автоматически.

Повторный импорт не выполняется (`meta.rdb_imported=1`).
