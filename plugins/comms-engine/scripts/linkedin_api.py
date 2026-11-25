#!/usr/bin/env python3
"""
linkedin_api.py - the brand's organisation page through LinkedIn's official APIs.

Posts go through the versioned Posts API and comments through the unversioned
v2 Social Actions API (the versioned one answers 403 to an app on the
development tier).

What changed: configuration comes from `scripts/secrets.py` (environment, then
the macOS keychain, the brand's service), never from a file, and a
refreshed access token is written back to the keychain. Standard library only.

Secrets (keychain account = the name):
  LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET      the LinkedIn developer app
  LINKEDIN_ORG_ID                                  the page (106602494); posts go out as the page
  LINKEDIN_ACCESS_TOKEN, LINKEDIN_REFRESH_TOKEN,
  LINKEDIN_TOKEN_EXPIRES_AT                        written by the login, refreshed here
  LINKEDIN_API_VERSION (optional)                  YYYYMM, default 202606

  engine linkedin_api status
  engine linkedin_api get urn:li:share:<id>
  engine linkedin_api comments urn:li:share:<id>
  engine linkedin_api post "<text>"            # sends. The PreToolUse hook refuses this outside the autopilot job.
  engine linkedin_api comment <urn> "<text>"   # sends.

Posting is public and irreversible. `autopilot.py` is the only caller that
should send, and only what `streams.md` allows.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import secrets as sec  # noqa: E402

TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
POSTS_URL = "https://api.linkedin.com/rest/posts"
SOCIAL_ACTIONS_URL = "https://api.linkedin.com/v2/socialActions"
DEFAULT_API_VERSION = "202606"
MAX_COMMENTARY_LENGTH = 3000
MAX_COMMENT_LENGTH = 1250
TOKEN_EXPIRY_MARGIN_SECONDS = 24 * 3600
NAMES = ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_ORG_ID", "LINKEDIN_ACCESS_TOKEN",
         "LINKEDIN_REFRESH_TOKEN", "LINKEDIN_TOKEN_EXPIRES_AT", "LINKEDIN_MEMBER_ID", "LINKEDIN_API_VERSION")


class LinkedInError(RuntimeError):
    """A configuration, authorization or API failure with a readable message."""


# ------------------------------------------------------------------ config


def settings(stream: str | None = None) -> dict[str, str]:
    """Every LINKEDIN_* secret that resolves, through secrets.py; blanks are unset."""
    out = {}
    for name in NAMES:
        try:
            value = sec.get_secret(name, required=False, stream=stream)
        except sec.SecretNotFound:
            value = None
        if value and value.strip():
            out[name] = value.strip()
    return out


def store(name: str, value: str, stream: str | None = None) -> None:
    """Write one secret back to the keychain (a refreshed token). Environment
    callers keep their own copy; the keychain is the durable one."""
    if sys.platform != "darwin":
        os.environ[sec.scoped_name(name, stream)] = value
        return
    cmd = ["/usr/bin/security", "add-generic-password", "-s", sec.KEYCHAIN_SERVICE,
           "-a", sec.scoped_name(name, stream), "-T", "/usr/bin/security", "-U", "-w", value]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise LinkedInError(f"keychain write for {name} failed: {proc.stderr.strip()[:200]}")


def token_state(config: dict[str, str], now: float | None = None) -> dict:
    now = time.time() if now is None else now
    token = config.get("LINKEDIN_ACCESS_TOKEN", "")
    expires_at = int(config.get("LINKEDIN_TOKEN_EXPIRES_AT") or 0)
    expired = bool(expires_at) and now >= expires_at
    needs_refresh = bool(expires_at) and now >= expires_at - TOKEN_EXPIRY_MARGIN_SECONDS
    return {
        "configured": bool(config.get("LINKEDIN_CLIENT_ID") and config.get("LINKEDIN_CLIENT_SECRET")),
        "authorized": bool(token) and not expired,
        "expires_at": expires_at or None,
        "needs_refresh": needs_refresh,
        "has_refresh_token": bool(config.get("LINKEDIN_REFRESH_TOKEN")),
        "organization": config.get("LINKEDIN_ORG_ID") or None,
    }


def author_urn(config: dict[str, str], author: str = "organization", member_id: str | None = None) -> str:
    kind = (author or "organization").strip().lower()
    if kind in ("organization", "org", "page", "company"):
        org_id = config.get("LINKEDIN_ORG_ID")
        if not org_id:
            raise LinkedInError("LINKEDIN_ORG_ID is not set; set it or post with author='member'")
        return f"urn:li:organization:{org_id}"
    if kind in ("member", "person", "me"):
        member_id = member_id or config.get("LINKEDIN_MEMBER_ID")
        if not member_id:
            raise LinkedInError("Member id unknown; the token lacks the openid scope")
        return f"urn:li:person:{member_id}"
    raise LinkedInError("author must be 'organization' or 'member'")


# ------------------------------------------------------------------ payloads (pure, tested)


def build_post_payload(*, author: str, text: str, visibility: str = "PUBLIC",
                       article_url: str | None = None, article_title: str | None = None,
                       article_description: str | None = None) -> dict:
    commentary = (text or "").strip()
    if not commentary:
        raise LinkedInError("Post text is empty")
    if len(commentary) > MAX_COMMENTARY_LENGTH:
        raise LinkedInError(f"Post text is {len(commentary)} characters; LinkedIn allows {MAX_COMMENTARY_LENGTH}")
    visibility_value = (visibility or "PUBLIC").strip().upper()
    if visibility_value not in ("PUBLIC", "CONNECTIONS", "LOGGED_IN"):
        raise LinkedInError("visibility must be PUBLIC, CONNECTIONS or LOGGED_IN")
    payload: dict = {
        "author": author,
        "commentary": commentary,
        "visibility": visibility_value,
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if article_url:
        parsed = urllib.parse.urlparse(article_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise LinkedInError("article_url must be an absolute http(s) URL")
        article: dict = {"source": article_url}
        if article_title:
            article["title"] = article_title[:400]
        if article_description:
            article["description"] = article_description[:4086]
        payload["content"] = {"article": article}
    return payload


def build_comment_payload(*, actor: str, text: str) -> dict:
    body = (text or "").strip()
    if not body:
        raise LinkedInError("Comment text is empty")
    if len(body) > MAX_COMMENT_LENGTH:
        raise LinkedInError(f"Comment is {len(body)} characters; LinkedIn allows {MAX_COMMENT_LENGTH}")
    return {"actor": actor, "message": {"text": body}}


def post_url(urn: str) -> str:
    return "https://www.linkedin.com/feed/update/" + urllib.parse.quote(urn, safe=":")


# ------------------------------------------------------------------ HTTP


def _headers(config: dict[str, str], token: str, versioned: bool = True) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0",
               "Content-Type": "application/json"}
    if versioned:
        headers["LinkedIn-Version"] = config.get("LINKEDIN_API_VERSION") or DEFAULT_API_VERSION
    return headers


def _describe_failure(status: int, body_text: str) -> str:
    try:
        body = json.loads(body_text)
    except ValueError:
        body = body_text[:400]
    if isinstance(body, dict):
        message = body.get("message") or body.get("error_description") or body.get("error")
        code = body.get("code") or body.get("serviceErrorCode")
        detail = " ".join(str(part) for part in (code, message) if part)
    else:
        detail = str(body)
    hint = ""
    if status == 401:
        hint = " (token rejected: run the login again)"
    elif status == 403:
        hint = (" (scope or product missing: organization posts need the Community Management API "
                "product and the w_organization_social scope)")
    elif status == 426:
        hint = " (LINKEDIN_API_VERSION is outside LinkedIn's supported window)"
    return f"LinkedIn HTTP {status}: {detail}{hint}"


def _request(url: str, headers: dict, body: dict | None = None, method: str = "GET",
             form: dict | None = None) -> tuple[int, dict[str, str], str]:
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
    elif body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read().decode("utf-8", "replace")


def refresh_token(config: dict[str, str]) -> dict:
    refresh = config.get("LINKEDIN_REFRESH_TOKEN")
    if not refresh:
        raise LinkedInError("No refresh token stored; run the login again")
    status, _, text = _request(TOKEN_URL, {}, method="POST", form={
        "grant_type": "refresh_token", "refresh_token": refresh,
        "client_id": config.get("LINKEDIN_CLIENT_ID", ""), "client_secret": config.get("LINKEDIN_CLIENT_SECRET", "")})
    if status != 200:
        raise LinkedInError(_describe_failure(status, text))
    return json.loads(text)


def store_token_response(payload: dict, stream: str | None = None, now: float | None = None) -> None:
    now = time.time() if now is None else now
    token = payload.get("access_token")
    if not token:
        raise LinkedInError("Token response carried no access_token")
    store("LINKEDIN_ACCESS_TOKEN", token, stream)
    expires_in = int(payload.get("expires_in") or 0)
    if expires_in:
        store("LINKEDIN_TOKEN_EXPIRES_AT", str(int(now + expires_in)), stream)
    if payload.get("refresh_token"):
        store("LINKEDIN_REFRESH_TOKEN", payload["refresh_token"], stream)


def usable_token(config: dict[str, str], stream: str | None = None) -> str:
    state = token_state(config)
    if state["needs_refresh"] and state["has_refresh_token"]:
        try:
            store_token_response(refresh_token(config), stream)
            config.update(settings(stream))
            state = token_state(config)
        except LinkedInError:
            if not state["authorized"]:
                raise
    if not state["authorized"]:
        raise LinkedInError("LinkedIn is not authorized: no live access token in the keychain. "
                            "Run the LinkedIn login once and store LINKEDIN_ACCESS_TOKEN, "
                            "LINKEDIN_REFRESH_TOKEN and LINKEDIN_TOKEN_EXPIRES_AT (secrets.py --set).")
    return config["LINKEDIN_ACCESS_TOKEN"]


def create_post(config: dict[str, str], payload: dict) -> dict:
    token = usable_token(config)
    status, headers, text = _request(POSTS_URL, _headers(config, token), body=payload, method="POST")
    if status not in (200, 201):
        raise LinkedInError(_describe_failure(status, text))
    urn = headers.get("x-restli-id") or headers.get("x-linkedin-id") or ""
    return {"urn": urn, "url": post_url(urn) if urn else None, "status": status}


def create_comment(config: dict[str, str], urn: str, payload: dict) -> dict:
    token = usable_token(config)
    url = SOCIAL_ACTIONS_URL + "/" + urllib.parse.quote(urn, safe="") + "/comments"
    status, headers, text = _request(url, _headers(config, token, versioned=False), body=payload, method="POST")
    if status not in (200, 201):
        raise LinkedInError(_describe_failure(status, text))
    return {"urn": headers.get("x-restli-id") or "", "status": status}


def list_comments(config: dict[str, str], urn: str, count: int = 50) -> list[dict]:
    token = usable_token(config)
    url = SOCIAL_ACTIONS_URL + "/" + urllib.parse.quote(urn, safe="") + f"/comments?count={int(count)}"
    status, _, text = _request(url, _headers(config, token, versioned=False))
    if status != 200:
        raise LinkedInError(_describe_failure(status, text))
    out = []
    for element in json.loads(text).get("elements", []):
        out.append({"urn": element.get("$URN") or element.get("id"), "actor": element.get("actor"),
                    "text": (element.get("message") or {}).get("text", ""),
                    "created_at": (element.get("created") or {}).get("time"), "parent": element.get("parentComment")})
    return out


def get_post(config: dict[str, str], urn: str) -> dict:
    token = usable_token(config)
    status, _, text = _request(POSTS_URL + "/" + urllib.parse.quote(urn, safe=""), _headers(config, token))
    if status != 200:
        raise LinkedInError(_describe_failure(status, text))
    return json.loads(text)


# ------------------------------------------------------------------ CLI


def main(argv: list[str]) -> int:
    if "--dry" in argv or "--dry-run" in argv:
        # This CLI has no dry mode, and the posting hook lets a --dry command through.
        print("linkedin_api.py has no dry mode; refusing rather than calling the API", file=sys.stderr)
        return 2
    if len(argv) < 2 or argv[1] not in ("status", "get", "comments", "post", "comment"):
        print(__doc__)
        return 2
    config = settings()
    cmd = argv[1]
    try:
        if cmd == "status":
            state = token_state(config)
            print(json.dumps(state, indent=2))
            return 0 if state["authorized"] else 1
        if cmd == "get":
            print(json.dumps(get_post(config, argv[2]), indent=2))
        elif cmd == "comments":
            print(json.dumps(list_comments(config, argv[2]), indent=2))
        elif cmd == "post":
            result = create_post(config, build_post_payload(author=author_urn(config), text=argv[2]))
            print(json.dumps(result))
        elif cmd == "comment":
            result = create_comment(config, argv[2], build_comment_payload(actor=author_urn(config), text=argv[3]))
            print(json.dumps(result))
    except (LinkedInError, IndexError) as exc:
        print(f"linkedin_api: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
