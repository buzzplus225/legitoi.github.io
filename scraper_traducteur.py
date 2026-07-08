#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper RSS automatique pour Legit.ng avec traduction en français
Version intégrale, optimisée pour un déploiement stable sur GitHub Actions.
"""

import os
import sys
import time
import random
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import re

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# SECTION 1: Importation des bibliothèques avec gestions des fallbacks
# ==============================================================================

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False
    logger.warning("cloudscraper non disponible, fallback vers requests")

import requests
from lxml import html
from feedgen.feed import FeedGenerator
from dateutil import parser

# Tiers 1 : Traducteur léger basé sur l'API (Recommandé pour GitHub Actions)
try:
    from deep_translator import GoogleTranslator as BackupTranslator
    HAS_DEEP_TRANSLATE = True
except ImportError:
    HAS_DEEP_TRANSLATE = False
    logger.warning("deep-translator non disponible, vérification de Transformers...")

# Tiers 2 : Traducteur local lourd (Alternative en cas de besoin)
try:
    from transformers import MarianMTModel, MarianTokenizer
    import torch
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    logger.warning("transformers non disponible")

# ==============================================================================
# SECTION 2: Configuration globale
# ==============================================================================

SOURCE_URL = "https://www.legit.ng/"
FEED_URL = "https://buzzplus225.github.io/legitoi.github.io/feed.xml"
FEED_TITLE = "Legit.ng - Actualités en Français"

MAX_ARTICLES = 25
MAX_RSS_ITEMS = 20
MIN_DELAY = 1
MAX_DELAY = 3
REQUEST_TIMEOUT = 30
MAX_TEXT_LENGTH = 400
MAX_RETRIES = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

# ==============================================================================
# SECTION 3: Moteur de traduction hybride intelligent
# ==============================================================================

class HybrideTranslator:
    def __init__(self):
        self.mode = "none"
        self.model = None
        self.tokenizer = None
        
        # Sélection automatique du meilleur moteur disponible
        if HAS_DEEP_TRANSLATE:
            logger.info("📚 Moteur sélectionné : deep-translator (Léger et Instantané)")
            self.mode = "deep_translator"
            self.engine = BackupTranslator(source='en', target='fr')
        elif HAS_TRANSFORMERS:
            try:
                model_name = "Helsinki-NLP/opus-mt-en-fr"
                logger.info(f"📚 Moteur sélectionné : Modèle local Transformers ({model_name})")
                self.tokenizer = MarianTokenizer.from_pretrained(model_name)
                self.model = MarianMTModel.from_pretrained(model_name)
                self.mode = "transformers"
            except Exception as e:
                logger.error(f"Impossible de charger Transformers: {e}")
                self.mode = "none"
        else:
            logger.warning("⚠️ Aucun moteur de traduction trouvé. Le flux restera en anglais.")

    def translate(self, text: str) -> str:
        if not text or not text.strip():
            return text

        # Nettoyage rudimentaire des espaces
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH] + "..."

        try:
            if self.mode == "deep_translator":
                return self.engine.translate(text)
            
            elif self.mode == "transformers" and self.model and self.tokenizer:
                inputs = self.tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
                with torch.no_grad():
                    translated = self.model.generate(**inputs)
                return self.tokenizer.decode(translated[0], skip_special_tokens=True)
                
        except Exception as e:
            logger.error(f"Erreur d'exécution de la traduction: {e}")
            
        return text

# ==============================================================================
# SECTION 4: Scraping et Normalisation des données
# ==============================================================================

def clean_date(date_str: str) -> datetime:
    """Analyse les formats de temps relatifs de Legit.ng ou absolus en format UTC"""
    now = datetime.now(timezone.utc)
    if not date_str:
        return now
    
    date_str_clean = date_str.lower().strip()
    
    try:
        if "minute" in date_str_clean:
            minutes = int(re.search(r'\d+', date_str_clean).group())
            return now - timedelta(minutes=minutes)
        elif "hour" in date_str_clean:
            hours = int(re.search(r'\d+', date_str_clean).group())
            return now - timedelta(hours=hours)
        elif "day" in date_str_clean:
            days = int(re.search(r'\d+', date_str_clean).group())
            return now - timedelta(days=days)
        elif "yesterday" in date_str_clean:
            return now - timedelta(days=1)
        
        return parser.parse(date_str, fuzzy=True).replace(tzinfo=timezone.utc)
    except Exception:
        return now

def fetch_page(url: str) -> Optional[html.HtmlElement]:
    """Tente de récupérer le DOM HTML d'une adresse spécifiée"""
    html_content = None
    
    if HAS_CLOUDSCRAPER:
        try:
            scraper = cloudscraper.create_scraper(browser='chrome')
            response = scraper.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                html_content = response.text
        except Exception as e:
            logger.warning(f"Échec cloudscraper: {e}")

    if html_content is None:
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                html_content = response.text
        except Exception as e:
            logger.error(f"Échec critique de la requête HTTP: {e}")

    if html_content:
        try:
            return html.fromstring(html_content)
        except Exception as e:
            logger.error(f"Erreur lors de la construction de l'arbre LXML: {e}")
            
    return None

def scrape_legit_ng() -> List[dict]:
    """Parse la page d'accueil de Legit.ng et extrait les articles"""
    articles = []
    tree = fetch_page(SOURCE_URL)
    
    if tree is None:
        return articles

    # Ciblage précis des blocs éditoriaux (Genesis Media Group layout)
    nodes = tree.xpath('//article[contains(@class, "c-article")] | //div[contains(@class, "c-article")] | //article')
    if not nodes:
        nodes = tree.xpath('//a[contains(@class, "news")]/ancestor::div[1] | //h2/ancestor::article')

    logger.info(f"📌 Nombre d'éléments HTML d'articles détectés : {len(nodes)}")

    for node in nodes:
        if len(articles) >= MAX_ARTICLES:
            break
        try:
            # 1. Extraction du Titre
            title_raw = node.xpath('.//a[contains(@class, "headline")]//text() | .//h3/a/text() | .//h2//text() | .//a/span/text()')
            title = " ".join([t.strip() for t in title_raw if t.strip()]).strip()
            
            # 2. Extraction de l'URL originale
            url_raw = node.xpath('.//a[contains(@class, "headline")]/@href | .//h3/a/@href | .//h2/a/@href | .//a/@href')
            url = url_raw[0].strip() if url_raw else None

            if not title or not url or len(title) < 10:
                continue

            # Traitement des chemins relatifs locaux
            if url.startswith('/'):
                url = 'https://www.legit.ng' + url
            elif not url.startswith('http'):
                continue

            # Anti-doublons préventif
            if any(a['url'] == url for a in articles):
                continue

            # 3. Extraction de l'image (Contre-mesure Lazy-Loading & srcset)
            image = ""
            img_src = node.xpath('.//img/@data-src | .//img/@data-original | .//img/@srcset | .//img/@src')
            if img_src:
                image = img_src[0].split(' ')[0].strip()
                if image.startswith('/'):
                    image = 'https://www.legit.ng' + image
                # Écarter les pixels transparents de tracking ou les GIF d'attente vides
                if "base64" in image or "pixel" in image or image.endswith('.gif'):
                    image = ""

            # 4. Extraction de la description (Résumé / Lead de l'article)
            desc_raw = node.xpath('.//p[contains(@class, "excerpt")]/text() | '
                                  './/div[contains(@class, "excerpt")]//text() | '
                                  './/p[contains(@class, "lead")]/text() | '
                                  './/span[contains(@class, "description")]/text() | .//p/text()')
            description = " ".join([d.strip() for d in desc_raw if d.strip()]).strip()

            # Stratégie de repli : Si le texte est vide, on duplique le titre pour éviter un champ vide
            if not description or len(description) < 6:
                description = title

            # 5. Extraction de l'horodatage
            date_raw = node.xpath('.//time/@datetime | .//time/text() | .//span[contains(@class, "date")]/text()')
            date_str = date_raw[0].strip() if date_raw else ""
            date_obj = clean_date(date_str)

            articles.append({
                'title': title,
                'url': url,
                'image': image,
                'description': description,
                'date': date_obj
            })
            
            logger.info(f"✨ Article capturé avec succès : {title[:40]}...")
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        except Exception as e:
            logger.debug(f"Alerte : Échec d'analyse sur un nœud HTML spécifique : {e}")
            continue

    return articles

# ==============================================================================
# SECTION 5: Compilation du Flux RSS final
# ==============================================================================

def generate_rss_feed(articles: List[dict], translator: HybrideTranslator) -> str:
    """Génère la structure XML au format RSS 2.0"""
    fg = FeedGenerator()
    fg.id(FEED_URL)
    fg.title(FEED_TITLE)
    fg.link(href=FEED_URL, rel='self')
    fg.link(href=SOURCE_URL, rel='alternate')
    fg.description("Flux d'actualités Legit.ng traduit automatiquement en Français")
    fg.language('fr')
    fg.copyright(f"© {datetime.now().year} Legit.ng - Traduction Automatique")
    fg.lastBuildDate(datetime.now(timezone.utc))
    
    for article in articles[:MAX_RSS_ITEMS]:
        try:
            entry = fg.add_entry()
            
            # Traduction à la volée des chaînes textuelles
            title_fr = translator.translate(article['title'])
            desc_fr = translator.translate(article['description'])
            
            entry.title(title_fr)
            entry.link(href=article['url'])
            entry.id(article['url'])
            entry.published(article['date'])
            
            # Structuration du contenu HTML embarqué dans le flux RSS
            content = "<div>"
            if article['image']:
                content += f'<img src="{article["image"]}" alt="{title_fr}" style="max-width:100%; height:auto; border-radius:6px; margin-bottom:12px;" /><br/>'
            content += f'<p><strong>{title_fr}</strong></p>'
            content += f'<p>{desc_fr}</p>'
            content += f'<p><a href="{article["url"]}" target="_blank" style="color:#1a73e8; text-decoration:none; font-weight:bold;">Lire l\'article original sur Legit.ng ↗</a></p>'
            content += '</div>'
            
            entry.content(content, type='html')
            entry.description(desc_fr)
            
        except Exception as e:
            logger.error(f"Impossible d'ajouter l'item au flux RSS: {e}")
            continue
            
    rss_str = fg.rss_str(pretty=True)
    return rss_str.decode('utf-8') if isinstance(rss_str, bytes) else rss_str

# ==============================================================================
# SECTION 6: Point d'entrée de l'application
# ==============================================================================

def main():
    logger.info("=== DÉMARRAGE DU SCRAPER LEGIT.NG EN FRANÇAIS ===")
    
    # Instanciation de l'écosystème de traduction
    translator = HybrideTranslator()
    
    logger.info("Lancement de la phase de collecte...")
    articles = scrape_legit_ng()
    
    if not articles:
        logger.error("❌ Aucun article n'a pu être extrait de la cible. Arrêt de sécurité.")
        sys.exit(1)
        
    logger.info(f"✓ Étape terminée : {len(articles)} articles valides en mémoire.")
    
    logger.info("Début de la phase de traduction et compilation XML...")
    rss_content = generate_rss_feed(articles, translator)
    
    # Sauvegarde sur le disque (lu ensuite par GitHub Actions)
    output_file = "feed.xml"
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(rss_content)
        logger.info(f"🎉 Succès ! Le fichier {output_file} a été mis à jour ({len(rss_content)} octets).")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'écriture sur le disque système : {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
