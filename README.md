# Dataset Generator

Web scraping and automatic dataset generation tool for question-answer datasets with advanced export capabilities and LLM integration.

## 🎯 Objective

Create quality datasets for training AI models by automatically scraping reliable sources and generating contextualized question-answer pairs. Export datasets to multiple formats including Langfuse for training data management.

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
- **Data Manager**: Data management and dataset storage with multiple export formats
- **Pipeline**: Orchestration of the complete dataset generation process
- **Export Module**: Advanced dataset export to various platforms (Langfuse, JSON, CSV, etc.)

## ✨ Key Features

- **Multi-source Scraping**: Support for various web sources and content types
- **AI-Powered QA Generation**: Leverage state-of-the-art LLMs for intelligent question-answer pair creation
- **Multi-language Support**: Generate datasets in French, English, Spanish, and German
- **Langfuse Integration**: Direct export to Langfuse for dataset management and training workflows
- **Multiple Export Formats**: JSON, CSV, JSONL, and platform-specific formats
- **Quality Control**: Automated validation and filtering of generated content
- **Batch Processing**: Efficient handling of large-scale data generation
- **API Interface**: RESTful API for programmatic access and integration

## 📚 Libraries Used

- **requests** >= 2.32.5 — HTTP requests for scraping
- **scrapy** >= 2.13.3 — Structured data extraction from HTML
- **fake-useragent** >= 2.2.0 — User-agent rotation to avoid scraping detection
- **openai** >= 1.102.0 — OpenAI API client for text processing
- **instructor** >= 1.10.0 — Tools to build structured LLM prompts / structured outputs
- **python-dotenv** >= 0.9.9 — Load environment variables from a .env file
- **fastapi** >= 0.116.1 — API framework used by the service
- **pydantic** >= 2.11.0 — Data validation and settings management
- **sqlalchemy** >= 2.0.23 — SQL toolkit and ORM
- **uvicorn** >= 0.27.1 — ASGI server implementation
- **langfuse** >= 2.14.1 — Integration with Langfuse platform for dataset management
- **pytest** >= 8.4.1 — Testing framework
- **difflib** — Sequence comparison tools from standard library

## 🔄 Workflow

1. **Scraping**: Retrieving raw web data from multiple sources
2. **Cleaning**: Processing and normalizing text to extract relevant content
3. **QA Generation**: Creating high-quality question-answer pairs via LLMs with configurable prompts
4. **Quality Assurance**: Automated validation and filtering of generated datasets
5. **Export**: Multi-format export including Langfuse integration for seamless training workflows
6. **Storage**: Persistent storage with metadata tracking and version control

## 📊 Export Options

- **Langfuse**: Direct integration for training data management
- **JSON/JSONL**: Standard formats for data interchange
- **CSV**: Tabular format for analysis and review
- **Custom Formats**: Extensible export system for specific requirements

## 🔧 Configuration

The tool supports extensive configuration options for:

- LLM model selection and parameters
- Export format preferences
- Quality thresholds and validation rules
- Batch processing settings
- API rate limiting and retry policies

## 🌍 Supported Languages

- **French (fr)**: French language dataset generation
- **English (en)**: English language dataset generation
- **Spanish (es)**: Spanish language dataset generation
- **German (de)**: German language dataset generation
