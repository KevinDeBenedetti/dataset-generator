def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200):
    """Divise un texte en morceaux de taille fixe avec chevauchement."""
    chunks = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks
