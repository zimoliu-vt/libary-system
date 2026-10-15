"""Small server-side client for TypeSafe AI's Jev classifier."""

import json
import os
import ssl
import time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi


PROJECT_DIRECTORY = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIRECTORY / ".env"
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"

CATEGORY_CRITERIA = {
    "Fiction": "General literary or contemporary fiction that does not fit a more specific fiction category.",
    "Fantasy": "Fantasy, mythology, magical realism, or supernatural speculative fiction.",
    "Science Fiction": "Science fiction, dystopian fiction, space fiction, or technology-focused speculative fiction.",
    "Mystery & Thriller": "Mystery, detective, crime, suspense, horror, or thriller fiction.",
    "Romance": "Romance is the book's primary genre.",
    "History": "History, politics, current affairs, war, geography, or cultural studies.",
    "Biography & Memoir": "Biography, autobiography, memoir, diaries, or personal essays.",
    "Science & Technology": "Science, mathematics, computing, engineering, medicine, or technology nonfiction.",
    "Business & Economics": "Business, leadership, management, economics, finance, or entrepreneurship.",
    "Self-Help & Psychology": "Psychology, personal development, health, relationships, or practical self-help.",
    "Philosophy & Religion": "Philosophy, ethics, spirituality, theology, or religion.",
    "Arts & Literature": "Art, design, music, film, literary criticism, poetry, or drama.",
    "Children & Young Adult": "Books primarily written for children, middle-grade readers, or young adults.",
    "Reference & Education": "Textbooks, language learning, reference works, study guides, or educational manuals.",
    "Other": "The book does not clearly fit any of the other categories."
}
CATEGORIES = tuple(CATEGORY_CRITERIA)


class JevError(RuntimeError):
    """A safe, user-facing Jev configuration or request error."""


def _load_api_key():
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    if not ENV_FILE.exists():
        return ""
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "TYPESAFE_API_KEY":
            return value.strip().strip('"').strip("'")
    return ""


def is_configured():
    return bool(_load_api_key())


def classify_book(title, author, year):
    api_key = _load_api_key()
    if not api_key:
        raise JevError("Add your TypeSafe API key to .env before using Jev")

    payload = {
        "model": JEV_MODEL,
        "state": {"title": title, "author": author, "year": year},
        "questions": {
            "category": {
                "type": "choice",
                "instructions": (
                    "Choose the single best library category for this book from its title, "
                    "author, and publication year. Use Other only when no category is a reasonable fit."
                ),
                "criteria": CATEGORY_CRITERIA
            }
        }
    }
    request = Request(
        JEV_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    result = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20, context=ssl_context) as response:
                result = json.load(response)
            break
        except HTTPError as error:
            if error.code in {401, 403}:
                raise JevError("TypeSafe rejected the API key") from error
            if error.code == 429:
                raise JevError("TypeSafe rate limit reached; try again shortly") from error
            raise JevError(f"TypeSafe returned HTTP {error.code}") from error
        except (URLError, TimeoutError, RemoteDisconnected,
                ConnectionResetError, ssl.SSLError, json.JSONDecodeError) as error:
            if attempt == 2:
                raise JevError("TypeSafe temporarily disconnected; try again") from error
            time.sleep(0.75 * (attempt + 1))

    # Current HTTP responses use answers.category. Accept the SDK-style
    # choices.category shape too, which makes minor API revisions harmless.
    answer = (result.get("answers") or {}).get("category")
    if answer is None:
        answer = (result.get("choices") or {}).get("category")
    if not isinstance(answer, dict):
        raise JevError("TypeSafe returned an unexpected response")
    category = answer.get("choice")
    if category not in CATEGORIES:
        raise JevError("TypeSafe returned an unknown category")
    confidence = answer.get("confidence")
    return {
        "category": category,
        "confidence": confidence if isinstance(confidence, (int, float)) else None,
        "model": result.get("model", JEV_MODEL)
    }
