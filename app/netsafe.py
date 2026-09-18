"""One urlopen for every call that carries a credential.

urllib's default opener follows a redirect to ANY host and re-sends the
request's headers with it, so an Alpaca key or the X session cookie would go
wherever a 3xx pointed — a compromised CDN edge, a typo'd base URL that now
belongs to someone else. Redirects that stay on the same host are the ones an
API legitimately issues, so those are kept; a change of host raises instead.
"""
from __future__ import annotations

import urllib.parse
import urllib.request


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if (new.scheme, new.netloc) != (old.scheme, old.netloc):
            raise urllib.error.HTTPError(
                req.full_url, code, f"refused redirect off {old.netloc} to {new.netloc}",
                headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SameHostRedirects)


def urlopen(req, timeout: float | None = None):
    """Drop-in for urllib.request.urlopen; same-host redirects only."""
    return _OPENER.open(req, timeout=timeout)
