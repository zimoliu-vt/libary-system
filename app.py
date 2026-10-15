
import csv
import io
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from flask import (
    Flask, Response, request, jsonify, render_template, send_from_directory
)
from library import (
    add_book, remove_book, update_book, find_books, get_all_books,
    set_book_category, get_book, bulk_update_books, library_stats,
    find_duplicate, READING_STATUSES, set_libby_availability
)
from logs import get_logs
from jev import CATEGORIES, JevError, classify_book, is_configured
from libby import LibbyError, fetch_nlb_availability

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024

COVER_DIRECTORY = Path(__file__).with_name("covers")
ALLOWED_COVER_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif"
}

libby_job_lock = threading.Lock()
libby_job = {
    "running": False, "total": 0, "completed": 0, "failed": 0,
    "current_title": None, "started_at": None, "finished_at": None,
    "errors": []
}


@app.errorhandler(413)
def cover_too_large(_error):
    return jsonify({"error": "Cover image must be 6 MB or smaller"}), 413


def save_cover(upload):
    if not upload or not upload.filename:
        return None

    extension = ALLOWED_COVER_TYPES.get(upload.mimetype)
    if extension is None:
        raise ValueError("Cover must be a JPEG, PNG, WebP, or GIF image")

    signatures = {
        ".jpg": (b"\xff\xd8\xff",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".webp": (b"RIFF",),
        ".gif": (b"GIF87a", b"GIF89a")
    }
    header = upload.stream.read(12)
    upload.stream.seek(0)
    if not any(header.startswith(signature) for signature in signatures[extension]):
        raise ValueError("The uploaded cover is not a valid image")
    if extension == ".webp" and header[8:12] != b"WEBP":
        raise ValueError("The uploaded cover is not a valid WebP image")

    COVER_DIRECTORY.mkdir(exist_ok=True)
    filename = f"{uuid4().hex}{extension}"
    upload.save(COVER_DIRECTORY / filename)
    return filename


def validate_book_url(value):
    if value is None or not str(value).strip():
        return None
    value = str(value).strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Book URL must begin with http:// or https://")
    return value


@app.route("/covers/<path:filename>", methods=["GET"])
def book_cover(filename):
    return send_from_directory(COVER_DIRECTORY, filename)


# ==========================================
# WEBSITE HOMEPAGE
# ==========================================

@app.route("/", methods=["GET"])
def home():
    return render_template("library.html")


@app.route("/book/<int:book_id>", methods=["GET"])
def book_details(book_id):
    book = get_book(book_id)
    if book is None:
        return render_template("book.html", book=None), 404
    return render_template("book.html", book=book)


@app.route("/management", methods=["GET"])
@app.route("/managment", methods=["GET"])
def management():
    return render_template("index.html")

# ==========================================
# LIST BOOKS WITH PAGINATION
# ==========================================


@app.route("/books", methods=["GET"])
def get_books():
    books = get_all_books()
    category = request.args.get("category", "").strip()
    reading_status = request.args.get("status", "").strip()
    query = request.args.get("q", "").strip()
    if category:
        books = [
            book for book in books
            if book.get("category", "Uncategorized") == category
        ]
    if reading_status:
        books = [
            book for book in books
            if book.get("reading_status", "Want to Read") == reading_status
        ]
    if query:
        matching_ids = {book["id"] for book in find_books(query)}
        books = [book for book in books if book["id"] in matching_ids]

    sort = request.args.get("sort", "added").strip()
    sorters = {
        "title": lambda book: book.get("title", "").casefold(),
        "author": lambda book: book.get("author", "").casefold(),
        "year": lambda book: book.get("year", 0),
        "category": lambda book: book.get("category", "Uncategorized").casefold(),
        "added": lambda book: book.get("id", 0)
    }
    if sort not in sorters:
        return jsonify({"error": "Unknown sort order"}), 400
    books = sorted(books, key=sorters[sort], reverse=sort == "added")

    if "limit" not in request.args:
        return jsonify({"books": books})

    try:
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return jsonify({"error": "Invalid pagination values"}), 400

    if not 1 <= limit <= 200 or offset < 0:
        return jsonify({"error": "Invalid pagination range"}), 400

    return jsonify({
        "books": books[offset:offset + limit],
        "total": len(books),
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(books)
    })





# ==========================================
# API DOCUMENTATION
# ==========================================

@app.route("/api", methods=["GET"])
@app.route("/api.json", methods=["GET"])
def api_documentation():
    if request.path == "/api" and request.args.get("format") != "json":
        return render_template("api.html")

    return jsonify({
        "name": "Library Management API",
        "version": "1.1",
        "description": "Manage books using HTTP and JSON",
        "content_type": "application/json",

        "endpoints": {
            "list_books": {
                "method": "GET",
                "path": "/books",
                "response_example": {
                    "books": [
                        {
                            "id": 1,
                            "title": "Harry Potter",
                            "author": "J.K. Rowling",
                            "year": 1997,
                            "category": "Fantasy",
                            "reading_status": "Want to Read"
                        }
                    ]
                }
            },

            "add_book": {
                "method": "POST",
                "path": "/books/add",
                "request_format": {
                    "title": "Harry Potter",
                    "author": "J.K. Rowling",
                    "year": 1997,
                    "url": "https://example.com/books/harry-potter",
                    "auto_categorize": True,
                    "reading_status": "Want to Read",
                    "personal_rating": 5
                },
                "response_example": {
                    "status": "success",
                    "message": "Book added successfully",
                    "book": {
                        "id": 1,
                        "title": "Harry Potter",
                        "author": "J.K. Rowling",
                        "year": 1997
                    }
                }
            },

            "remove_book": {
                "method": "POST",
                "path": "/books/remove",
                "request_format": {
                    "id": 1
                },
                "response_example": {
                    "status": "success",
                    "message": "Book removed",
                    "book_id": 1
                }
            },

            "update_book": {
                "method": "POST",
                "path": "/books/update",
                "request_format": {
                    "id": 1,
                    "title": "Harry Potter and the Philosopher's Stone",
                    "author": "J.K. Rowling",
                    "year": 1997,
                    "url": "https://example.com/books/harry-potter",
                    "remove_cover": False,
                    "category": "Fantasy",
                    "reading_status": "Reading",
                    "personal_rating": 4
                }
            },

            "categorize_book": {
                "method": "POST",
                "path": "/books/categorize",
                "request_format": {"id": 1},
                "description": "Classify one book using TypeSafe Jev"
            },

            "list_categories": {
                "method": "GET",
                "path": "/categories"
            },

            "book_details": {
                "method": "GET", "path": "/book/{id}",
                "description": "Human-readable book details page"
            },

            "library_stats": {
                "method": "GET", "path": "/stats"
            },

            "bulk_update": {
                "method": "POST", "path": "/books/bulk-update",
                "request_format": {
                    "ids": [1, 2], "category": "Fantasy",
                    "reading_status": "Finished"
                }
            },

            "export_books": {
                "method": "GET", "path": "/books/export?format=json",
                "formats": ["json", "csv"]
            },

            "import_books": {
                "method": "POST", "path": "/books/import",
                "content_type": "multipart/form-data", "field": "file"
            },

            "refresh_nlb_libby": {
                "method": "POST", "path": "/books/libby-availability",
                "request_format": {"id": 1},
                "description": "Refresh public NLB Libby catalogue availability"
            },

            "bulk_nlb_libby": {
                "method": "POST", "path": "/books/libby-availability/bulk",
                "request_format": {"refresh_all": False},
                "status": "GET /books/libby-availability/bulk",
                "description": "Start or monitor a reload-safe background NLB check"
            },

            "find_books": {
                "method": "POST",
                "path": "/books/find",
                "request_format": {
                    "query": "Rowling"
                },
                "response_example": {
                    "status": "success",
                    "count": 1,
                    "books": [
                        {
                            "id": 1,
                            "title": "Harry Potter",
                            "author": "J.K. Rowling",
                            "year": 1997
                        }
                    ]
                }
            },

            "view_logs": {
                "method": "GET",
                "path": "/logs",
                "response_example": {
                    "logs": [
                        {
                            "timestamp": "2026-10-14T05:00:00+00:00",
                            "action": "ADD",
                            "book_id": 1,
                            "title": "Harry Potter",
                            "author": "J.K. Rowling"
                        }
                    ]
                }
            }
        }
    })


# ==========================================
# VIEW ACTIVITY LOGS
# ==========================================


@app.route("/logs", methods=["GET"])
def view_logs():
    logs = get_logs()
    action = request.args.get("action", "").strip().upper()
    query = request.args.get("q", "").strip().casefold()

    if action and action not in {"ADD", "UPDATE", "REMOVE"}:
        return jsonify({"error": "action must be ADD, UPDATE, or REMOVE"}), 400

    if action:
        logs = [entry for entry in logs if entry.get("action") == action]
    if query:
        logs = [
            entry for entry in logs
            if query in entry.get("title", "").casefold()
            or query in entry.get("author", "").casefold()
            or query in str(entry.get("book_id", ""))
        ]

    # Preserve old clients that request all logs
    if "limit" not in request.args:
        return jsonify({"logs": logs})

    try:
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return jsonify({
            "error": "limit and offset must be integers"
        }), 400

    if not 1 <= limit <= 200 or offset < 0:
        return jsonify({
            "error": "Invalid pagination range"
        }), 400

    total = len(logs)

    # Newest logs first, without reversing the whole list
    end = max(0, total - offset)
    start = max(0, end - limit)
    selected_logs = logs[start:end][::-1]

    return jsonify({
        "logs": selected_logs,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(selected_logs) < total
    })



# ==========================================
# LIST ALL BOOKS
# ==========================================


# ==========================================
# ADD BOOK
# ==========================================

@app.route("/books/add", methods=["GET", "POST"])
def add():

    if request.method == "GET":
        return jsonify({
            "method": "POST",
            "endpoint": "/books/add",
            "request_format": {
                "title": "Harry Potter",
                "author": "J.K. Rowling",
                "year": 1997,
                "url": "https://example.com/books/harry-potter",
                "auto_categorize": True
            },
            "return_format": {
                "status": "success",
                "message": "Book added successfully",
                "book": {
                    "id": 1,
                    "title": "Harry Potter",
                    "author": "J.K. Rowling",
                    "year": 1997
                }
            }
        })

    is_multipart = request.mimetype == "multipart/form-data"
    data = request.form.to_dict() if is_multipart else request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "Expected JSON object"
        }), 400

    title = data.get("title")
    author = data.get("author")
    year = data.get("year")
    book_url = data.get("url")
    reading_status = data.get("reading_status", "Want to Read")
    if reading_status not in READING_STATUSES:
        return jsonify({"error": "Unknown reading status"}), 400
    personal_rating = data.get("personal_rating")
    if personal_rating is None or personal_rating == "":
        personal_rating = None
    else:
        try:
            personal_rating = int(personal_rating)
        except (TypeError, ValueError):
            return jsonify({"error": "Personal rating must be 1 to 5 stars"}), 400
        if not 1 <= personal_rating <= 5:
            return jsonify({"error": "Personal rating must be 1 to 5 stars"}), 400
    auto_categorize = str(data.get("auto_categorize", "true")).lower() not in {
        "false", "0", "no", "off"
    }
    if is_multipart:
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None

    if (
        not isinstance(title, str)
        or not title.strip()
        or not isinstance(author, str)
        or not author.strip()
        or type(year) is not int
    ):
        return jsonify({
            "error": "Invalid book information",
            "expected": {
                "title": "Book title",
                "author": "Author name",
                "year": 2000
            }
        }), 400

    cover_filename = None
    classification = None
    classification_warning = None
    try:
        book_url = validate_book_url(book_url)
        duplicate = find_duplicate(title.strip(), author.strip())
        if duplicate:
            return jsonify({
                "error": f"Duplicate book: already stored as ID {duplicate['id']}"
            }), 409
        if is_multipart:
            cover_filename = save_cover(request.files.get("cover"))
        if auto_categorize and is_configured():
            try:
                classification = classify_book(title.strip(), author.strip(), year)
            except JevError as error:
                classification_warning = str(error)
        book = add_book(
            title.strip(), author.strip(), year, cover_filename, book_url,
            category=(classification or {}).get("category", "Uncategorized"),
            category_confidence=(classification or {}).get("confidence"),
            category_source="jev" if classification else None,
            reading_status=reading_status, personal_rating=personal_rating
        )
    except ValueError as error:
        if cover_filename:
            (COVER_DIRECTORY / cover_filename).unlink(missing_ok=True)
        status = 409 if str(error).startswith("Duplicate book:") else 400
        return jsonify({"error": str(error)}), status
    except Exception:
        if cover_filename:
            (COVER_DIRECTORY / cover_filename).unlink(missing_ok=True)
        raise

    response = {
        "status": "success",
        "message": "Book added successfully",
        "book": book
    }
    if classification_warning:
        response["categorization_warning"] = classification_warning
    return jsonify(response), 201


# ==========================================
# UPDATE BOOK
# ==========================================

@app.route("/books/update", methods=["GET", "POST"])
def update():
    if request.method == "GET":
        return jsonify({
            "method": "POST",
            "endpoint": "/books/update",
            "content_types": ["application/json", "multipart/form-data"],
            "request_format": {
                "id": 1,
                "title": "Dune",
                "author": "Frank Herbert",
                "year": 1965,
                "url": "https://example.com/books/dune",
                "remove_cover": False,
                "category": "Science Fiction",
                "reading_status": "Reading"
            }
        })

    is_multipart = request.mimetype == "multipart/form-data"
    data = request.form.to_dict() if is_multipart else request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected JSON object or multipart form"}), 400

    try:
        book_id = int(data.get("id")) if is_multipart else data.get("id")
        year = int(data.get("year")) if is_multipart else data.get("year")
    except (TypeError, ValueError):
        book_id = year = None

    title = data.get("title")
    author = data.get("author")
    category = data.get("category")
    if category is not None:
        category = str(category).strip()
        if category not in {*CATEGORIES, "Uncategorized"}:
            return jsonify({"error": "Unknown book category"}), 400
    reading_status = data.get("reading_status")
    if reading_status is not None and reading_status not in READING_STATUSES:
        return jsonify({"error": "Unknown reading status"}), 400
    rating_supplied = "personal_rating" in data
    personal_rating = data.get("personal_rating")
    clear_personal_rating = rating_supplied and (
        personal_rating is None or personal_rating == ""
    )
    if rating_supplied and not clear_personal_rating:
        try:
            personal_rating = int(personal_rating)
        except (TypeError, ValueError):
            return jsonify({"error": "Personal rating must be 1 to 5 stars"}), 400
        if not 1 <= personal_rating <= 5:
            return jsonify({"error": "Personal rating must be 1 to 5 stars"}), 400
    if (
        type(book_id) is not int
        or not isinstance(title, str) or not title.strip()
        or not isinstance(author, str) or not author.strip()
        or type(year) is not int
    ):
        return jsonify({"error": "Invalid book information"}), 400

    remove_cover = str(data.get("remove_cover", "")).lower() in {
        "true", "1", "yes", "on"
    }
    new_cover = None
    try:
        book_url = validate_book_url(data.get("url"))
        if is_multipart:
            new_cover = save_cover(request.files.get("cover"))
        book, old_cover = update_book(
            book_id, title.strip(), author.strip(), year,
            book_url, new_cover, remove_cover, category,
            None, "manual" if category is not None else None,
            reading_status, personal_rating, clear_personal_rating
        )
        if book is None:
            if new_cover:
                (COVER_DIRECTORY / new_cover).unlink(missing_ok=True)
            return jsonify({"error": "Book not found"}), 404
        if old_cover and Path(old_cover).name == old_cover:
            (COVER_DIRECTORY / old_cover).unlink(missing_ok=True)
    except ValueError as error:
        if new_cover:
            (COVER_DIRECTORY / new_cover).unlink(missing_ok=True)
        status = 409 if str(error).startswith("Duplicate book:") else 400
        return jsonify({"error": str(error)}), status
    except Exception:
        if new_cover:
            (COVER_DIRECTORY / new_cover).unlink(missing_ok=True)
        raise

    return jsonify({
        "status": "success",
        "message": "Book updated successfully",
        "book": book
    })


# ==========================================
# REMOVE BOOK
# ==========================================

@app.route("/books/remove", methods=["GET", "POST"])
def remove():

    if request.method == "GET":
        return jsonify({
            "method": "POST",
            "endpoint": "/books/remove",
            "request_format": {
                "id": 1
            },
            "return_format": {
                "status": "success",
                "message": "Book removed",
                "book_id": 1
            }
        })

    data = request.get_json(silent=True)

    if not isinstance(data, dict) or type(data.get("id")) is not int:
        return jsonify({
            "error": "Expected integer book ID"
        }), 400

    book_id = data["id"]

    removed_book = remove_book(book_id)

    if removed_book:
        cover_filename = removed_book.get("cover_filename")
        if cover_filename and Path(cover_filename).name == cover_filename:
            (COVER_DIRECTORY / cover_filename).unlink(missing_ok=True)
        return jsonify({
            "status": "success",
            "message": "Book removed",
            "book_id": book_id
        })

    return jsonify({
        "status": "error",
        "message": "Book not found"
    }), 404


# ==========================================
# FIND BOOKS
# ==========================================

@app.route("/books/find", methods=["GET", "POST"])
def find():

    if request.method == "GET":
        return jsonify({
            "method": "POST",
            "endpoint": "/books/find",
            "request_format": {
                "query": "Rowling",
                "status": "Finished"
            },
            "return_format": {
                "status": "success",
                "count": 1,
                "books": [
                    {
                        "id": 1,
                        "title": "Harry Potter",
                        "author": "J.K. Rowling",
                        "year": 1997
                    }
                ]
            }
        })

    data = request.get_json(silent=True)

    query = data.get("query", data.get("title")) if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(query, str):
        return jsonify({
            "error": "Expected query string"
        }), 400

    results = find_books(query)
    category = data.get("category")
    if category:
        results = [
            book for book in results
            if book.get("category", "Uncategorized") == category
        ]
    reading_status = data.get("status")
    if reading_status:
        results = [
            book for book in results
            if book.get("reading_status", "Want to Read") == reading_status
        ]

    return jsonify({
        "status": "success",
        "count": len(results),
        "books": results
    })


# ==========================================
# CATEGORIES / TYPESAFE JEV
# ==========================================

@app.route("/categories", methods=["GET"])
def categories():
    counts = {category: 0 for category in (*CATEGORIES, "Uncategorized")}
    for book in get_all_books():
        category = book.get("category", "Uncategorized")
        counts[category] = counts.get(category, 0) + 1
    return jsonify({
        "categories": list(CATEGORIES),
        "counts": counts,
        "jev_configured": is_configured()
    })


@app.route("/stats", methods=["GET"])
def stats():
    return jsonify(library_stats())


@app.route("/books/libby-availability", methods=["GET", "POST"])
def libby_availability():
    if request.method == "GET":
        return jsonify({
            "method": "POST", "endpoint": "/books/libby-availability",
            "request_format": {"id": 1},
            "source": "Public NLB OverDrive catalogue"
        })
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or type(data.get("id")) is not int:
        return jsonify({"error": "Expected integer book ID"}), 400
    book = get_book(data["id"])
    if book is None:
        return jsonify({"error": "Book not found"}), 404
    try:
        availability = fetch_nlb_availability(book["title"], book["author"])
    except LibbyError as error:
        return jsonify({"error": str(error)}), 503
    updated = set_libby_availability(
        book["id"], availability, datetime.now(timezone.utc).isoformat()
    )
    return jsonify({
        "status": "success", "message": "NLB Libby availability refreshed",
        "book": updated
    })


def run_libby_job(book_ids):
    global libby_job
    for book_id in book_ids:
        book = get_book(book_id)
        if book is None:
            with libby_job_lock:
                libby_job["completed"] += 1
                libby_job["failed"] += 1
            continue
        with libby_job_lock:
            libby_job["current_title"] = book["title"]
        try:
            availability = fetch_nlb_availability(book["title"], book["author"])
            set_libby_availability(
                book["id"], availability,
                datetime.now(timezone.utc).isoformat()
            )
        except (LibbyError, OSError, ValueError) as error:
            with libby_job_lock:
                libby_job["failed"] += 1
                if len(libby_job["errors"]) < 20:
                    libby_job["errors"].append({
                        "book_id": book_id, "title": book["title"],
                        "error": str(error)
                    })
        finally:
            with libby_job_lock:
                libby_job["completed"] += 1
            time.sleep(0.4)
    with libby_job_lock:
        libby_job["running"] = False
        libby_job["current_title"] = None
        libby_job["finished_at"] = datetime.now(timezone.utc).isoformat()


@app.route("/books/libby-availability/bulk", methods=["GET", "POST"])
def bulk_libby_availability():
    global libby_job
    if request.method == "GET":
        with libby_job_lock:
            return jsonify(dict(libby_job))

    data = request.get_json(silent=True) or {}
    refresh_all = bool(data.get("refresh_all", False))
    with libby_job_lock:
        if libby_job["running"]:
            return jsonify({
                "status": "already_running", "job": dict(libby_job)
            }), 202
        books = get_all_books()
        selected = books if refresh_all else [book for book in books if not book.get("nlb_libby")]
        libby_job = {
            "running": bool(selected), "total": len(selected), "completed": 0,
            "failed": 0, "current_title": None,
            "started_at": datetime.now(timezone.utc).isoformat() if selected else None,
            "finished_at": None, "errors": []
        }
        snapshot = dict(libby_job)
    if selected:
        threading.Thread(
            target=run_libby_job,
            args=([book["id"] for book in selected],),
            daemon=True,
            name="nlb-libby-check"
        ).start()
    return jsonify({
        "status": "started" if selected else "nothing_to_check",
        "job": snapshot
    }), 202


@app.route("/books/bulk-update", methods=["POST"])
def bulk_update():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("ids"), list):
        return jsonify({"error": "Expected a list of book IDs"}), 400
    ids = data["ids"]
    if not ids or any(type(book_id) is not int for book_id in ids):
        return jsonify({"error": "Book IDs must be integers"}), 400
    category = data.get("category")
    reading_status = data.get("reading_status")
    if category is not None and category not in {*CATEGORIES, "Uncategorized"}:
        return jsonify({"error": "Unknown book category"}), 400
    if reading_status is not None and reading_status not in READING_STATUSES:
        return jsonify({"error": "Unknown reading status"}), 400
    if category is None and reading_status is None:
        return jsonify({"error": "Choose a category or reading status"}), 400
    updated = bulk_update_books(ids, category, reading_status)
    return jsonify({
        "status": "success", "updated": len(updated), "books": updated
    })


@app.route("/books/export", methods=["GET"])
def export_books():
    books = get_all_books()
    export_format = request.args.get("format", "json").lower()
    if export_format == "json":
        payload = json.dumps({"books": books}, indent=2, ensure_ascii=False)
        return Response(
            payload, mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=library-books.json"}
        )
    if export_format == "csv":
        output = io.StringIO()
        fields = [
            "title", "author", "year", "category", "reading_status",
            "personal_rating", "url"
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for book in books:
            writer.writerow({field: book.get(field, "") for field in fields})
        return Response(
            output.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=library-books.csv"}
        )
    return jsonify({"error": "format must be json or csv"}), 400


@app.route("/books/import", methods=["POST"])
def import_books():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "Choose a JSON or CSV file"}), 400
    try:
        text = upload.read().decode("utf-8-sig")
        if upload.filename.lower().endswith(".json"):
            parsed = json.loads(text)
            records = parsed.get("books", []) if isinstance(parsed, dict) else parsed
        elif upload.filename.lower().endswith(".csv"):
            records = list(csv.DictReader(io.StringIO(text)))
        else:
            return jsonify({"error": "Import file must be JSON or CSV"}), 400
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error):
        return jsonify({"error": "Could not read the import file"}), 400
    if not isinstance(records, list):
        return jsonify({"error": "Import must contain a list of books"}), 400

    imported, skipped, errors = 0, 0, []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            errors.append(f"Row {index}: not a book object")
            continue
        title, author = str(record.get("title", "")).strip(), str(record.get("author", "")).strip()
        try:
            year = int(record.get("year"))
        except (TypeError, ValueError):
            errors.append(f"Row {index}: invalid year")
            continue
        if not title or not author:
            errors.append(f"Row {index}: title and author are required")
            continue
        if find_duplicate(title, author):
            skipped += 1
            continue
        category = str(record.get("category", "Uncategorized")).strip()
        if category not in {*CATEGORIES, "Uncategorized"}:
            category = "Uncategorized"
        reading_status = str(record.get("reading_status", "Want to Read")).strip()
        if reading_status not in READING_STATUSES:
            reading_status = "Want to Read"
        personal_rating = record.get("personal_rating")
        try:
            personal_rating = int(personal_rating) if personal_rating is not None and personal_rating != "" else None
        except (TypeError, ValueError):
            personal_rating = None
        if personal_rating is not None and not 1 <= personal_rating <= 5:
            personal_rating = None
        try:
            book_url = validate_book_url(record.get("url"))
            created = add_book(
                title, author, year, url=book_url, category=category,
                reading_status=reading_status, personal_rating=personal_rating
            )
            if isinstance(record.get("nlb_libby"), dict):
                libby_data = dict(record["nlb_libby"])
                fetched_at = libby_data.pop("updated_at", datetime.now(timezone.utc).isoformat())
                set_libby_availability(created["id"], libby_data, fetched_at)
            imported += 1
        except (TypeError, ValueError) as error:
            errors.append(f"Row {index}: {error}")
    return jsonify({
        "status": "success", "imported": imported, "skipped_duplicates": skipped,
        "errors": errors[:20]
    })


@app.route("/books/categorize", methods=["GET", "POST"])
def categorize():
    if request.method == "GET":
        return jsonify({
            "method": "POST",
            "endpoint": "/books/categorize",
            "request_format": {"id": 1},
            "requires": "TYPESAFE_API_KEY in .env"
        })
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or type(data.get("id")) is not int:
        return jsonify({"error": "Expected integer book ID"}), 400
    book = next(
        (item for item in get_all_books() if item["id"] == data["id"]),
        None
    )
    if book is None:
        return jsonify({"error": "Book not found"}), 404
    try:
        result = classify_book(book["title"], book["author"], book["year"])
    except JevError as error:
        return jsonify({"error": str(error)}), 503
    updated = set_book_category(
        book["id"], result["category"], result["confidence"], "jev"
    )
    return jsonify({
        "status": "success",
        "message": "Book categorized with TypeSafe Jev",
        "book": updated,
        "classification": result
    })


# ==========================================
# START SERVER
# ==========================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=2500,
        debug=False
    )
