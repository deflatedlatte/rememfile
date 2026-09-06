#! /usr/bin/python3

import sys
import os
import os.path
import sqlite3
import hashlib
import argparse
from datetime import datetime

DB_FILE_PATH = "~/.rememfile.db"

_INTO_NOT_REQUESTED = object()

class NamespaceNotFoundError(Exception):
    pass

class DuplicateNamespaceNameError(Exception):
    pass

class SetOpConflictError(Exception):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__(
            "conflicting hash values for {} name(s)".format(len(conflicts))
        )

class HashDatabase:
    def __init__(self):
        self.open_database()

    def open_database(self):
        target_path = os.path.expanduser(DB_FILE_PATH)
        db = sqlite3.connect(target_path)
        db.execute("PRAGMA foreign_keys = ON")
        cursor = db.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS
            metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS
            namespaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            );
        """)
        cursor.execute("PRAGMA table_info(hashes)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        needs_migration = bool(existing_columns) and (
            "namespace_id" not in existing_columns
        )
        if needs_migration:
            cursor.execute("ALTER TABLE hashes RENAME TO hashes_pre_namespaces")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS
            hashes (
                namespace_id INTEGER NOT NULL
                    REFERENCES namespaces (id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                hash TEXT NOT NULL,
                PRIMARY KEY (namespace_id, name)
            );
        """)
        cursor.close()
        db.commit()
        self.db = db
        self._ensure_default_namespace()
        if needs_migration:
            cursor = self.db.cursor()
            cursor.execute("""
                INSERT INTO hashes (namespace_id, name, hash)
                SELECT ?, name, hash FROM hashes_pre_namespaces
            """, (self.default_namespace_id,))
            cursor.execute("DROP TABLE hashes_pre_namespaces")
            cursor.close()
            self.db.commit()

    def _ensure_default_namespace(self):
        cursor = self.db.cursor()
        cursor.execute(
            "SELECT value FROM metadata WHERE key = 'default_namespace_id'"
        )
        row = cursor.fetchone()
        if row is not None:
            cursor.close()
            self.default_namespace_id = int(row[0])
            return
        cursor.execute("INSERT INTO namespaces (name) VALUES (NULL)")
        default_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO metadata (key, value)
            VALUES ('default_namespace_id', ?)
        """, (str(default_id),))
        cursor.close()
        self.db.commit()
        self.default_namespace_id = default_id

    def create_namespace(self, name=None):
        cursor = self.db.cursor()
        try:
            cursor.execute(
                "INSERT INTO namespaces (name) VALUES (?)", (name,)
            )
        except sqlite3.IntegrityError:
            cursor.close()
            raise DuplicateNamespaceNameError(name)
        new_id = cursor.lastrowid
        cursor.close()
        self.db.commit()
        return new_id

    def delete_namespace(self, namespace_id):
        if namespace_id == self.default_namespace_id:
            raise ValueError("cannot delete the default namespace")
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM namespaces WHERE id = ?", (namespace_id,))
        deleted = cursor.rowcount
        cursor.close()
        self.db.commit()
        return deleted > 0

    def rename_namespace(self, namespace_id, new_name):
        cursor = self.db.cursor()
        try:
            cursor.execute(
                "UPDATE namespaces SET name = ? WHERE id = ?",
                (new_name, namespace_id),
            )
        except sqlite3.IntegrityError:
            cursor.close()
            raise DuplicateNamespaceNameError(new_name)
        updated = cursor.rowcount
        cursor.close()
        self.db.commit()
        return updated > 0

    def list_namespaces(self):
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT namespaces.id, namespaces.name, COUNT(hashes.name)
            FROM namespaces
            LEFT JOIN hashes ON hashes.namespace_id = namespaces.id
            GROUP BY namespaces.id
            ORDER BY namespaces.id
        """)
        result = cursor.fetchall()
        cursor.close()
        return result

    def resolve_namespace(self, ref):
        if ref is None:
            return self.default_namespace_id
        cursor = self.db.cursor()
        try:
            as_id = int(ref)
        except ValueError:
            as_id = None
        if as_id is not None:
            cursor.execute("SELECT id FROM namespaces WHERE id = ?", (as_id,))
            row = cursor.fetchone()
            if row is not None:
                cursor.close()
                return row[0]
        cursor.execute("SELECT id FROM namespaces WHERE name = ?", (ref,))
        row = cursor.fetchone()
        cursor.close()
        if row is None:
            raise NamespaceNotFoundError(ref)
        return row[0]

    def get_namespace_display(self, namespace_id):
        cursor = self.db.cursor()
        cursor.execute(
            "SELECT name FROM namespaces WHERE id = ?", (namespace_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        if row is None:
            raise NamespaceNotFoundError(namespace_id)
        return row[0] if row[0] is not None else "#{}".format(namespace_id)

    def store_hash(self, namespace_id, name, hash):
        cursor = self.db.cursor()
        cursor.execute("""
            REPLACE INTO hashes (namespace_id, name, hash) VALUES (?, ?, ?)
        """, (namespace_id, name, hash))
        cursor.close()
        self.db.commit()

    def delete_by_hash(self, namespace_id, hash):
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM hashes WHERE namespace_id = ? AND hash = ?
        """, (namespace_id, hash))
        cursor.close()
        self.db.commit()

    def delete_by_name(self, namespace_id, name):
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM hashes WHERE namespace_id = ? AND name = ?
        """, (namespace_id, name))
        cursor.close()
        self.db.commit()

    def delete_all(self, namespace_id):
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM hashes WHERE namespace_id = ?", (namespace_id,))
        count = cursor.rowcount
        cursor.close()
        self.db.commit()
        return count

    def get_all_hashes(self, namespace_id):
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT name, hash FROM hashes WHERE namespace_id = ?
        """, (namespace_id,))
        result = cursor.fetchall()
        cursor.close()
        return result

    def get_hashes(self, namespace_id, hash):
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT name, hash FROM hashes
            WHERE namespace_id = ? AND hash = ?
        """, (namespace_id, hash))
        result = cursor.fetchall()
        cursor.close()
        return result

    def get_hash_by_name(self, namespace_id, name):
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT name, hash FROM hashes
            WHERE namespace_id = ? AND name = ?
        """, (namespace_id, name))
        result = cursor.fetchone()
        cursor.close()
        return result

    def get_number_of_hashes(self, namespace_id):
        cursor = self.db.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM hashes WHERE namespace_id = ?", (namespace_id,)
        )
        result = cursor.fetchone()
        cursor.close()
        return result[0]

    def replace_namespace_rows(self, namespace_id, rows):
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM hashes WHERE namespace_id = ?", (namespace_id,))
        cursor.executemany("""
            INSERT INTO hashes (namespace_id, name, hash) VALUES (?, ?, ?)
        """, [(namespace_id, name, hash) for name, hash in rows])
        cursor.close()
        self.db.commit()

def print_to_stderr_with_time(msg: str):
    print("[{}] {}".format(datetime.now(), msg), file=sys.stderr)

def calculate_hash_digest(filepath: str):
    if not os.path.isfile(filepath):
        return None
    digest = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            data = f.read(4096)
            while data:
                digest.update(data)
                data = f.read(4096)
    except OSError as exc:
        return None
    hexdigest = digest.hexdigest()
    return hexdigest

# ---------------------------------------------------------------------------
# Set operations (pure functions, no I/O)
# ---------------------------------------------------------------------------

def _project(rows, by):
    if by == "pair":
        return set(rows)
    if by == "name":
        return set(r[0] for r in rows)
    if by == "hash":
        return set(r[1] for r in rows)
    raise ValueError("unknown 'by' key: {}".format(by))

def _apply_set_op(set_a, set_b, op):
    if op == "union":
        return set_a | set_b
    if op == "intersection":
        return set_a & set_b
    if op == "complement":
        return set_a - set_b
    if op == "xor":
        return set_a ^ set_b
    raise ValueError("unknown set operation: {}".format(op))

def compute_set_op(rows_a: list, rows_b: list, op: str, by: str):
    """
    Compute UNION/INTERSECTION/COMPLEMENT(A-B)/XOR of two (name, hash) row
    sets, keyed by full pair, name only, or hash only. The result is always
    materialized back into full (name, hash) rows, since that's all a
    namespace can store. Raises SetOpConflictError if two contributing rows
    would need to occupy the same name with different hashes.
    """
    set_a = _project(rows_a, by)
    set_b = _project(rows_b, by)
    result_keys = _apply_set_op(set_a, set_b, op)
    if by == "pair":
        candidate_rows = result_keys
    else:
        key_index = 0 if by == "name" else 1
        candidate_rows = {
            row for row in (set(rows_a) | set(rows_b))
            if row[key_index] in result_keys
        }
    name_to_hashes = {}
    for name, hash_ in candidate_rows:
        name_to_hashes.setdefault(name, set()).add(hash_)
    conflicts = {
        name: hashes for name, hashes in name_to_hashes.items()
        if len(hashes) > 1
    }
    if conflicts:
        raise SetOpConflictError(conflicts)
    return sorted((name, next(iter(hashes))) for name, hashes in name_to_hashes.items())

def _set_hash(
    db: HashDatabase,
    namespace_id: int,
    filepath: str,
    verbose: bool = False,
):
    LOGVERBOSE = lambda msg: verbose and print_to_stderr_with_time(msg)
    state = "CREATED"
    abspath = os.path.abspath(filepath)
    LOGVERBOSE("calculating hash for '{}'".format(abspath))
    hexdigest = calculate_hash_digest(abspath)
    if hexdigest is None:
        LOGVERBOSE("failed to calculate hash of '{}'".format(abspath))
        state = "FILEERR"
        hexdigest = "-"*64
    else:
        LOGVERBOSE("'{}'={}".format(abspath, hexdigest))
        row = db.get_hash_by_name(namespace_id, abspath)
        if row is not None:
            name, hash = row
            state = "UPDATED" if hash != hexdigest else "NCHANGE"
    if state not in ("NCHANGE", "FILEERR"):
        LOGVERBOSE("storing hash of '{}'".format(abspath))
        db.store_hash(namespace_id, abspath, hexdigest)
    elif state == "NCHANGE":
        LOGVERBOSE("hash unchanged, skipping '{}'".format(abspath))
    return (state, hexdigest)

def _set_hashes(
    filepaths: list,
    namespace_ref: str = None,
    show_hashes: bool = False,
    show_absolute_paths: bool = False,
    show_all: bool = False,
    recursive: bool = False,
    silent: bool = False,
    verbose: bool = False,
):
    if verbose:
        print_to_stderr_with_time("opening hash database")
    db = HashDatabase()
    namespace_id = db.resolve_namespace(namespace_ref)
    result = []
    def process_one_file(filepath):
        abspath = os.path.abspath(filepath)
        state, hexdigest = _set_hash(db, namespace_id, abspath, verbose)
        path_to_display = abspath if show_absolute_paths else filepath
        if (
            not silent
            and (show_all or state in ("CREATED", "UPDATED", "FILEERR"))
        ):
            if show_hashes:
                print("{} {} {}".format(state, hexdigest, path_to_display))
            else:
                print("{} {}".format(state, path_to_display))
        result.append((state, hexdigest, abspath))
    for fp in filepaths:
        if recursive and os.path.isdir(fp):
            for root, dirs, files in os.walk(fp):
                for fp_r in files:
                    process_one_file(os.path.join(root, fp_r))
        else:
            process_one_file(fp)
    return result

def set_hashes(filepaths: list, namespace_ref: str = None):
    return _set_hashes(filepaths, namespace_ref, silent=True, verbose=False)

def _get_hash(
    db: HashDatabase,
    namespace_id: int,
    filepath: str,
    verbose: bool = False,
):
    LOGVERBOSE = lambda msg: verbose and print_to_stderr_with_time(msg)
    abspath = os.path.abspath(filepath)
    LOGVERBOSE("calculating hash for '{}'".format(abspath))
    hexdigest = calculate_hash_digest(abspath)
    if hexdigest is None:
        LOGVERBOSE("failed to calculate hash of '{}'".format(abspath))
        state = "ERR"
        hexdigest = "-"*64
        hashes = []
    else:
        LOGVERBOSE("'{}'={}".format(abspath, hexdigest))
        hashes = db.get_hashes(namespace_id, hexdigest)
        state = "HIT" if hashes else "N/A"
    return (state, hexdigest, hashes)

def _get_hashes(
    filepaths: list,
    namespace_ref: str = None,
    show_hashes: bool = False,
    show_absolute_paths: bool = False,
    show_all: bool = False,
    recursive: bool = False,
    silent: bool = False,
    verbose: bool = False,
):
    if verbose:
        print_to_stderr_with_time("opening hash database")
    db = HashDatabase()
    namespace_id = db.resolve_namespace(namespace_ref)
    result = []
    def process_one_file(filepath):
        abspath = os.path.abspath(filepath)
        state, hexdigest, hashes = _get_hash(db, namespace_id, abspath, verbose)
        src_path_to_display = abspath if show_absolute_paths else filepath
        dst_path_to_display = ",".join([r[0] for r in hashes])
        if dst_path_to_display:
            dst_path_to_display = "-> " + dst_path_to_display
        if (
            not silent
            and (show_all or state in ("HIT", "ERR"))
        ):
            if show_hashes:
                print("{} {} {} {}".format(
                    state,
                    hexdigest,
                    src_path_to_display,
                    dst_path_to_display,
                ))
            else:
                print("{} {} {}".format(
                    state,
                    src_path_to_display,
                    dst_path_to_display,
                ))
        result.append((state, hexdigest, abspath, [r[0] for r in hashes]))
    for fp in filepaths:
        if recursive and os.path.isdir(fp):
            for root, dirs, files in os.walk(fp):
                for fp_r in files:
                    process_one_file(os.path.join(root, fp_r))
        else:
            process_one_file(fp)
    return result

def get_hashes(filepaths: list, namespace_ref: str = None):
    return _get_hashes(filepaths, namespace_ref, silent=True, verbose=False)

def _unset_hash(
    db: HashDatabase,
    namespace_id: int,
    filepath: str,
    verbose: bool = False,
):
    LOGVERBOSE = lambda msg: verbose and print_to_stderr_with_time(msg)
    abspath = os.path.abspath(filepath)
    row = db.get_hash_by_name(namespace_id, abspath)
    name, hash = "", "-"*64
    if row is not None:
        name, hash = row
        LOGVERBOSE("deleting hash of '{}'".format(abspath))
        db.delete_by_name(namespace_id, abspath)
    else:
        LOGVERBOSE("hash not found, skipping '{}'".format(abspath))
    state = "DELETED" if row is not None else "NOENTRY"
    return (state, hash, name)

def _unset_hashes(
    filepaths: list,
    namespace_ref: str = None,
    show_hashes: bool = False,
    show_absolute_paths: bool = False,
    show_all: bool = False,
    recursive: bool = False,
    silent: bool = False,
    verbose: bool = False,
):
    if verbose:
        print_to_stderr_with_time("opening hash database")
    db = HashDatabase()
    namespace_id = db.resolve_namespace(namespace_ref)
    result = []
    def process_one_file(filepath):
        abspath = os.path.abspath(filepath)
        state, hash, name = _unset_hash(db, namespace_id, abspath, verbose)
        path_to_display = abspath if show_absolute_paths else filepath
        if not silent and (show_all or state == "DELETED"):
            if show_hashes:
                print("{} {} {}".format(state, hash, path_to_display))
            else:
                print("{} {}".format(state, path_to_display))
        result.append((state, hash, abspath))
    for fp in filepaths:
        if recursive and os.path.isdir(fp):
            for root, dirs, files in os.walk(fp):
                for fp_r in files:
                    process_one_file(os.path.join(root, fp_r))
        else:
            process_one_file(fp)
    return result

def unset_hashes(filepaths: list, namespace_ref: str = None):
    return _unset_hashes(filepaths, namespace_ref, silent=True, verbose=False)

def _clear_hashes(
    namespace_ref: str = None,
    silent: bool = False,
    verbose: bool = False,
):
    LOGVERBOSE = lambda msg: verbose and print_to_stderr_with_time(msg)
    LOGVERBOSE("opening hash database")
    db = HashDatabase()
    namespace_id = db.resolve_namespace(namespace_ref)
    display = db.get_namespace_display(namespace_id)
    LOGVERBOSE("querying row counts of namespace {}".format(display))
    count = db.get_number_of_hashes(namespace_id)
    LOGVERBOSE("deleting all entries in namespace {}".format(display))
    db.delete_all(namespace_id)
    if not silent:
        print("Successfully deleted {} entries from namespace {}.".format(
            count, display
        ))
    return count

def clear_hashes(namespace_ref: str = None):
    return _clear_hashes(namespace_ref, silent=True, verbose=False)

# ---------------------------------------------------------------------------
# Namespace management
# ---------------------------------------------------------------------------

def _namespace_create(name=None, silent=False, verbose=False):
    db = HashDatabase()
    ns_id = db.create_namespace(name)
    if not silent:
        display = name if name is not None else "#{}".format(ns_id)
        print("CREATED namespace {} (id={})".format(display, ns_id))
    return ns_id

def _namespace_delete(namespace_ref, silent=False, verbose=False):
    db = HashDatabase()
    ns_id = db.resolve_namespace(namespace_ref)
    display = db.get_namespace_display(ns_id)
    db.delete_namespace(ns_id)
    if not silent:
        print("DELETED namespace {} (id={})".format(display, ns_id))
    return ns_id

def _namespace_rename(namespace_ref, new_name, silent=False, verbose=False):
    db = HashDatabase()
    ns_id = db.resolve_namespace(namespace_ref)
    old_display = db.get_namespace_display(ns_id)
    db.rename_namespace(ns_id, new_name)
    if not silent:
        print("RENAMED namespace {} (id={}) to {}".format(
            old_display, ns_id, new_name
        ))
    return ns_id

def _namespace_list(silent=False, verbose=False):
    db = HashDatabase()
    rows = db.list_namespaces()
    if not silent:
        for ns_id, name, count in rows:
            display = name if name is not None else "#{}".format(ns_id)
            marker = " (default)" if ns_id == db.default_namespace_id else ""
            print("{}\t{}\t{} entries{}".format(ns_id, display, count, marker))
    return rows

# ---------------------------------------------------------------------------
# Set operations over namespaces
# ---------------------------------------------------------------------------

def _print_set_op_result(result_rows, by):
    if by == "pair":
        for name, hash_ in result_rows:
            print("{} {}".format(name, hash_))
    elif by == "name":
        for name in sorted(name for name, _ in result_rows):
            print(name)
    elif by == "hash":
        for hash_ in sorted(set(hash_ for _, hash_ in result_rows)):
            print(hash_)

def _compare(
    namespace_a_ref,
    namespace_b_ref,
    op,
    by,
    into=_INTO_NOT_REQUESTED,
    silent=False,
    verbose=False,
):
    LOGVERBOSE = lambda msg: verbose and print_to_stderr_with_time(msg)
    db = HashDatabase()
    ns_a = db.resolve_namespace(namespace_a_ref)
    ns_b = db.resolve_namespace(namespace_b_ref)
    LOGVERBOSE("computing {} by {} of namespace {} and namespace {}".format(
        op, by, ns_a, ns_b
    ))
    rows_a = db.get_all_hashes(ns_a)
    rows_b = db.get_all_hashes(ns_b)
    result_rows = compute_set_op(rows_a, rows_b, op, by)
    if not silent:
        _print_set_op_result(result_rows, by)
    new_ns_id = None
    if into is not _INTO_NOT_REQUESTED:
        new_name = into if into else None
        new_ns_id = db.create_namespace(new_name)
        db.replace_namespace_rows(new_ns_id, result_rows)
        if not silent:
            display = new_name if new_name is not None else "#{}".format(new_ns_id)
            print("CREATED namespace {} (id={}) with {} entries.".format(
                display, new_ns_id, len(result_rows)
            ))
    return result_rows, new_ns_id

def _combine(
    target_ref,
    source_ref,
    op,
    by,
    silent=False,
    verbose=False,
):
    LOGVERBOSE = lambda msg: verbose and print_to_stderr_with_time(msg)
    db = HashDatabase()
    target_id = db.resolve_namespace(target_ref)
    source_id = db.resolve_namespace(source_ref)
    LOGVERBOSE("combining namespace {} {}= namespace {} (by {})".format(
        target_id, op, source_id, by
    ))
    rows_t = db.get_all_hashes(target_id)
    rows_s = db.get_all_hashes(source_id)
    result_rows = compute_set_op(rows_t, rows_s, op, by)
    db.replace_namespace_rows(target_id, result_rows)
    if not silent:
        display = db.get_namespace_display(target_id)
        print("UPDATED namespace {} (id={}) via {} by {}: {} entries.".format(
            display, target_id, op, by, len(result_rows)
        ))
    return result_rows

class _AliasDedupingArgumentParser(argparse.ArgumentParser):
    """
    Subparser "invalid choice" errors list every registered name, aliases
    included (e.g. 'set', 's', 'get', 'g', ...). This collapses each group
    of aliases down to the canonical name they were registered under.
    """
    def _check_value(self, action, value):
        if action.choices is None or value in action.choices:
            return super()._check_value(action, value)
        choices = action.choices
        if isinstance(choices, dict):
            seen_parsers = set()
            names = []
            for name, subparser in choices.items():
                if id(subparser) not in seen_parsers:
                    seen_parsers.add(id(subparser))
                    names.append(name)
            choices_repr = ", ".join(repr(name) for name in names)
        else:
            choices_repr = ", ".join(repr(choice) for choice in choices)
        raise argparse.ArgumentError(
            action,
            "invalid choice: {!r} (choose from {})".format(value, choices_repr)
        )

def main():
    parser = _AliasDedupingArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "Remember the files at specific paths and compare them later."
        ),
        epilog=(
            "Please note that the current version only stores hashes of "
            "regular files,\nwhile special files, such as device files, "
            "are ignored."
        )
    )
    subparsers = parser.add_subparsers(
        dest="action", required=True, metavar="action",
        help="see below for the full list"
    )

    def add_file_action_flags(sp, recursive=True):
        sp.add_argument("-s", "--silent", action="store_true", help="run silently")
        sp.add_argument(
            "-a", "--show-absolute-paths", action="store_true",
            help="show absolute paths"
        )
        sp.add_argument("-H", "--show-hashes", action="store_true", help="show hashes")
        sp.add_argument(
            "-A", "--show-all", action="store_true",
            help="show all states, not just the notable ones"
        )
        if recursive:
            sp.add_argument(
                "-r", "--recursive", action="store_true",
                help=(
                    "recursively select files within directories (does not "
                    "follow symlinks to directories)"
                )
            )
        sp.add_argument("-v", "--verbose", action="store_true", help="run verbosely")
        sp.add_argument(
            "-n", "--namespace", default=None,
            help="namespace to operate in (id or name); defaults to the default namespace"
        )

    set_parser = subparsers.add_parser(
        "set", aliases=["s"], help="store the hash sums of the given files"
    )
    set_parser.add_argument("files", nargs="*")
    add_file_action_flags(set_parser)

    get_parser = subparsers.add_parser(
        "get", aliases=["g"],
        help="retrieve stored file paths that share the same hash sum"
    )
    get_parser.add_argument("files", nargs="*")
    add_file_action_flags(get_parser)

    unset_parser = subparsers.add_parser(
        "unset", aliases=["u"], help="remove specific file paths from the database"
    )
    unset_parser.add_argument("files", nargs="*")
    add_file_action_flags(unset_parser)

    clear_parser = subparsers.add_parser(
        "clear", aliases=["c"], help="remove all entries from a namespace"
    )
    clear_parser.add_argument("-s", "--silent", action="store_true")
    clear_parser.add_argument("-v", "--verbose", action="store_true")
    clear_parser.add_argument("-n", "--namespace", default=None)

    namespace_parser = subparsers.add_parser(
        "namespace", aliases=["ns"], help="manage namespaces"
    )
    ns_sub = namespace_parser.add_subparsers(
        dest="ns_action", required=True, metavar="ns_action"
    )

    ns_create_parser = ns_sub.add_parser("create", help="create a new namespace")
    ns_create_parser.add_argument("--name", default=None)
    ns_create_parser.add_argument("-s", "--silent", action="store_true")

    ns_delete_parser = ns_sub.add_parser("delete", help="delete a namespace")
    ns_delete_parser.add_argument("namespace")
    ns_delete_parser.add_argument("-s", "--silent", action="store_true")

    ns_rename_parser = ns_sub.add_parser(
        "rename", aliases=["modify"], help="rename a namespace"
    )
    ns_rename_parser.add_argument("namespace")
    ns_rename_parser.add_argument("new_name")
    ns_rename_parser.add_argument("-s", "--silent", action="store_true")

    ns_list_parser = ns_sub.add_parser("list", help="list all namespaces")
    ns_list_parser.add_argument("-s", "--silent", action="store_true")

    def add_set_op_flags(sp):
        sp.add_argument(
            "--op", required=True,
            choices=["union", "intersection", "complement", "xor"]
        )
        sp.add_argument("--by", required=True, choices=["pair", "name", "hash"])
        sp.add_argument("-s", "--silent", action="store_true")
        sp.add_argument("-v", "--verbose", action="store_true")

    compare_parser = subparsers.add_parser(
        "compare",
        help=(
            "compute UNION/INTERSECTION/COMPLEMENT/XOR of two namespaces "
            "(read-only; complement is namespace_a minus namespace_b)"
        )
    )
    compare_parser.add_argument("namespace_a")
    compare_parser.add_argument("namespace_b")
    add_set_op_flags(compare_parser)
    compare_parser.add_argument(
        "--into", nargs="?", const="", default=_INTO_NOT_REQUESTED,
        help="also materialize the result as a new namespace (optionally named)"
    )

    combine_parser = subparsers.add_parser(
        "combine",
        help=(
            "apply UNION/INTERSECTION/COMPLEMENT/XOR in place into the "
            "target namespace (target = target op source)"
        )
    )
    combine_parser.add_argument("target")
    combine_parser.add_argument("source")
    add_set_op_flags(combine_parser)

    arguments = parser.parse_args()

    try:
        if arguments.action in ("s", "set"):
            _set_hashes(
                arguments.files,
                arguments.namespace,
                arguments.show_hashes,
                arguments.show_absolute_paths,
                arguments.show_all,
                arguments.recursive,
                arguments.silent,
                arguments.verbose,
            )
        elif arguments.action in ("g", "get"):
            _get_hashes(
                arguments.files,
                arguments.namespace,
                arguments.show_hashes,
                arguments.show_absolute_paths,
                arguments.show_all,
                arguments.recursive,
                arguments.silent,
                arguments.verbose,
            )
        elif arguments.action in ("u", "unset"):
            _unset_hashes(
                arguments.files,
                arguments.namespace,
                arguments.show_hashes,
                arguments.show_absolute_paths,
                arguments.show_all,
                arguments.recursive,
                arguments.silent,
                arguments.verbose,
            )
        elif arguments.action in ("c", "clear"):
            _clear_hashes(
                arguments.namespace,
                arguments.silent,
                arguments.verbose,
            )
        elif arguments.action in ("ns", "namespace"):
            if arguments.ns_action == "create":
                _namespace_create(arguments.name, arguments.silent)
            elif arguments.ns_action == "delete":
                _namespace_delete(arguments.namespace, arguments.silent)
            elif arguments.ns_action in ("rename", "modify"):
                _namespace_rename(
                    arguments.namespace, arguments.new_name, arguments.silent
                )
            elif arguments.ns_action == "list":
                _namespace_list(arguments.silent)
        elif arguments.action == "compare":
            _compare(
                arguments.namespace_a,
                arguments.namespace_b,
                arguments.op,
                arguments.by,
                arguments.into,
                arguments.silent,
                arguments.verbose,
            )
        elif arguments.action == "combine":
            _combine(
                arguments.target,
                arguments.source,
                arguments.op,
                arguments.by,
                arguments.silent,
                arguments.verbose,
            )
    except NamespaceNotFoundError as exc:
        print("error: namespace not found: {}".format(exc), file=sys.stderr)
        return 1
    except DuplicateNamespaceNameError as exc:
        print(
            "error: a namespace named '{}' already exists".format(exc),
            file=sys.stderr,
        )
        return 1
    except SetOpConflictError as exc:
        print(
            "error: conflicting hash values for {} name(s):".format(
                len(exc.conflicts)
            ),
            file=sys.stderr,
        )
        for name, hashes in sorted(exc.conflicts.items()):
            print("  {}: {}".format(name, ", ".join(sorted(hashes))), file=sys.stderr)
        return 1
    except ValueError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    retval = main()
    sys.exit(retval)
