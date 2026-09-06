# rememfile
This Python script calculates hash sums of specified files and stores them for
later lookup.

I wrote this script because I often forgot which files I have moved or copied
from one location to another.

Entries live in **namespaces**, so you can keep separate hash sets (e.g. one
per backup destination or one per machine) and compare or combine them with
set operations (union/intersection/complement/xor).

## Where are the hash sums stored
In `~/.rememfile.db`. Databases created by older versions of this script are
migrated automatically the first time you run the new version; your existing
entries end up in the default namespace.

## How to install
Download `rememfile.py` and run it in a terminal. You may want to consider
adding it to your `PATH` for easier access.

This script uses only standard libraries, so you don't need to install any
dependencies.

## Version requirements
Requires Python 3.3 or later (tested only in Python 3.10, though)

## Basic usage

```terminal
$ ls
myfile1.png    myfile2.txt    myfile3.c
$ cp myfile1.png /backups/photo.png
$ cp myfile2.txt /backups/notes.txt
$ rememfile.py set /backups/*
CREATED /backups/photo.png
CREATED /backups/notes.txt
$ rememfile.py get myfile1.png myfile2.txt myfile3.c
HIT myfile1.png -> /backups/photo.png
HIT myfile2.txt -> /backups/notes.txt
```

`set`/`get`/`unset`/`clear` all operate on the **default namespace** unless
you pass `-n`/`--namespace <id-or-name>`.

## Namespaces

```terminal
$ rememfile.py namespace create --name laptop
CREATED namespace laptop (id=2)
$ rememfile.py set -n laptop ~/Documents/*
CREATED /home/user/Documents/report.pdf
$ rememfile.py namespace list
1	#1	3 entries (default)
2	laptop	1 entries
$ rememfile.py namespace rename laptop old-laptop
$ rememfile.py namespace delete old-laptop
```

A namespace can be created without a name, in which case it's only
referenceable by its numeric id (shown as `#<id>` in listings). A
`--namespace`/positional namespace argument is resolved as a numeric id
first (if a namespace with that id exists), otherwise as a name — so a
namespace literally *named* a number is normally reachable by that name, but
loses to an unrelated namespace that happens to have that id.

The default namespace is created automatically and can't be deleted (use
`clear` to empty it instead).

## Set operations

Compare two namespaces, or combine one into another, using UNION,
INTERSECTION, COMPLEMENT (`namespace_a` minus `namespace_b`), or XOR
(symmetric difference), over one of three element views:

- `--by pair`: elements are `(path, hash)` pairs — "do these two namespaces
  match exactly?"
- `--by name`: elements are paths, hashes ignored — "which files are missing
  on one side?"
- `--by hash`: elements are content hashes, paths ignored — "which file
  *contents* are missing on one side?"

`compare` is read-only and prints the result; add `--into [NAME]` to also
save it as a new namespace. `combine` applies the operation in place into
the first (target) namespace, leaving the second (source) namespace
untouched.

```terminal
$ rememfile.py compare 1 laptop --op complement --by name
/home/user/Documents/notes.txt
$ rememfile.py compare 1 laptop --op intersection --by hash --into shared
CREATED namespace shared (id=3) with 1 entries.
$ rememfile.py combine 1 laptop --op union --by pair
UPDATED namespace #1 (id=1) via union by pair: 4 entries.
```

If a name/hash-keyed operation would need to store the same path under two
different hashes (e.g. the same file path has different content in each
namespace), the operation aborts with an error listing the conflicting
paths — nothing is written.
