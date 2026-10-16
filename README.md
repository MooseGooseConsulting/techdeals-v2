# TechDeals v2

Experimental work on interpreting hardware listings and preserving the evidence
needed for useful buying queries. Production intent belongs to the
[TechDeals North Star](https://github.com/MooseGooseConsulting/TechdealsHandoff/blob/main/docs/NORTH_STAR.md).

Start with the [draft execution and integration plan](docs/plans/parsing-usefulness-and-integration.md)
for repository consolidation, all known open PRs/issues, review follow-through,
semantic acceptance, and when improvements should enter the production project.
The former personal repository is preserved under organization ownership as
[techdeals-v2-review-import](https://github.com/MooseGooseConsulting/techdeals-v2-review-import).
This repository remains the canonical destination for reviewed consolidation.

The [brief](BRIEF.md) defines the v2 experiment. The
[2026-10-15 review evidence](docs/research/2026-10-15-parsing-review/README.md)
records known failures and the limits of existing checks. Successful extraction,
passing helper tests, and stored data do not establish correct application
answers. The packaged CLI and standalone extraction paths are not yet reconciled.

The [field inventory and review contract](docs/plans/field-review.md) accounts for
the reviewed standalone schema's columns and defines the evidence needed to keep,
change, or remove each field. Its generated inventory entries are unreviewed.

The execution plan is proposed work. Repository transfer and PR completion do not
establish verified parsing, deployed production repairs, or a production cutover.
