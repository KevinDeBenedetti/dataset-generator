# Dataset Generator

Web scraping and automatic dataset generation tool for question-answer datasets.

## 🎯 Objective

Create quality datasets for training AI models by automatically scraping reliable sources and generating contextualized question-answer pairs.

## ⚡ Quick Start

```bash
# Configuration
cp .env.example .env
# Edit .env with your API keys

# Launch
make start
```

## 🏗️ Architecture

This project is designed with a modular architecture that separates concerns into distinct components:

- **Scraper**: Retrieval of web content from specified URLs
- **LLM Client**: Interaction with language models to generate question-answer pairs
- **Data Manager**: Data management and dataset storage
- **Pipeline**: Orchestration of the complete dataset generation process

## 📚 Libraries Used

- **requests** >= 2.32.5 — HTTP requests for scraping
- **scrapy** >= 2.13.3 — Structured data extraction from HTML
- **fake-useragent** >= 2.2.0 — User-agent rotation to avoid scraping detection
- **openai** >= 1.102.0 — OpenAI API client for text processing
- **instructor** >= 1.10.0 — Tools to build structured LLM prompts / structured outputs
- **python-dotenv** >= 0.9.9 — Load environment variables from a .env file
- **fastapi** >= 0.116.1 — API framework used by the service
- **pytest** >= 8.4.1 — Testing framework

## 🔄 Workflow

1. **Scraping**: Retrieving raw web data
2. **Cleaning**: Processing text to extract relevant content
3. **QA Generation**: Creating question-answer pairs via LLMs
4. **Storage**: Exporting data in different formats

