"""Embedding endpoint construction shared by runtime requests and admin probes."""


def build_embeddings_url(base_url: str) -> str:
    """Build an OpenAI-compatible embeddings endpoint from an SDK-style base URL.

    The admin UI stores SDK ``base_url`` values rather than full request URLs.
    Be forgiving for common Alibaba Model Studio inputs because operators often
    paste ``.../compatible-mode`` without the trailing ``/v1``.

    Examples:
    - ``https://api.openai.com/v1`` -> ``.../v1/embeddings``
    - ``.../compatible-mode/v1`` -> ``.../compatible-mode/v1/embeddings``
    - ``.../compatible-mode`` -> ``.../compatible-mode/v1/embeddings``
    - Alibaba workspace host only -> ``.../compatible-mode/v1/embeddings``
    - ``.../api/v3`` -> ``.../api/v3/embeddings``
    - a full ``.../embeddings`` endpoint is preserved
    """
    from urllib.parse import urlparse

    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return ""

    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    path_lower = path.lower()
    host = (parsed.hostname or "").lower()

    if path_lower.endswith("/embeddings"):
        return normalized

    # Alibaba Model Studio's OpenAI-compatible endpoint is rooted at
    # /compatible-mode/v1. Accept the frequently pasted parent path too.
    if path_lower.endswith("/compatible-mode"):
        return f"{normalized}/v1/embeddings"
    if path_lower.endswith("/compatible-mode/v1"):
        return f"{normalized}/embeddings"

    # Workspace-specific Model Studio domains are also commonly pasted as a
    # bare host. Give them the provider's OpenAI-compatible root instead of the
    # generic /v1 root used by OpenAI/vLLM-style servers.
    is_alibaba_model_studio = host.endswith(".maas.aliyuncs.com") or host in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "cn-hongkong.dashscope.aliyuncs.com",
    }
    if not path and is_alibaba_model_studio:
        return f"{normalized}/compatible-mode/v1/embeddings"

    if not path:
        return f"{normalized}/v1/embeddings"
    return f"{normalized}/embeddings"
