#! /usr/bin/python3

import sys
import os.path
import sqlite3
import hashlib
import argparse
from datetime import datetime

DB_FILE_PATH = "~/.rememfile.db"

class HashDatabase:
    def __init__(self):
        self.open_database()

    def open_database(self):
        target_path = os.path.expanduser(DB_FILE_PATH)
        db = sqlite3.connect(target_path)
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
            hashes (
                name TEXT PRIMARY KEY,
                hash TEXT
            )
        """)
        cursor.close()
        db.commit()
        self.db = db

    def store_hash(self, name, hash):
        cursor = self.db.cursor()
        cursor.execute("""
            REPLACE INTO hashes (name, hash) VALUES (?, ?)
        """, (name, hash))
        cursor.close()
        self.db.commit()

    def delete_by_hash(self, hash):
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM hashes WHERE hash = ?
        """, (hash,))
        cursor.close()
        self.db.commit()

    def delete_by_name(self, name):
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM hashes WHERE name = ?
        """, (name,))
        cursor.close()
        self.db.commit()

    def delete_all(self):
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM hashes
        """)
        cursor.close()
        self.db.commit()

    def get_all_hashes(self):
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT name, hash FROM hashes
        """)
        cursor.close()
        self.db.commit()

    def get_hashes(self, hash):
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT name, hash FROM hashes
            WHERE hash = ?
        """, (hash,))
        result = cursor.fetchall()
        cursor.close()
        return result

    def get_hash_by_name(self, name):
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT name, hash FROM hashes
            WHERE name = ?
        """, (name,))
        result = cursor.fetchone()
        cursor.close()
        return result

    def get_number_of_hashes(self):
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM hashes
        """)
        result = cursor.fetchone()
        cursor.close()
        return result[0]

def print_to_stderr_with_time(msg: str):
    print("[{}] {}".format(datetime.now(), msg), file=sys.stderr)

def calculate_hash_digest(filepath: str):
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

def _set_hash(
    db: HashDatabase,
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
        row = db.get_hash_by_name(abspath)
        if row is not None:
            name, hash = row
            state = "UPDATED" if hash != hexdigest else "NCHANGE"
    if state not in ("NCHANGE", "FILEERR"):
        LOGVERBOSE("storing hash of '{}'".format(abspath))
        db.store_hash(abspath, hexdigest)
    elif state == "NCHANGE":
        LOGVERBOSE("hash unchanged, skipping '{}'".format(abspath))
    return (state, hexdigest)

def _set_hashes(
    filepaths: list,
    show_hashes: bool = False,
    show_absolute_paths: bool = False,
    show_all: bool = False,
    silent: bool = False,
    verbose: bool = False,
):
    if verbose:
        print_to_stderr_with_time("opening hash database")
    db = HashDatabase()
    result = []
    for fp in filepaths:
        abspath = os.path.abspath(fp)
        state, hexdigest = _set_hash(db, abspath, verbose)
        path_to_display = abspath if show_absolute_paths else fp
        if (
            not silent
            and (show_all or state in ("CREATED", "UPDATED", "FILEERR"))
        ):
            if show_hashes:
                print("{} {} {}".format(state, hexdigest, path_to_display))
            else:
                print("{} {}".format(state, path_to_display))
        result.append((state, hexdigest, abspath))
    return result

def set_hashes(filepaths: list):
    return _set_hashes(filepaths, silent=True, verbose=False)

def _get_hash(
    db: HashDatabase,
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
        hashes = db.get_hashes(hexdigest)
        state = "HIT" if hashes else "N/A"
    return (state, hexdigest, hashes)

def _get_hashes(
    filepaths: list,
    show_hashes: bool = False,
    show_absolute_paths: bool = False,
    show_all: bool = False,
    silent: bool = False,
    verbose: bool = False,
):
    if verbose:
        print_to_stderr_with_time("opening hash database")
    db = HashDatabase()
    result = []
    for fp in filepaths:
        abspath = os.path.abspath(fp)
        state, hexdigest, hashes = _get_hash(db, abspath, verbose)
        src_path_to_display = abspath if show_absolute_paths else fp
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
    return result

def get_hashes(filepaths: list):
    return _get_hashes(filepaths, silent=True, verbose=False)

def _unset_hash(
    db: HashDatabase,
    filepath: str,
    verbose: bool = False,
):
    LOGVERBOSE = lambda msg: verbose and print_to_stderr_with_time(msg)
    abspath = os.path.abspath(filepath)
    row = db.get_hash_by_name(abspath)
    name, hash = "", "-"*64
    if row is not None:
        name, hash = row
        LOGVERBOSE("deleting hash of '{}'".format(abspath))
        db.delete_by_name(abspath)
    else:
        LOGVERBOSE("hash not found, skipping '{}'".format(abspath))
    state = "DELETED" if row is not None else "NOENTRY"
    return (state, hash, name)

def _unset_hashes(
    filepaths: list,
    show_hashes: bool = False,
    show_absolute_paths: bool = False,
    show_all: bool = False,
    silent: bool = False,
    verbose: bool = False,
):
    if verbose:
        print_to_stderr_with_time("opening hash database")
    db = HashDatabase()
    result = []
    for fp in filepaths:
        abspath = os.path.abspath(fp)
        state, hash, name = _unset_hash(db, abspath, verbose)
        path_to_display = abspath if show_absolute_paths else fp
        if not silent and (show_all or state == "DELETED"):
            if show_hashes:
                print("{} {} {}".format(state, hash, path_to_display))
            else:
                print("{} {}".format(state, path_to_display))
        result.append((state, hash, abspath))
    return result

def unset_hashes(filepaths: list):
    return _unset_hashes(filepaths, silent=True, verbose=False)

def _clear_hashes(
    filepaths: list,
    silent: bool = False,
    verbose: bool = False,
):
    LOGVERBOSE = lambda msg: verbose and print_to_stderr_with_time(msg)
    LOGVERBOSE("opening hash database")
    db = HashDatabase()
    LOGVERBOSE("querying row counts of 'hashes' table")
    count = db.get_number_of_hashes()
    LOGVERBOSE("deleting everything in 'hashes' table")
    db.delete_all()
    if not silent:
        print("Successfully deleted {} entries.".format(count))
    return count

def clear_hashes(filepaths: list):
    return _clear_hashes(filepaths, silent=True, verbose=False)

def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "Remember the files at specific paths and compare them later."
        )
    )
    parser.add_argument(
        "action",
        help=(
            "s or set:   store the hash sums of the given files\n"
            "g or get:   retrieve stored file paths that share the same hash "
            "sum\n"
            "u or unset: remove specific file paths from the database\n"
            "c or clear: remove all entries from the database\n"
        )
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "files to work on "
            "(relative paths are automatically converted to absolute paths)"
        )
    )
    parser.add_argument(
        "-s",
        "--silent",
        action="store_true",
        help="run silently"
    )
    parser.add_argument(
        "-a",
        "--show-absolute-paths",
        action="store_true",
        help="show absolute paths"
    )
    parser.add_argument(
        "-H",
        "--show-hashes",
        action="store_true",
        help="show hashes"
    )
    parser.add_argument(
        "-A",
        "--show-all",
        action="store_true",
        help=(
            "show all states (shows only CREATED, UPDATED, HIT, DELETED, "
            "FILEERR, ERR by default)"
        )
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="recursively choose files below directories"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="run verbosely (print progress to stderr)"
    )
    arguments = parser.parse_args()
    if arguments.action in ("s", "set"):
        _set_hashes(
            arguments.files,
            arguments.show_hashes,
            arguments.show_absolute_paths,
            arguments.show_all,
            arguments.silent,
            arguments.verbose,
        )
    elif arguments.action in ("g", "get"):
        _get_hashes(
            arguments.files,
            arguments.show_hashes,
            arguments.show_absolute_paths,
            arguments.show_all,
            arguments.silent,
            arguments.verbose,
        )
    elif arguments.action in ("u", "unset"):
        _unset_hashes(
            arguments.files,
            arguments.show_hashes,
            arguments.show_absolute_paths,
            arguments.show_all,
            arguments.silent,
            arguments.verbose,
        )
    elif arguments.action in ("c", "clear"):
        _clear_hashes(
            arguments.files,
            arguments.silent,
            arguments.verbose,
        )
    else:
        parser.print_usage()
        print(
            "{}: error: action must be one of '[s]et', '[g]et', '[u]nset', "
            "or '[c]lear'".format(sys.argv[0])
        )
        return 2
    return 0

if __name__ == "__main__":
    retval = main()
    sys.exit(retval)
