#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper RSS automatique pour Legit.ng avec traduction en français
Version optimisée pour GitHub Actions (Robuste et Économe en ressources)
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
# SECTION 1: Importation des bibliothèques avec fallbacks robustes
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

# Tiers-1 : Traducteur alternatif léger (évite d'exploser la RAM de GitHub Actions)
try:
    from deep_translator import GoogleTranslator as BackupTranslator
    HAS_DEEP_TRANSLATE = True
except ImportError:
    HAS_DEEP_TRANSLATE = False

# Tiers-2 : Modèle lourd Transformers
try:
    from transformers import MarianMTModel, MarianTokenizer
    import torch
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False

# ==============================================================================
# SECTION 2: Configuration
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
# SECTION 3: Classe de traduction hybride (Performance max)
# ==============================================================================

class HybrideTranslator:
    def __init__(self):
        self.mode = "none"
        self.model = None
        self.tokenizer = None
        
        # Choix de la meilleure méthode disponible
        if HAS_DEEP_TRANSLATE:
            logger.info("📚 Utilisation de deep-translator (Léger et Rapide)")
            self.mode = "deep_translator"
            self.engine = BackupTranslator(source='en', target='fr')
        elif HAS_TRANSFORMERS:
            try:
                model_name = "Helsinki-NLP/opus-mt-en-fr"
                logger.info(f"📚 Chargement du modèle local: {model_name}")
                self.tokenizer = MarianTokenizer.from_pretrained(model_name)
                self.model = MarianMTModel.from_pretrained(model_name)
                self.mode = "transformers"
            except Exception as e:
                logger.error(f"Impossible de charger Transformers: {e}")
                self.mode = "none"
        else:
            logger.warning("⚠️ Aucun moteur de traduction trouvé. Le texte restera en anglais.")

    def translate(self, text: str) -> str:
        if not text or not text.strip():
            return text

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
            logger.error(f"Erreur lors de la traduction: {e}")
            
        return text

# ==============================================================================
# SECTION 4: Fonctions de parsing et scraping optimisées
# ==============================================================================

def clean_date(date_str: str) -> datetime:
    """Convertit les dates relatives (ex: '2 hours ago') ou absolues en datetime UTC"""
    now = datetime.now(timezone.utc)
    if not date_str:
        return now
    
    date_str_clean = date_str.lower().strip()
    
    # Gestion des formats relatifs de Legit.ng
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
        
        # Fallback vers le parseur standard
        return parser.parse(date_str, fuzzy=True).replace(tzinfo=timezone.utc)
    except Exception:
        return now

def fetch_page(url: str) -> Optional[html.HtmlElement]:
    """Récupère le code HTML de la page"""
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
            logger.error(f"Échec global de récupération: {e}")

    if html_content:
        try:
            return html.fromstring(html_content)
        except Exception as e:
            logger.error(f"Erreur parsing lxml: {e}")
            
    return None

def scrape_legit_ng() -> List[dict]:
    """Scrape le contenu de la page d'accueil de Legit.ng"""
    articles = []
    tree = fetch_page(SOURCE_URL)
    
    if tree is None:
        return articles

    # Sélecteurs XPath mis à jour (Cible les structures d'articles Genesis Media)
    nodes = tree.xpath('//article[contains(@class, "c-article")] | //div[contains(@class, "c-article")] | //article')
    if not nodes:
        # Fallback de secours si le site a changé ses classes de composants
        nodes = tree.xpath('//a[contains(@class, "news")]/ancestor::div[1] | //h2/ancestor::article')

    logger.info(f"📌 Nœuds d'articles potentiels identifiés : {len(nodes)}")

    for node in nodes:
        if len(articles) >= MAX_ARTICLES:
            break
        try:
            # Extraction du titre
            title_raw = node.xpath('.//a[contains(@class, "headline")]//text() | .//h3/a/text() | .//h2//text() | .//a/span/text()')
            title = " ".join([t.strip() for t in title_raw if t.strip()]).strip()
            
            # Extraction de l'URL
            url_raw = node.xpath('.//a[contains(@class, "headline")]/@href | .//h3/a/@href | .//h2/a/@href | .//a/@href')
            url = url_raw[0].strip() if url_raw else None

            if not title or not url or len(title) < 10:
                continue

            # Normalisation de l'URL
            if url.startswith('/'):
                url = 'https://www.legit.ng' + url
            elif not url.startswith('http'):
                continue

            # Éviter les doublons instantanés
            if any(a['url'] == url for a in articles):
                continue

            # Extraction de l'image (Gestion critique du Lazy-Loading)
            image = ""
            img_src = node.xpath('.//img/@data-src | .//img/@data-original | .//img/@srcset | .//img/@src')
            if img_src:
                image = img_src[0].split(' ')[0].strip()  # Prend la première URL si srcset
                if image.startswith('/'):
                    image = 'https://www.legit.ng' + image

            # Extraction de la description / Excerpt
            desc_raw = node.xpath('.//p/text() | .//div[contains(@class, "excerpt")]/text()')
            description = " ".join([d.strip() for d in desc_raw if d.strip()]).strip()

            # Extraction de la date
            date_raw = node.xpath('.//time/@datetime | .//time/text() | .//span[contains(@class, "date")]/text()')
            date_str = date_raw[0].strip() if date_raw else ""
            date_obj = clean_date(date_str)

            articles.append({
                'title': title,
                'url': url,
                'image': image,
                'description': description if description else title,
                'date': date_obj
            })
            
            logger.info(f"✨ Article capturé: {title[:45]}...")
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        except Exception as e:
            logger.debug(f"Erreur lors du traitement d'un nœud d'article: {e}")
            continue

    return articles

# ==============================================================================
# SECTION 5: Génération du flux RSS
# ==============================================================================

def generate_rss_feed(articles: List[dict], translator: HybrideTranslator) -> str:
    """Génère la structure XML du flux RSS final"""
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
            
            # Traduction des champs textuels
            title_fr = translator.translate(article['title'])
            desc_fr = translator.translate(article['description'])
            
            entry.title(title_fr)
            entry.link(href=article['url'])
            entry.id(article['url'])
            entry.published(article['date'])
            
            # Construction du corps HTML de l'item RSS
            content = "<div>"
            if article['image']:
                content += f'<img src="{article["image"]}" alt="{title_fr}" style="max-width:100%; height:auto; border-radius:6px; margin-bottom:12px;" /><br/>'
            content += f'<p>{desc_fr}</p>'
            content += f'<p><a href="{article["url"]}" target="_blank" style="color:#1a73e8; text-decoration:none; font-weight:bold;">Lire l\'article original sur Legit.ng ↗</a></p>'
            content += '</div>'
            
            entry.content(content, type='html')
            
        except Exception as e:
            logger.error(f"Erreur ajout item RSS: {e}")
            continue
            
    rss_str = fg.rss_str(pretty=True)
    return rss_str.decode('utf-8') if isinstance(rss_str, bytes) else rss_str

# ==============================================================================
# SECTION 6: Point d'entrée principal
# ==============================================================================

def main():
    logger.info("=== DÉMARRAGE DU SCRAPER LEGIT.NG EN FRANÇAIS ===")
    
    translator = HybrideTranslator()
    
    logger.info("Scraping en cours...")
    articles = scrape_legit_ng()
    
    if not articles:
        logger.error("❌ Aucun article valide n'a pu être extrait. Fin du script.")
        sys.exit(1)
        
    logger.info(f"✓ {len(articles)} articles extraits avec succès.")
    
    logger.info("Génération du flux RSS enrichi...")
    rss_content = generate_rss_feed(articles, translator)
    
    # Sauvegarde locale du fichier feed.xml
    output_file = "feed.xml"
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(rss_content)
        logger.info(f"🎉 Le fichier {output_file} a été généré avec succès ({len(rss_content)} octets).")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'écriture du fichier XML: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
