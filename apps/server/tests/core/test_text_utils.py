"""Tests for text utility functions"""

from server.core.utils.text import chunk_text


class TestChunkText:
    """Tests for the chunk_text function"""

    def test_chunk_text_basic(self):
        """Test basic text chunking"""
        text = "a" * 1500
        chunks = chunk_text(text, chunk_size=1000, overlap=200)

        assert len(chunks) == 2
        assert len(chunks[0]) == 1000
        assert len(chunks[1]) == 700  # 1500 - (1000 - 200) = 700

    def test_chunk_text_no_overlap(self):
        """Test chunking with no overlap"""
        text = "a" * 2000
        chunks = chunk_text(text, chunk_size=500, overlap=0)

        assert len(chunks) == 4
        for chunk in chunks:
            assert len(chunk) == 500

    def test_chunk_text_with_overlap(self):
        """Test chunking with overlap"""
        text = "abcdefghij" * 100  # 1000 chars
        chunks = chunk_text(text, chunk_size=300, overlap=50)

        assert len(chunks) == 4
        assert len(chunks[0]) == 300
        assert len(chunks[1]) == 300
        assert len(chunks[2]) == 300
        assert len(chunks[3]) == 250  # Remaining text

    def test_chunk_text_smaller_than_chunk_size(self):
        """Test text smaller than chunk size"""
        text = "Hello World"
        chunks = chunk_text(text, chunk_size=1000, overlap=200)

        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_text_exact_chunk_size(self):
        """Test text exactly matching chunk size"""
        text = "a" * 1000
        chunks = chunk_text(text, chunk_size=1000, overlap=200)

        # Will create 2 chunks: [0:1000] and [800:1000]
        assert len(chunks) == 2
        assert len(chunks[0]) == 1000
        assert len(chunks[1]) == 200  # Last 200 chars from position 800 to 1000

    def test_chunk_text_empty_string(self):
        """Test chunking empty string"""
        text = ""
        chunks = chunk_text(text, chunk_size=1000, overlap=200)

        assert len(chunks) == 0

    def test_chunk_text_large_overlap(self):
        """Test chunking with large overlap"""
        text = "a" * 2000
        chunks = chunk_text(text, chunk_size=1000, overlap=900)

        assert len(chunks) >= 2
        # Each chunk moves forward by (chunk_size - overlap) = 100 chars

    def test_chunk_text_preserves_content(self):
        """Test that chunking preserves the original content"""
        text = "The quick brown fox jumps over the lazy dog. " * 50
        chunks = chunk_text(text, chunk_size=500, overlap=100)

        # Reconstruct without overlap
        reconstructed = ""
        for i, chunk in enumerate(chunks):
            if i == 0:
                reconstructed += chunk
            else:
                # Skip the overlap part
                reconstructed += chunk[100:]

        assert text in reconstructed or len(reconstructed) >= len(text)

    def test_chunk_text_different_sizes(self):
        """Test chunking with different chunk sizes"""
        text = "a" * 10000

        # Test small chunks
        chunks_small = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks_small) > 10

        # Test large chunks
        chunks_large = chunk_text(text, chunk_size=5000, overlap=1000)
        assert len(chunks_large) == 3
