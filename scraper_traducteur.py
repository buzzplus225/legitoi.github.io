#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper RSS automatique pour Legit.ng avec traduction en français
Ce script scrape les articles de legit.ng, les traduit en français,
et génère un flux RSS accessible publiquement.
"""

import os
import sys
import time
import random
import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple
import re

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# SECTION 1: Importation des bibliothèques
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

# Imports pour la traduction
try:
    from transformers import MarianMTModel, MarianTokenizer
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    logger.warning("transformers non disponible, traduction désactivée")

# ==============================================================================
# SECTION 2: Configuration
# ==============================================================================

SOURCE_URL = "https://www.legit.ng/"
FEED_URL = "https://buzzplus225.github.io/legitoi.github.io/feed.xml"
FEED_TITLE = "Legit.ng - Actualités traduites en français"

MAX_ARTICLES = 20
MAX_RSS_ITEMS = 15
MIN_DELAY = 2
MAX_DELAY = 5
REQUEST_TIMEOUT = 30
MAX_TEXT_LENGTH = 512
MAX_RETRIES = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

# ==============================================================================
# SECTION 3: Classe de traduction
# ==============================================================================

class Translator:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self):
        if not HAS_TRANSFORMERS:
            logger.warning("Transformers non installé, traduction désactivée")
            return

        try:
            model_name = "Helsinki-NLP/opus-mt-en-fr"
            logger.info(f"Chargement du modèle: {model_name}")
            
            self.tokenizer = MarianTokenizer.from_pretrained(model_name)
            self.model = MarianMTModel.from_pretrained(model_name)
            
            logger.info("✓ Modèle chargé avec succès")

        except Exception as e:
            logger.error(f"Erreur chargement modèle: {e}")
            self.model = None
            self.tokenizer = None

    def translate(self, text: str) -> str:
        if self.model is None or self.tokenizer is None:
            return text
        
        if not text or not text.strip():
            return text

        try:
            # Nettoyer le texte
            text = re.sub(r'\s+', ' ', text).strip()
            
            if len(text) > MAX_TEXT_LENGTH:
                text = text[:MAX_TEXT_LENGTH]
                logger.warning(f"Texte tronqué à {MAX_TEXT_LENGTH} caractères")

            inputs = self.tokenizer(
                text,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=MAX_TEXT_LENGTH
            )

            translated = self.model.generate(**inputs)
            result = self.tokenizer.decode(translated[0], skip_special_tokens=True)
            
            return result

        except Exception as e:
            logger.error(f"Erreur de traduction: {e}")
            return text

# ==============================================================================
# SECTION 4: Fonctions de scraping
# ==============================================================================

def fetch_page(url: str) -> Optional[html.HtmlElement]:
    """Récupère le contenu HTML d'une page"""
    html_content = None
    
    # Tentative avec cloudscraper
    if HAS_CLOUDSCRAPER:
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"Tentative {attempt + 1}/{MAX_RETRIES} avec cloudscraper")
                scraper = cloudscraper.create_scraper(browser='chrome')
                response = scraper.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                html_content = response.text
                logger.info("✓ Page récupérée avec cloudscraper")
                break
            except Exception as e:
                logger.warning(f"Échec cloudscraper (tentative {attempt + 1}): {e}")
                time.sleep(3 * (attempt + 1))

    # Fallback avec requests
    if html_content is None:
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"Tentative {attempt + 1}/{MAX_RETRIES} avec requests")
                headers = {
                    'User-Agent': random.choice(USER_AGENTS),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }
                response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                html_content = response.text
                logger.info("✓ Page récupérée avec requests")
                break
            except Exception as e:
                logger.warning(f"Échec requests (tentative {attempt + 1}): {e}")
                time.sleep(3 * (attempt + 1))

    if html_content:
        try:
            return html.fromstring(html_content)
        except Exception as e:
            logger.error(f"Erreur parsing lxml: {e}")
            return None

    return None

def scrape_legit_ng() -> List[dict]:
    """Scrape les articles de legit.ng"""
    articles = []
    tree = fetch_page(SOURCE_URL)
    
    if tree is None:
        logger.error("Impossible de récupérer la page principale")
        return articles

    # XPath patterns
    patterns = [
        '//article[@data-post-id]',
        '//article[contains(@class, "post")]',
        '//div[contains(@class, "article")]//article',
        '//article'
    ]
    
    article_nodes = []
    for pattern in patterns:
        nodes = tree.xpath(pattern)
        if nodes:
            logger.info(f"✓ Trouvé {len(nodes)} articles avec: {pattern}")
            article_nodes = nodes
            break
    
    if not article_nodes:
        logger.warning("Aucun article trouvé")
        return articles

    for node in article_nodes[:MAX_ARTICLES]:
        try:
            # Titre
            title_xpaths = [
                './/a[contains(@class, "headline")]/span[contains(@class, "hover-inner")]/text()',
                './/a[contains(@class, "headline")]/text()',
                './/h2/a/text()',
                './/h3/a/text()',
                './/a[contains(@class, "title")]/text()'
            ]
            
            title = None
            for xpath in title_xpaths:
                elem = node.xpath(xpath)
                if elem and elem[0].strip():
                    title = elem[0].strip()
                    break

            # URL
            url_xpaths = [
                './/a[contains(@class, "headline")]/@href',
                './/h2/a/@href',
                './/h3/a/@href',
                './/a[contains(@class, "title")]/@href'
            ]
            
            url = None
            for xpath in url_xpaths:
                elem = node.xpath(xpath)
                if elem:
                    url = elem[0]
                    break

            # Image
            img_xpaths = [
                './/div[contains(@class, "thumbnail-picture")]//img/@src',
                './/img[contains(@class, "featured")]/@src',
                './/img/@src'
            ]
            
            image = ''
            for xpath in img_xpaths:
                elem = node.xpath(xpath)
                if elem:
                    image = elem[0]
                    if not image.startswith('http'):
                        image = 'https://www.legit.ng' + image
                    break

            # Description
            desc_xpaths = [
                './/p[contains(@class, "description")]/text()',
                './/p[contains(@class, "excerpt")]/text()',
                './/div[contains(@class, "excerpt")]/p/text()'
            ]
            
            description = ''
            for xpath in desc_xpaths:
                elem = node.xpath(xpath)
                if elem and elem[0].strip():
                    description = elem[0].strip()
                    break

            # Date
            date_xpaths = [
                './/time[contains(@class, "time")]/text()',
                './/time/@datetime',
                './/span[contains(@class, "date")]/text()'
            ]
            
            date = ''
            for xpath in date_xpaths:
                elem = node.xpath(xpath)
                if elem:
                    date = elem[0].strip()
                    break

            if not title or not url:
                continue

            # Normaliser l'URL
            if url.startswith('/'):
                url = 'https://www.legit.ng' + url
            elif not url.startswith('http'):
                url = 'https://www.legit.ng/' + url

            articles.append({
                'title': title,
                'url': url,
                'image': image,
                'description': description,
                'date': date
            })

            logger.info(f"✓ Article {len(articles)}: {title[:40]}...")

            # Pause entre les articles
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        except Exception as e:
            logger.error(f"Erreur parsing article: {e}")
            continue

    return articles

# ==============================================================================
# SECTION 5: Génération du flux RSS
# ==============================================================================

def generate_rss_feed(articles: List[dict], translator: Translator) -> str:
    """Génère le flux RSS"""
    fg = FeedGenerator()
    
    fg.id(FEED_URL)
    fg.title(FEED_TITLE)
    fg.link(href=FEED_URL, rel='self')
    fg.link(href=SOURCE_URL, rel='alternate')
    fg.description("Actualités de Legit.ng traduites automatiquement en français")
    fg.language('fr')
    fg.copyright(f"© {datetime.now().year} Legit.ng - Traduit automatiquement")
    
    now = datetime.now(timezone.utc)
    fg.lastBuildDate(now)
    
    # Limiter le nombre d'articles dans le flux
    for article in articles[:MAX_RSS_ITEMS]:
        entry = fg.add_entry()
        
        # Traduire le titre
        translated_title = translator.translate(article['title']) if translator else article['title']
        entry.title(translated_title)
        
        # Traduire la description
        description = article.get('description', '')
        translated_desc = translator.translate(description) if translator and description else description
        
        # Construire le contenu
        content_parts = []
        
        if article.get('image'):
            content_parts.append(f'<img src="{article["image"]}" alt="{translated_title}" style="max-width:100%;height:auto;border-radius:8px;margin:10px 0;">')
        
        content_parts.append(f'<h2>{translated_title}</h2>')
        
        if translated_desc:
            content_parts.append(f'<p>{translated_desc}</p>')
        
        if article.get('date'):
            content_parts.append(f'<p><small>📅 Date originale: {article["date"]}</small></p>')
        
        content_parts.append(f'<p><a href="{article["url"]}" target="_blank" style="display:inline-block;background:#1a73e8;color:white;padding:8px 16px;border-radius:4px;text-decoration:none;">📰 Lire l\'article original</a></p>')
        
        entry.content(''.join(content_parts), type='html')
        entry.link(href=article['url'])
        entry.id(article['url'])
        
        # Gérer la date de publication
        try:
            if article.get('date'):
                try:
                    article_date = parser.parse(article['date'], fuzzy=True)
                    entry.published(article_date.replace(tzinfo=timezone.utc))
                except:
                    entry.published(now)
            else:
                entry.published(now)
        except:
            entry.published(now)
    
    rss_feed = fg.rss_str(pretty=True)
    
    if isinstance(rss_feed, bytes):
        rss_feed = rss_feed.decode('utf-8')
    
    return rss_feed

def validate_rss_feed(rss_content: str) -> bool:
    """Valide le flux RSS"""
    try:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(rss_content)
        channel = root.find('channel')
        
        if channel is None:
            logger.error("❌ Flux RSS invalide: pas de channel")
            return False
        
        items = channel.findall('item')
        if not items:
            logger.warning("⚠️ Flux RSS vide: aucun item")
            return False
        
        logger.info(f"✅ Flux RSS valide avec {len(items)} items")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur validation RSS: {e}")
        return False

# ==============================================================================
# SECTION 6: Fonction principale
# ==============================================================================

def main():
    logger.info("=" * 70)
    logger.info("🚀 Démarrage du scraper Legit.ng")
    logger.info("=" * 70)
    
    # Initialiser le traducteur
    logger.info("📚 Initialisation du traducteur...")
    translator = Translator()
    
    # Scraper les articles
    logger.info("🔍 Récupération des articles...")
    articles = scrape_legit_ng()
    
    if not articles:
        logger.error("❌ Aucun article récupéré")
        sys.exit(1)
    
    logger.info(f"✅ Articles récupérés: {len(articles)}")
    
    # Générer le flux RSS
    logger.info("📝 Génération du flux RSS...")
    rss_content = generate_rss_feed(articles, translator)
    
    # Valider le flux
    if not validate_rss_feed(rss_content):
        logger.error("❌ Flux RSS invalide")
        sys.exit(1)
    
    # Sauvegarder le fichier
    output_file = "feed.xml"
    
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(rss_content)
        
        logger.info(f"✅ Flux RSS sauvegardé: {output_file}")
        logger.info(f"📊 Taille: {len(rss_content)} caractères")
        
    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde: {e}")
        sys.exit(1)
    
    # Résumé
    logger.info("=" * 70)
    logger.info("✅ Scraping terminé avec succès!")
    logger.info("=" * 70)
    
    print("\n" + "=" * 50)
    print("📊 RÉSUMÉ")
    print("=" * 50)
    print(f"📰 Articles scrapés: {len(articles)}")
    print(f"📝 Articles dans le flux: {min(len(articles), MAX_RSS_ITEMS)}")
    print(f"🌐 Traduction: {'✅ Activée' if translator.model else '❌ Désactivée'}")
    print(f"📁 Fichier: {os.path.abspath(output_file)}")
    print(f"🔗 URL: {FEED_URL}")
    print("=" * 50)

if __name__ == "__main__":
    main()
