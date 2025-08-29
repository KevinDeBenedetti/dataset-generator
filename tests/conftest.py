import pytest
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)

@pytest.fixture
def sample_urls_config():
    """Sample URLs configuration for testing"""
    return {
        "ministeres": {
            "interieur": {
                "url": "https://fr.wikipedia.org/wiki/Minist%C3%A8re_de_l%27Int%C3%A9rieur_(France)",
                "description": "Page Wikipedia du ministère de l'Intérieur"
            },
            "justice": {
                "url": "https://fr.wikipedia.org/wiki/Minist%C3%A8re_de_la_Justice_(France)",
                "description": "Page Wikipedia du ministère de la Justice"
            }
        },
        "institutions": {
            "assemblee": {
                "url": "https://fr.wikipedia.org/wiki/Assembl%C3%A9e_nationale_(France)",
                "description": "Page Wikipedia de l'Assemblée nationale"
            }
        }
    }

@pytest.fixture
def urls_json_file(temp_dir, sample_urls_config):
    """Create a temporary URLs JSON file"""
    urls_file = temp_dir / "test_urls.json"
    urls_file.write_text(json.dumps(sample_urls_config, indent=2), encoding="utf-8")
    return urls_file

@pytest.fixture
def test_env_vars(urls_json_file):
    """Set up test environment variables"""
    with patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-api-key",
        "URLS": str(urls_json_file),
        "TARGET_LANGUAGE": "fr"
    }):
        yield