<!-- BEGIN game-on-yasuki -->

## game-on-yasuki

Card data is file-first. The committed YAML under `yasuki_core/assets/database/` is the source of
truth and PostgreSQL is a derived cache, so a card is corrected in the YAML and reloaded with
`install-db --force`. Never edit the database to fix a card.

A card's id is derived from its printed title, and is written down nowhere you can edit. A handler
keyed on a misspelled id registers happily, never fires, and raises nothing.

Game pieces are frozen dataclasses. They change through their transition methods, never by
assignment.

This package ships agent skills covering these in more detail, one per kind of task.
`yasuki-install-skills` places them where your agent will find them.

<!-- END game-on-yasuki -->
