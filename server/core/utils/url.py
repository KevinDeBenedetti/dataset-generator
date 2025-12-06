from urllib.parse import urljoin, urlparse


def clean_base_url(url: str) -> str:
    """Clean and normalize base URL to ensure it ends with a slash"""
    if not url:
        return ""

    # Parse the URL to validate it
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")

    # Ensure the URL ends with a slash
    if not url.endswith("/"):
        url += "/"

    return url


def build_api_url(base_url: str, endpoint: str) -> str:
    """Safely build API URL by joining base URL with endpoint"""
    clean_base = clean_base_url(base_url)
    # Remove leading slash from endpoint if present to avoid double slashes
    clean_endpoint = endpoint.lstrip("/")
    return urljoin(clean_base, clean_endpoint)
