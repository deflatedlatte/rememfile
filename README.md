# rememfile
This Python script calculates hash sums of specified files and stores them for
later lookup.

I wrote this script because I often forgot which files I have moved or copied
from one location to another.

## Where are the hash sums stored
In `~/.rememfile.db`.

## How to install
Download `rememfile.py` and run it in a terminal. You may want to consider
adding it to your `PATH` for easier access.

This script uses only standard libraries, so you don't need to install any
dependencies.

## Version requirements
Requires Python 3.3 or later (tested only in Python 3.10, though)

## Examples

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
