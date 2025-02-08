#!/usr/bin/env python3
import time
import json
import re
import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from pymongo import MongoClient, UpdateOne
import os

def get_mongo_client():
    mongo_url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    print(f"[INFO] Connexion à MongoDB via: {mongo_url}")
    return MongoClient(mongo_url)

def preprocess_reviews(data):
    print(f"[INFO] Prétraitement de {len(data)} avis récupérés...")
    now = datetime.datetime.utcnow()
    for review in data:
        if 'rating' in review and isinstance(review['rating'], str):
            rating_str = review['rating'].strip()
            try:
                if not rating_str:
                    review['rating'] = None
                else:
                    rating_str = rating_str.replace("\xa0", " ")
                    num_part = rating_str.split(" sur")[0]
                    num_part = num_part.replace(',', '.')
                    review['rating'] = float(num_part)
            except Exception as e:
                print(f"[WARNING] Erreur lors de la conversion de la note: {e}")
                review['rating'] = None
        if 'comment' in review and isinstance(review['comment'], str):
            review['comment'] = re.sub(r'\s+', ' ', review['comment']).strip()
        review['scraped_at'] = now.isoformat() + "Z"
    print(f"[INFO] Prétraitement terminé. {len(data)} avis traités.")
    return data

def store_reviews(data):
    client = get_mongo_client()
    db = client["amazon_reviews"]
    collection = db["reviews"]
    try:
        collection.create_index([("username", 1), ("comment", 1), ("scraped_at", 1)], unique=True)
    except Exception as e:
        print(f"[WARNING] Problème lors de la création de l'index: {e}")
    operations = []
    for review in data:
        filter_query = {"username": review["username"], "comment": review["comment"]}
        update_data = {"$set": review}
        operations.append(UpdateOne(filter_query, update_data, upsert=True))
    if operations:
        result = collection.bulk_write(operations)
        print(f"[INFO] {result.upserted_count + result.modified_count} avis ajoutés ou mis à jour dans MongoDB.")
    else:
        print("[INFO] Aucune opération à effectuer.")
    client.close()

def build_page_url(base_url, page_number):
    """
    Construit l'URL pour une page d'avis en ajoutant ou modifiant les paramètres
    'reviewerType' et 'pageNumber'.
    """
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query)
    query["reviewerType"] = ["all_reviews"]
    query["pageNumber"] = [str(page_number)]
    new_query = urlencode(query, doseq=True)
    new_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    return new_url

def scrape_reviews(product_url, max_pages=3):
    print(f"[INFO] Début du scraping pour: {product_url}")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.binary_location = "/usr/bin/chromium"
    service = Service(executable_path="/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)

    all_data = []
    page = 1
    while page <= max_pages:
        page_url = build_page_url(product_url, page)
        print(f"[INFO] Accès à la page {page}: {page_url}")
        try:
            driver.get(page_url)
            time.sleep(5)
        except Exception as e:
            print(f"[ERROR] Impossible d'accéder à la page {page}: {e}")
            break
        try:
            review_elements = driver.find_elements(By.CSS_SELECTOR, ".review")
            print(f"[INFO] {len(review_elements)} avis trouvés sur la page {page}.")
        except Exception as e:
            print(f"[ERROR] Échec de la récupération des avis sur la page {page}: {e}")
            break

        if not review_elements:
            print(f"[INFO] Aucune critique trouvée sur la page {page}. Arrêt du scraping.")
            break

        for idx, element in enumerate(review_elements, start=1):
            try:
                username = element.find_element(By.CSS_SELECTOR, "span.a-profile-name").text
                rating_element = element.find_element(By.CSS_SELECTOR, ".a-icon-alt")
                rating = rating_element.get_attribute("textContent").strip()
                comment = element.find_element(By.CSS_SELECTOR, ".review-text-content span").text
                review_data = {
                    "username": username,
                    "rating": rating,
                    "comment": comment,
                    "url": page_url
                }
                all_data.append(review_data)
                print(f"[INFO] Avis {idx} extrait de la page {page}: {review_data}")
            except Exception as e:
                print(f"[WARNING] Échec de l'extraction de l'avis {idx} sur la page {page}: {e}")
        page += 1

    driver.quit()
    print(f"[INFO] Scraping terminé, {len(all_data)} avis extraits sur {page - 1} pages.")
    return all_data

def main():
    product_url = input("Entrez l'URL du produit Amazon: ").strip()
    if not product_url.startswith("https://www.amazon."):
        print("[ERROR] URL invalide. Veuillez entrer une URL Amazon valide.")
        return

    raw_data = scrape_reviews(product_url, max_pages=3)
    if not raw_data:
        print("[ERROR] Aucun avis extrait.")
        return

    print("[INFO] Données brutes extraites:")
    print(json.dumps(raw_data, indent=4, ensure_ascii=False))
    cleaned_data = preprocess_reviews(raw_data)
    store_reviews(cleaned_data)

if __name__ == "__main__":
    main()
