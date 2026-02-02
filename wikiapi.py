import os
import requests
from datetime import datetime
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


def get_contact_email():
    """Load contact email from environment/.env for polite API requests."""
    # Load from a local .env if present; environment vars override
    load_dotenv()
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
    load_dotenv()
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
        try:
            response = requests.get(url, params=params, headers=get_header())
            data = response.json()
        except:
            raise Exception(response.text)
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
                        content_response = requests.get(url, params=content_params, headers=get_header())
                        content_data = content_response.json()
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
