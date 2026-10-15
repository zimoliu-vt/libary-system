"""Read public title availability from NLB's OverDrive/Libby catalogue."""

import json
import re
import ssl
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi


NLB_SEARCH_URL = "https://nlb.overdrive.com/search"
COLLECTION_PATTERN = re.compile(
    r"window\.OverDrive\.titleCollection\s*=\s*(\[.*?\]);", re.DOTALL
)


class LibbyError(RuntimeError):
    """A safe error raised when NLB availability cannot be checked."""


def _normalized(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def _title_matches(expected, candidate):
    expected_full, candidate_full = _normalized(expected), _normalized(candidate)
    if expected_full == candidate_full:
        return True
    # Subtitle differences are common between print and Libby editions, but
    # prefix matching would incorrectly treat Dune Messiah as Dune.
    expected_base = _normalized(re.split(r"[:–—]", str(expected), maxsplit=1)[0])
    candidate_base = _normalized(re.split(r"[:–—]", str(candidate), maxsplit=1)[0])
    return len(expected_base) >= 4 and expected_base == candidate_base


def _author_matches(expected, creators):
    expected = _normalized(expected)
    authors = [
        _normalized(creator.get("name")) for creator in creators
        if creator.get("role") == "Author"
    ]
    return any(
        author == expected or author in expected or expected in author
        for author in authors if author
    )


def fetch_nlb_availability(title, author):
    url = f"{NLB_SEARCH_URL}?{urlencode({'query': title})}"
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; PersonalLibrary/1.0)",
        "Accept": "text/html,application/xhtml+xml"
    })
    context = ssl.create_default_context(cafile=certifi.where())
    html = None
    for attempt in range(2):
        try:
            with urlopen(request, timeout=25, context=context) as response:
                html = response.read(2_500_000).decode("utf-8", "replace")
            break
        except HTTPError as error:
            raise LibbyError(f"NLB Libby returned HTTP {error.code}") from error
        except (URLError, TimeoutError, ssl.SSLError, ConnectionResetError) as error:
            if attempt:
                raise LibbyError("Could not reach NLB Libby") from error
            time.sleep(1)
    match = COLLECTION_PATTERN.search(html or "")
    if not match:
        raise LibbyError("NLB Libby returned an unexpected page")
    try:
        titles = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise LibbyError("NLB Libby returned invalid catalogue data") from error

    editions = []
    for item in titles:
        if not _title_matches(title, item.get("title")):
            continue
        if not _author_matches(author, item.get("creators", [])):
            continue
        media_type = (item.get("type") or {}).get("name", "Digital title")
        editions.append({
            "format": media_type,
            "available_copies": max(0, int(item.get("availableCopies") or 0)),
            "owned_copies": max(0, int(item.get("ownedCopies") or 0)),
            "holds": max(0, int(item.get("holdsCount") or 0)),
            "reserve_id": item.get("reserveId")
        })
    return {
        "found": bool(editions),
        "available": any(item["available_copies"] > 0 for item in editions),
        "available_copies": sum(item["available_copies"] for item in editions),
        "editions": editions,
        "search_url": url
    }
