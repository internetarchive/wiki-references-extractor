import os
from datetime import datetime
from pathlib import Path

import requests
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


_ENV_LOADED = False


def _iter_candidate_dotenv_paths() -> list[Path]:
    """Return likely `.env` locations.

    We intentionally do not rely solely on the current working directory because
    callers may execute the CLI from different directories.
    """

    candidates: list[Path] = []

    def add(p: Path):
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp not in candidates:
            candidates.append(rp)

    # 1) Current working directory and a few parents
    cwd = Path.cwd()
    add(cwd / ".env")
    for parent in cwd.parents[:5]:
        add(parent / ".env")

    # 2) Package directory and a few parents (covers `python -m refs_extractor`)
    here = Path(__file__).resolve().parent
    add(here / ".env")
    for parent in here.parents[:5]:
        add(parent / ".env")

    return candidates


def _parse_env_file(dotenv_path: Path) -> dict[str, str]:
    """Minimal `.env` parser (supports KEY=VALUE, optional quotes, ignores comments)."""

    out: dict[str, str] = {}
    try:
        content = dotenv_path.read_text(encoding="utf-8")
    except Exception:
        return out

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # Strip simple wrapping quotes
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        out[key] = value
    return out


def _load_env_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    for dotenv_path in _iter_candidate_dotenv_paths():
        if not dotenv_path.exists():
            continue

        # Prefer python-dotenv when available (it handles escapes, export, etc.)
        loaded = False
        try:
            loaded = bool(load_dotenv(dotenv_path=dotenv_path, override=False))
        except TypeError:
            # Our stub doesn't accept keyword args; fall back to manual parse below.
            loaded = False
        except Exception:
            loaded = False

        if not loaded:
            for k, v in _parse_env_file(dotenv_path).items():
                os.environ.setdefault(k, v)

        # Stop after the first `.env` we find; env vars still override.
        break

    _ENV_LOADED = True


def get_contact_email():
    """Load contact email from environment/.env for polite API requests."""
    # Load from a local .env if present; environment vars override.
    _load_env_once()
    email = os.getenv("CONTACT_EMAIL")
    if not email or "@" not in email:
        raise EnvironmentError(
            "CONTACT_EMAIL is not set or invalid. Create a .env file with CONTACT_EMAIL=you@example.com or set the env var."
        )
    return email


def get_header():
    # Primary product token with contact email inside comment per common practice
    ua = f"WikiReferencesExtractor/1.0 ({get_contact_email()})"
    # Optional secondary product token, space-separated after primary
    # Example: YourApp/2.3 or YourApp/2.3; extra info
    # Load from env/.env if provided
    _load_env_once()
    secondary = (os.getenv("SECONDARY_USER_AGENT") or "").strip()
    if secondary:
        ua = f"{ua} {secondary}"
    return {"User-Agent": ua}

def get_current_timestamp():
    now = datetime.utcnow()
    return now.strftime('%Y-%m-%dT%H:%M:%SZ')

def get_wikipedia_article(domain, title, timestamp):
    url = f"https://{domain}/w/api.php"
    continue_token = None

    # Query for revisions, and stop once the target revision is found
    while True:
        params = {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "titles": title,
            "rvlimit": "max",
            "rvprop": "ids|timestamp",
            "rvdir": "older"
        }
        if continue_token:
            params["rvcontinue"] = continue_token
        response = None
        try:
            response = requests.get(url, params=params, headers=get_header())
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            # Preserve the most useful context without relying on `response`
            # being defined (e.g. request failures before a response is created).
            detail = None
            if response is not None:
                try:
                    detail = response.text
                except Exception:
                    detail = None
            msg = f"Wikipedia API request failed: {e}"
            if detail:
                msg = f"{msg}\nResponse body: {detail}"
            raise Exception(msg)
        pages = data.get("query", {}).get("pages", {})
        for page_id, page_info in pages.items():
            if "missing" in page_info:
                return None, None, None, None  # Article did not exist at the given time
            revisions = page_info.get("revisions", [])
            # Check each revision to find the target one
            for rev in revisions:
                try:
                    rev_timestamp = rev["timestamp"]
                    if rev_timestamp <= timestamp:
                        # Fetch the content of the identified revision
                        revision_id = rev["revid"]
                        content_params = {
                            "action": "query",
                            "format": "json",
                            "prop": "revisions",
                            "revids": revision_id,
                            "rvprop": "content"
                        }
                        content_response = None
                        try:
                            content_response = requests.get(url, params=content_params, headers=get_header())
                            content_response.raise_for_status()
                            content_data = content_response.json()
                        except Exception as e:
                            detail = None
                            if content_response is not None:
                                try:
                                    detail = content_response.text
                                except Exception:
                                    detail = None
                            msg = f"Wikipedia API content request failed: {e}"
                            if detail:
                                msg = f"{msg}\nResponse body: {detail}"
                            raise Exception(msg)
                        # Extract content
                        for page_id, page_info in content_data.get("query", {}).get("pages", {}).items():
                            content_revisions = page_info.get("revisions", [])
                            if content_revisions:
                                return page_id, revision_id, rev_timestamp, content_revisions[0]["*"]
                        return None, None, None, None
                except KeyError:  # Caused by deleted revision
                    continue
        continue_token = data.get("continue", {}).get("rvcontinue")
        if not continue_token:
            break
    # Return None if no suitable revision was found
    return None, None, None, None

if __name__ == "__main__":
    print(get_wikipedia_article("en.wikipedia.org", "Easter_Island", "2003-01-01T00:00:00Z"))
