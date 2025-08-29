import pytest
import os
import json
from unittest.mock import patch, mock_open
from pathlib import Path

# Import après les patches pour éviter l'initialisation automatique
def test_config_initialization(test_env_vars):
    """Test basic config initialization"""
    from app.config import Config
    
    config = Config()
    
    assert config.openai_api_key == "test-api-key"
    assert config.target_language == "fr"
    assert config.model_cleaning == "mistral-small-3.1-24b-instruct-2503"

def test_urls_config_loading(test_env_vars, sample_urls_config):
    """Test URLs configuration loading"""
    from app.config import Config
    
    config = Config()
    
    # Test hierarchical config
    assert config.urls_config == sample_urls_config
    
    # Test flat URLs list
    expected_urls = [
        "https://fr.wikipedia.org/wiki/Minist%C3%A8re_de_l%27Int%C3%A9rieur_(France)",
        "https://fr.wikipedia.org/wiki/Minist%C3%A8re_de_la_Justice_(France)",
        "https://fr.wikipedia.org/wiki/Assembl%C3%A9e_nationale_(France)"
    ]
    assert set(config.urls) == set(expected_urls)

def test_dataset_names_generation(test_env_vars, sample_urls_config):
    """Test dataset names generation from hierarchical config"""
    from app.config import Config
    
    config = Config()
    
    def extract_dataset_names(data, path_parts=[]):
        names = []
        for key, value in data.items():
            current_path = path_parts + [key]
            if isinstance(value, dict):
                if "url" in value:
                    names.append("-".join(current_path))
                else:
                    names.extend(extract_dataset_names(value, current_path))
        return names
    
    dataset_names = extract_dataset_names(config.urls_config)
    expected_names = ["ministeres-interieur", "ministeres-justice", "institutions-assemblee"]
    
    assert set(dataset_names) == set(expected_names)

def test_missing_api_key():
    """Test error when API key is missing"""
    with patch.dict(os.environ, {}, clear=True):
        from app.config import Config
        
        with pytest.raises(EnvironmentError, match="OPENAI_API_KEY missing"):
            Config()

def test_missing_urls_file():
    """Test error when URLs file doesn't exist"""
    with patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-key",
        "URLS": "nonexistent.json"
    }):
        from app.config import Config
        
        with pytest.raises(EnvironmentError, match="URLs file not found"):
            Config()

def test_invalid_json_urls_file(temp_dir):
    """Test error when URLs file contains invalid JSON"""
    invalid_json_file = temp_dir / "invalid.json"
    invalid_json_file.write_text("{ invalid json", encoding="utf-8")
    
    with patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-key",
        "URLS": str(invalid_json_file)
    }):
        from app.config import Config
        
        with pytest.raises(EnvironmentError, match="Unable to read URLs file"):
            Config()

def test_legacy_urls_string():
    """Test legacy URLs string parsing"""
    with patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-key",
        "URLS": "https://example1.com,https://example2.com"
    }):
        from app.config import Config
        
        config = Config()
        
        assert config.urls == ["https://example1.com", "https://example2.com"]
        assert config.urls_config == {}

@pytest.mark.parametrize("urls_string,expected", [
    ("url1.com,url2.com", ["url1.com", "url2.com"]),
    ("url1.com;url2.com", ["url1.com", "url2.com"]),
    ("url1.com\nurl2.com", ["url1.com", "url2.com"]),
    ('["url1.com", "url2.com"]', ["url1.com", "url2.com"]),
    ("", []),
    ("single-url.com", ["single-url.com"])
])
def test_parse_urls_function(urls_string, expected):
    """Test the _parse_urls function with various formats"""
    from app.config import _parse_urls
    
    result = _parse_urls(urls_string)
    assert result == expected