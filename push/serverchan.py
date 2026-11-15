"""Send a message through Server酱 (WeChat push). The SendKey is never logged."""
import re

import requests

TITLE_LIMIT = 32


def endpoint(sendkey):
    sendkey = (sendkey or "").strip()
    if not sendkey:
        raise ValueError("SERVERCHAN_SENDKEY is not set")
    match = re.match(r"^sctp(\d+)t", sendkey)
    if match:  # Server酱³ keys carry the user id
        return f"https://{match.group(1)}.push.ft07.com/send/{sendkey}.send"
    return f"https://sctapi.ftqq.com/{sendkey}.send"


def send(sendkey, title, body, timeout=20):
    try:
        response = requests.post(
            endpoint(sendkey),
            data={"title": title[:TITLE_LIMIT], "desp": body},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        # requests' messages include the URL, which contains the SendKey.
        raise RuntimeError(f"Server酱 request failed: {type(exc).__name__}") from None
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    code = payload.get("code", payload.get("errno"))
    if response.status_code != 200 or code not in (0, None):
        message = payload.get("message") or payload.get("errmsg") or response.text[:200]
        raise RuntimeError(f"Server酱 returned HTTP {response.status_code}, code {code}: {message}")
    return payload
