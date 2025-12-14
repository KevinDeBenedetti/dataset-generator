#!/usr/bin/env python3
import requests
import json
import os
import time
from datetime import datetime
import logging

# --- Configuration ---
API_BASE_URL = "https://api.coinpaprika.com/v1"
ENDPOINT_COINS = "/coins"
ENDPOINT_COIN_BY_ID = "/coins/{}"  # coin_id

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "../../data/crypto")
os.makedirs(OUTPUT_DIR, exist_ok=True)

log_dir = os.path.join(os.path.dirname(__file__), "../../logs")
os.makedirs(log_dir, exist_ok=True)

log_file = os.path.join(log_dir, "crypto_fetch.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
)


def fetch_all_coins() -> list | None:
    url = API_BASE_URL + ENDPOINT_COINS
    logging.info(f"Fetching list of all coins from {url}")
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logging.error(f"Error fetching coins list: {e}")
        return None


def fetch_coin_by_id(coin_id: str) -> dict | None:
    url = API_BASE_URL + ENDPOINT_COIN_BY_ID.format(coin_id)
    logging.info(f"Fetching data for coin {coin_id} from {url}")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logging.error(f"Error fetching coin {coin_id}: {e}")
        return None


def save_json(data, filename: str):
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logging.info(f"Saved data to {filepath}")
    return filepath


def main(limit: int = None):
    coins = fetch_all_coins()
    if not coins:
        logging.error("No coins fetched; exiting.")
        return

    if limit is not None:
        coins = coins[:limit]

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    # 1) Save full list of coins
    save_json(coins, f"all_coins_{timestamp}.json")

    # 2) For each coin, fetch full info
    detailed = {}
    count = 0
    total = len(coins)
    for coin in coins:
        coin_id = coin.get("id")
        if not coin_id:
            continue
        info = fetch_coin_by_id(coin_id)
        if info:
            detailed[coin_id] = info
        count += 1
        # Log / inform
        if count % 100 == 0:
            logging.info(f"Fetched details for {count}/{total} coins")
        # Pause pour éviter d'exploser le rate limit (ajuster selon besoin)
        time.sleep(0.2)

    # 3) Sauvegarder les détails complets
    save_json(detailed, f"all_coins_details_{timestamp}.json")


if __name__ == "__main__":
    main(limit=10)
