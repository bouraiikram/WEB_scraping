
# === Stage 1: Builder ===
FROM python:3.10-slim-buster as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt




# === Stage 2: Runtime ===
FROM seleniarm/standalone-chromium:latest
USER root
WORKDIR /app




# Copier la bibliothèque Python (libpython3.10.so.1.0) depuis le stage builder
COPY --from=builder /usr/local/lib/libpython3.10.so.1.0 /usr/local/lib/




# Copier l'installation Python complète et les packages installés
COPY --from=builder /usr/local/lib/python3.10 /usr/local/lib/python3.10
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin




# Copier libssl et libcrypto depuis le stage builder.
# Pour Debian-slim-buster sur ARM, les bibliothèques se trouvent généralement dans /usr/lib/aarch64-linux-gnu/
COPY --from=builder /usr/lib/aarch64-linux-gnu/libssl.so.1.1 /usr/lib/
COPY --from=builder /usr/lib/aarch64-linux-gnu/libcrypto.so.1.1 /usr/lib/




# Définir les variables d'environnement pour que Python retrouve ses modules
ENV PYTHONHOME=/usr/local
ENV PYTHONPATH=/usr/local/lib/python3.10:/usr/local/lib/python3.10/lib-dynload:/usr/local/lib/python3.10/site-packages
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/lib




RUN ldconfig




# Copier votre script de scraping
COPY scraper_amazon_reviews.py .




EXPOSE 5000
CMD ["python3", "scraper_amazon_reviews.py"]


