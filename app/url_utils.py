from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def add_sub5_test(url: str | None) -> str | None:
    """
    Add or replace sub5=test parameter to a URL for cloaking bypass during manual testing.

    Examples:
        https://track.example.com/click?sub1=abc&sub2=xyz
        -> https://track.example.com/click?sub1=abc&sub2=xyz&sub5=test

        https://track.example.com/click?sub1=abc&sub5=original
        -> https://track.example.com/click?sub1=abc&sub5=test

    Args:
        url: The URL to modify. Can be None.

    Returns:
        Modified URL with sub5=test parameter, or None if input was None.
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)

        # Parse existing query parameters
        params = parse_qs(parsed.query, keep_blank_values=True)

        # Add or replace sub5 parameter with 'test'
        params['sub5'] = ['test']

        # Reconstruct query string
        new_query = urlencode(params, doseq=True)

        # Rebuild URL with modified query
        modified_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))

        return modified_url
    except Exception:
        # If URL parsing fails, return original URL
        return url
