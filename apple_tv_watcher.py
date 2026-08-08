#!/usr/bin/env python3
"""
Bot de surveillance : Apple TV reconditionnée (page FR d'Apple)
----------------------------------------------------------------
Vérifie périodiquement https://www.apple.com/fr/shop/refurbished/appletv
et envoie une notification Telegram dès qu'un ou plusieurs modèles
d'Apple TV reconditionnée apparaissent en vente.

Installation :
    pip install requests beautifulsoup4

Configuration : voir les variables en haut du fichier (ou variables
d'environnement TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).

Lancement :
    python3 apple_tv_watcher.py

Le script tourne en boucle indéfiniment. Pour le laisser tourner en
permanence sur un serveur, utilise systemd, pm2, screen/tmux, ou une
tâche cron avec un flag "--once" (voir en bas du fichier).
"""

import os
import re
import sys
import time
import json
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIGURATION — remplis ces valeurs ou utilise des variables d'environnement
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "COLLE_TON_TOKEN_ICI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "COLLE_TON_CHAT_ID_ICI")

URL = "https://www.apple.com/fr/shop/refurbished/appletv"
CHECK_INTERVAL_SECONDS = 5 * 60  # toutes les 5 minutes
SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_products.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("apple_tv_watcher")


# ---------------------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------------------

def send_telegram_message(text: str) -> None:
    """Envoie un message via l'API Telegram Bot."""
    if "COLLE_TON" in TELEGRAM_BOT_TOKEN or "COLLE_TON" in TELEGRAM_CHAT_ID:
        log.warning("Token/chat_id Telegram non configurés — message non envoyé:\n%s", text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=payload, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("Échec de l'envoi Telegram: %s", e)


# ---------------------------------------------------------------------------
# SCRAPING
# ---------------------------------------------------------------------------

def fetch_products() -> list[dict]:
    """
    Récupère la liste des Apple TV reconditionnées actuellement en vente.
    Retourne une liste de dicts {id, name, price, url}.
    """
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    products = []
    seen_ids = set()

    # Les fiches produit reconditionnées pointent vers /fr/shop/product/XXXXX/a/...
    for link in soup.select('a[href*="/fr/shop/product/"]'):
        href = link.get("href", "")
        match = re.search(r"/fr/shop/product/([a-zA-Z0-9]+)/", href)
        if not match:
            continue
        product_id = match.group(1)
        if product_id in seen_ids:
            continue
        seen_ids.add(product_id)

        name = link.get_text(strip=True)
        if not name:
            # Parfois le nom est dans un attribut aria-label
            name = link.get("aria-label", "Apple TV reconditionnée")

        full_url = href if href.startswith("http") else f"https://www.apple.com{href}"

        products.append({
            "id": product_id,
            "name": name,
            "url": full_url,
        })

    return products


# ---------------------------------------------------------------------------
# PERSISTANCE (pour ne pas re-notifier deux fois le même produit)
# ---------------------------------------------------------------------------

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(seen_ids: set) -> None:
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# BOUCLE PRINCIPALE
# ---------------------------------------------------------------------------

def check_once(seen_ids: set) -> set:
    """Fait une vérification, notifie les nouveautés, retourne le set à jour."""
    try:
        products = fetch_products()
    except requests.RequestException as e:
        log.error("Erreur réseau lors du scraping: %s", e)
        return seen_ids

    if not products:
        log.info("Aucune Apple TV reconditionnée disponible actuellement.")
        return seen_ids

    current_ids = {p["id"] for p in products}
    new_ids = current_ids - seen_ids

    if new_ids:
        for p in products:
            if p["id"] in new_ids:
                message = (
                    f"🍏 <b>Apple TV reconditionnée disponible !</b>\n\n"
                    f"{p['name']}\n"
                    f"{p['url']}"
                )
                log.info("Nouveau produit détecté: %s", p["name"])
                send_telegram_message(message)
    else:
        log.info("%d Apple TV en stock, rien de nouveau.", len(products))

    return current_ids


def main():
    once = "--once" in sys.argv

    log.info("Démarrage de la surveillance de %s", URL)
    seen_ids = load_seen()

    if once:
        seen_ids = check_once(seen_ids)
        save_seen(seen_ids)
        return

    while True:
        seen_ids = check_once(seen_ids)
        save_seen(seen_ids)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
