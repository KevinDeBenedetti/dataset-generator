import logging

def setup_logging(level: int = logging.INFO):
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(filename)s:%(lineno)d',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('scraper.log')
        ]
    )