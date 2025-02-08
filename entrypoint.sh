#!/bin/sh
if [ "$MODE" = "sentiment" ]; then
    echo "[INFO] Lancement de l'analyse de sentiment..."
    exec python3 sentiment_analysis.py
else
    echo "[INFO] Lancement du scraping Amazon..."
    exec python3 scraper_amazon_reviews.py
fi
