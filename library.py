
import json
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from logs import add_log

FILE = Path(__file__).with_name("books.json")
BACKUP_DIRECTORY = Path(__file__).with_name("backups")
READING_STATUSES = ("Want to Read", "Reading", "Finished", "Paused")


def load_library():
    if not FILE.exists():
        return {
            "books": [],
            "next_id": 1
        }

    with open(FILE, "r", encoding="utf-8") as file:
        data = json.load(file)
    for book in data.get("books", []):
        book.setdefault("category", "Uncategorized")
        book.setdefault("reading_status", "Want to Read")
    return data


def save_library(data):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    if FILE.exists() and FILE.stat().st_size:
        BACKUP_DIRECTORY.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        shutil.copy2(FILE, BACKUP_DIRECTORY / f"books-{stamp}.json")
        backups = sorted(BACKUP_DIRECTORY.glob("books-*.json"), reverse=True)
        for old_backup in backups[20:]:
            old_backup.unlink(missing_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".books-", suffix=".json.tmp", dir=FILE.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            json.dump(data, temporary_file, indent=4)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, FILE)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def normalized(value):
    return " ".join(str(value).casefold().split())


def find_duplicate(title, author, exclude_id=None, books=None):
    books = books if books is not None else load_library()["books"]
    title_key, author_key = normalized(title), normalized(author)
    return next((
        book for book in books
        if book.get("id") != exclude_id
        and normalized(book.get("title", "")) == title_key
        and normalized(book.get("author", "")) == author_key
    ), None)


def add_book(title, author, year, cover_filename=None, url=None,
             category="Uncategorized", category_confidence=None,
             category_source=None, reading_status="Want to Read",
             allow_duplicate=False, personal_rating=None):
    data = load_library()

    duplicate = find_duplicate(title, author, books=data["books"])
    if duplicate and not allow_duplicate:
        raise ValueError(f"Duplicate book: already stored as ID {duplicate['id']}")

    book = {
        "id": data["next_id"],
        "title": title,
        "author": author,
        "year": year,
        "category": category,
        "reading_status": reading_status
    }
    if personal_rating is not None:
        book["personal_rating"] = personal_rating
    if cover_filename:
        book["cover_filename"] = cover_filename
        book["cover_url"] = f"/covers/{cover_filename}"
    if url:
        book["url"] = url
    if category_confidence is not None:
        book["category_confidence"] = category_confidence
    if category_source:
        book["category_source"] = category_source

    data["books"].append(book)
    data["next_id"] += 1

    save_library(data)
    add_log("ADD", book)

    return book


def remove_book(book_id):
    data = load_library()

    for book in data["books"]:
        if book["id"] == book_id:
            data["books"].remove(book)

            save_library(data)
            add_log("REMOVE", book)

            return book

    return False


def update_book(book_id, title, author, year, url=None,
                cover_filename=None, remove_cover=False, category=None,
                category_confidence=None, category_source=None,
                reading_status=None, personal_rating=None,
                clear_personal_rating=False):
    data = load_library()

    duplicate = find_duplicate(title, author, exclude_id=book_id,
                               books=data["books"])
    if duplicate:
        raise ValueError(f"Duplicate book: already stored as ID {duplicate['id']}")

    for book in data["books"]:
        if book["id"] != book_id:
            continue

        old_cover = book.get("cover_filename")
        book.update({
            "title": title,
            "author": author,
            "year": year
        })

        if url:
            book["url"] = url
        else:
            book.pop("url", None)

        if cover_filename:
            book["cover_filename"] = cover_filename
            book["cover_url"] = f"/covers/{cover_filename}"
        elif remove_cover:
            book.pop("cover_filename", None)
            book.pop("cover_url", None)

        if category is not None:
            book["category"] = category
            if category_confidence is None:
                book.pop("category_confidence", None)
            else:
                book["category_confidence"] = category_confidence
            if category_source:
                book["category_source"] = category_source
            else:
                book.pop("category_source", None)

        if reading_status is not None:
            book["reading_status"] = reading_status
        if clear_personal_rating:
            book.pop("personal_rating", None)
        elif personal_rating is not None:
            book["personal_rating"] = personal_rating

        save_library(data)
        add_log("UPDATE", book)
        replaced_cover = old_cover if cover_filename or remove_cover else None
        return book, replaced_cover

    return None, None


def find_books(query):
    data = load_library()
    results = []
    needle = normalized(query)
    for book in data["books"]:
        haystack = " ".join(str(book.get(field, "")) for field in (
            "title", "author", "year", "category", "reading_status", "id"
        ))
        if needle in normalized(haystack):
            results.append(book)

    return results


def get_all_books():
    data = load_library()
    return data["books"]


def get_book(book_id):
    return next((book for book in get_all_books() if book["id"] == book_id), None)


def set_book_category(book_id, category, confidence=None, source="jev"):
    data = load_library()
    for book in data["books"]:
        if book["id"] != book_id:
            continue
        book["category"] = category
        if confidence is None:
            book.pop("category_confidence", None)
        else:
            book["category_confidence"] = confidence
        book["category_source"] = source
        save_library(data)
        add_log("UPDATE", book)
        return book
    return None


def set_libby_availability(book_id, availability, fetched_at):
    data = load_library()
    for book in data["books"]:
        if book["id"] != book_id:
            continue
        book["nlb_libby"] = {**availability, "updated_at": fetched_at}
        save_library(data)
        add_log("UPDATE", book)
        return book
    return None


def bulk_update_books(book_ids, category=None, reading_status=None):
    data = load_library()
    wanted = set(book_ids)
    updated = []
    for book in data["books"]:
        if book["id"] not in wanted:
            continue
        if category is not None:
            book["category"] = category
            book["category_source"] = "manual"
            book.pop("category_confidence", None)
        if reading_status is not None:
            book["reading_status"] = reading_status
        updated.append(book.copy())
    if updated:
        save_library(data)
        for book in updated:
            add_log("UPDATE", book)
    return updated


def library_stats():
    books = get_all_books()
    category_counts = Counter(
        book.get("category", "Uncategorized") for book in books
    )
    status_counts = Counter(
        book.get("reading_status", "Want to Read") for book in books
    )
    author_counts = Counter(book.get("author", "Unknown") for book in books)
    years = [book["year"] for book in books if type(book.get("year")) is int]
    return {
        "total": len(books),
        "categories": dict(category_counts.most_common()),
        "reading_statuses": {
            status: status_counts.get(status, 0) for status in READING_STATUSES
        },
        "top_authors": [
            {"author": author, "count": count}
            for author, count in author_counts.most_common(5)
        ],
        "oldest_year": min(years) if years else None,
        "newest_year": max(years) if years else None
    }
