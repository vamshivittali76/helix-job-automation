"""
Gmail OAuth2 authentication.

Handles the OAuth2 flow for Gmail API access. Stores refresh token
locally so re-auth is only needed once.
"""

from pathlib import Path
from typing import Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_PATH = Path(__file__).parent.parent.parent / "config" / "gmail_token.json"


def get_gmail_service(credentials_path: str | Path):
    """
    Authenticate with Gmail API and return a service object.

    First run opens a browser for OAuth consent. Subsequent runs
    use the cached refresh token.
    """
    creds = _load_or_refresh_token()

    if not creds or not creds.valid:
        creds_path = Path(credentials_path)
        if not creds_path.exists():
            raise FileNotFoundError(
                f"Gmail credentials file not found: {creds_path}\n"
                "Download it from Google Cloud Console > APIs > Credentials > OAuth 2.0 Client ID"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)
        _save_token(creds)

    return build("gmail", "v1", credentials=creds)


def _load_or_refresh_token() -> Optional[Credentials]:
    """Load cached token and refresh if expired."""
    if not TOKEN_PATH.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
        except Exception:
            return None

    return creds if (creds and creds.valid) else None


def _save_token(creds: Credentials):
    """Save credentials to disk for reuse."""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
