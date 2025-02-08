from flask import Flask, render_template, request, jsonify
import json
import os
import datetime
import re
import faiss
import numpy as np
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from sentence_transformers import SentenceTransformer
from transformers import BartForConditionalGeneration, BartTokenizer

#  Désactiver les logs inutiles pour économiser de la mémoire
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # Forcer l'utilisation CPU uniquement
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"  # Réduire les logs TensorFlow

app = Flask(__name__)

JSON_FILE = "reviews.json"

# Modèle Sentence Transformer allégé
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

d = 384  # Dimension des embeddings
index = faiss.IndexFlatL2(d)  # ✅ Initialisation correcte de FAISS
reviews = []  # Stocke les avis en mémoire

# Modèle BART plus léger
bart_model_name = "sshleifer/distilbart-cnn-12-6"
bart_tokenizer = BartTokenizer.from_pretrained(bart_model_name)
bart_model = BartForConditionalGeneration.from_pretrained(
    bart_model_name, device_map="cpu", low_cpu_mem_usage=True
)

#  Initialisation unique de VADER pour éviter de le recréer à chaque appel
analyzer = SentimentIntensityAnalyzer()


#  Analyse de sentiment améliorée
def analyze_sentiment_vader(comment, rating=None):
    """
    Analyse de sentiment avec VADER + pondération basée sur la note (rating).
    """
    if not comment:
        return "Neutre"

    # Nettoyage du commentaire (suppression des caractères spéciaux et mise en minuscules)
    clean_comment = re.sub(r"[^\w\s]", "", comment).lower()

    # Calcul du score avec VADER
    sentiment_score = analyzer.polarity_scores(clean_comment)["compound"]

    # Ajustement basé sur la note (rating) si disponible
    if rating is None:
        rating = 3  # Supposition d'une note neutre si non trouvée

    if rating >= 4:
        sentiment_score += 0.2
    elif rating <= 2:
        sentiment_score -= 0.2

    # Définition du sentiment
    if sentiment_score >= 0.05:
        return "Positif"
    elif sentiment_score <= -0.05:
        return "Négatif"
    return "Neutre"


#  Extraction des notes numériques
def extract_numeric_rating(rating_text):
    """
    Extrait la note sous forme numérique depuis une chaîne du type '4,5 sur 5 étoiles'.
    """
    match = re.search(r"(\d+,\d+|\d+) sur 5 étoiles", rating_text)
    return float(match.group(1).replace(",", ".")) if match else None


#  Scraping des avis Amazon avec Selenium (mode headless)
def scrape_reviews(product_url):
    print(f"[INFO] Scraping en cours: {product_url}")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get(product_url)
        driver.implicitly_wait(10)

        if "Aucun avis client" in driver.page_source:
            print("[INFO] Aucun avis trouvé")
            return []

        review_elements = driver.find_elements(By.CSS_SELECTOR, ".review")
        data = []
        for element in review_elements:
            try:
                username = element.find_element(By.CSS_SELECTOR, "span.a-profile-name").text
                rating = element.find_element(By.CSS_SELECTOR, ".a-icon-alt").get_attribute("textContent").strip()
                comment = element.find_element(By.CSS_SELECTOR, ".review-text-content span").text
                rating_num = extract_numeric_rating(rating)

                # Analyse du sentiment avec VADER
                sentiment = analyze_sentiment_vader(comment, rating_num)

                data.append({"username": username, "rating": rating, "rating_num": rating_num, "comment": comment, "sentiment": sentiment})
            except Exception:
                continue

    finally:
        driver.quit()
    return data

# Stocker les avis dans un fichier JSON
def store_reviews_json(data):
    with open(JSON_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

# Fonction pour rechercher des avis similaires avec FAISS
def search_reviews_faiss(query, k=3):
    if index.ntotal == 0:
        return ["Aucun avis disponible."]
    query_vector = model.encode([query])[0]
    D, I = index.search(np.array([query_vector], dtype=np.float32), k)
    return [reviews[i]["comment"] for i in I[0] if i >= 0]

#  Charger les avis stockés en JSON
def get_reviews_json():
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except json.JSONDecodeError:
            return []
    return []


#  Résumé des avis avec BART
def summarize_text(text, max_length=130, min_length=30):
    inputs = bart_tokenizer(text, return_tensors="pt", max_length=1024, truncation=True)
    summary_ids = bart_model.generate(inputs["input_ids"], max_length=max_length, min_length=min_length, length_penalty=2.0, num_beams=4, early_stopping=True)
    return bart_tokenizer.decode(summary_ids[0], skip_special_tokens=True)


#  Récupérer le nombre d'éléments dans FAISS
def get_faiss_info():
    return index.ntotal






# Route de la page d'accueil
@app.route("/")
def index():
    return render_template("index.html")

#  Route pour scraper des avis Amazon
@app.route("/scrape", methods=["POST"])
def scrape():
    product_url = request.form.get("product_url")
    if not product_url.startswith("https://www.amazon."):
        return jsonify({"error": "URL invalide."}), 400

    raw_data = scrape_reviews(product_url)
    if not raw_data:
        return jsonify({"error": "Aucun avis trouvé."}), 400

    for review in raw_data:
        review["scraped_at"] = datetime.datetime.utcnow().isoformat()
        review["rating_num"] = extract_numeric_rating(review["rating"])
        review["sentiment"] = analyze_sentiment_vader(review["comment"], review["rating_num"])
        store_review_faiss(review["username"], review["comment"])

    store_reviews_json(raw_data)
    return jsonify({"message": "Scraping terminé.", "reviews": raw_data, "faiss_count": get_faiss_info()})

def store_review_faiss(username, comment):
    global index  # 🔹 S'assurer que index est bien la variable globale

    if not isinstance(index, faiss.IndexFlatL2):  # 🔥 Vérifier si FAISS est bien initialisé
        d = 384
        index = faiss.IndexFlatL2(d)  # ✅ Réinitialisation correcte de FAISS

    vector = model.encode([comment])[0]
    index.add(np.array([vector], dtype=np.float32))
    reviews.append({"username": username, "comment": comment, "vector": vector})




#  Route pour rechercher des avis similaires avec FAISS
@app.route("/search", methods=["GET"])
def search():
    query = request.args.get("query")
    if not query:
        return jsonify({"error": "Requête vide"}), 400
    return jsonify({"query": query, "results": search_reviews_faiss(query, k=5)})


#  Route pour afficher les avis stockés
@app.route("/reviews")
def show_reviews():
    return jsonify(get_reviews_json())


#  Route pour vérifier le statut de FAISS
@app.route("/faiss_status")
def faiss_status():
    return jsonify({"faiss_total": index.ntotal})


#  Route pour afficher les avis stockés en mémoire
@app.route("/stored_reviews")
def stored_reviews():
    return jsonify([rev["comment"] for rev in reviews])


#  Route pour générer un résumé des avis
@app.route("/summary", methods=["GET"])
def summarize_reviews():
    if not reviews:
        return jsonify({"error": "Aucun avis disponible"}), 400

    full_text = " ".join([rev["comment"] for rev in reviews])
    if len(full_text.split()) < 50:
        return jsonify({"error": "Pas assez de texte pour un résumé"}), 400

    return jsonify({"summary": summarize_text(full_text)})


#  Lancement de Flask
if __name__ == "__main__":
    app.run(debug=False)
