"""
A fake of the Composio REST API for tests, injected at the urllib opener channels.py uses.

    fake = fake_composio_http.install(self, reply={"data": {"id": "1"}, "successful": True})
    channels._execute("alpha", "x", "TWITTER_CREATION_OF_A_POST", {"text": "hi"})
    fake.executes        # [(slug, body)] of every POST /api/v3.1/tools/execute/<slug>
    fake.calls           # every request: method, path, query, headers, body, url
    fake.uploads         # [(url, headers, bytes)] of every file PUT to the presigned storage URL

The fake also installs a fake `COMPOSIO_API_KEY` (fake_composio_key) and clears the account
cache. Accounts default to `<stream>-x` and `<stream>-linkedin` for every stream in the
registry, ACTIVE, ids `ca_<alias>`. `reply` is one JSON object, a `{SLUG: object}` dict, or a
callable `(slug, body) -> object`; a reply that is an Exception is raised as the opener's error.
"""
import io
import json
import os
import sys
import urllib.error
import urllib.parse
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import channels  # noqa: E402
import fake_composio_key  # noqa: E402
import memory  # noqa: E402

KEY = fake_composio_key.KEY
STORAGE_HOST = "storage.composio.dev"


class Response:
    def __init__(self, obj, raw=None):
        self._raw = raw if raw is not None else json.dumps(obj).encode("utf-8")

    def read(self):
        return self._raw


def account(alias, toolkit, status="ACTIVE", auth_config="ac_" + "x", user_id="u_1", ident=None):
    return {"id": ident or "ca_" + str(alias), "alias": alias, "status": status, "word_id": "w_" + str(alias), "user_id": user_id,
            "toolkit": {"slug": toolkit}, "auth_config": {"id": auth_config}}


class FakeComposio:
    def __init__(self, accounts=None, reply=None, auth_configs=None, status=200, error_body=""):
        self.accounts = accounts
        self.reply = reply if reply is not None else {"data": {}, "successful": True}
        self.auth_configs = auth_configs if auth_configs is not None else []
        self.status = status
        self.error_body = error_body
        self.calls = []
        self.executes = []
        self.uploads = []

    def default_accounts(self):
        out = []
        for slug in memory.streams():
            out.append(account(f"{slug}-x", "twitter", auth_config="ac_x"))
            out.append(account(f"{slug}-linkedin", "linkedin", auth_config="ac_li"))
        return out

    def open(self, request, timeout=None):
        parsed = urllib.parse.urlparse(request.full_url)
        if request.get_method() == "PUT" and parsed.netloc == STORAGE_HOST:
            # the file itself, to the presigned URL: storage, not the Composio API, so no key travels with it
            self.uploads.append((request.full_url, {k.lower(): v for k, v in request.header_items()}, request.data))
            return Response({})
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        call = {"method": request.get_method(), "path": parsed.path, "query": urllib.parse.parse_qs(parsed.query),
                "headers": {k.lower(): v for k, v in request.header_items()}, "body": body, "url": request.full_url}
        self.calls.append(call)
        if self.status != 200:
            raise urllib.error.HTTPError(request.full_url, self.status, "err", {}, io.BytesIO(self.error_body.replace("{key}", call["headers"]["x-api-key"]).encode("utf-8")))
        if parsed.path == "/api/v3.1/connected_accounts":
            items = self.accounts if self.accounts is not None else self.default_accounts()
            return Response({"items": items, "next_cursor": None})
        if parsed.path == "/api/v3.1/auth_configs":
            return Response({"items": [{"id": i, "toolkit": {"slug": "twitter"}, "name": "n", "status": "ENABLED", "type": "custom",
                                        "no_of_connections": 1} for i in self.auth_configs], "next_cursor": None})
        if parsed.path == "/api/v3.1/files/upload/request":
            return Response({"id": "req_file_1", "key": f"projects/pr_1/requests/{body['toolkit_slug']}/{body['tool_slug']}/{body['filename']}",
                             "new_presigned_url": f"https://{STORAGE_HOST}/put/{body['filename']}?X-Amz-Signature=sig",
                             "type": "new", "metadata": {"storage_backend": "s3"}})
        if parsed.path.startswith("/api/v3.1/tools/execute/"):
            slug = parsed.path.rsplit("/", 1)[-1]
            self.executes.append((slug, body))
            reply = self.reply
            if callable(reply):
                reply = reply(slug, body)
            elif isinstance(reply, dict) and slug in reply:
                reply = reply[slug]
            if isinstance(reply, Exception):
                raise reply
            return Response(reply)
        raise AssertionError(f"unexpected request {request.get_method()} {request.full_url}")


def install(case, **kw):
    fake = FakeComposio(**kw)
    fake_composio_key.install(case)
    channels.clear_cache()
    p = mock.patch.object(channels, "_OPENER", fake)
    p.start()
    case.addCleanup(p.stop)
    case.addCleanup(channels.clear_cache)
    return fake
