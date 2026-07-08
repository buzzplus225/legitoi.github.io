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

# Configuration du logging pour le debugging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# SECTION 1: Importation des bibliothèques avec gestion des erreurs
# ==============================================================================

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False
    logger.warning("cloudscraper non disponible, fallback vers requests")

import requests
from lxml import html  # Parsing XPath
from feedgen.feed import FeedGenerator

# Imports pour la traduction avec transformers
try:
    from transformers import MarianMTModel, MarianTokenizer
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    logger.warning("transformers non disponible, traduction désactivée")

# ==============================================================================
# SECTION 2: Configuration globale
# ==============================================================================

# URLs du site source et du flux de sortie
SOURCE_URL = "https://www.legit.ng/"
FEED_URL = "https://buzzplus225.github.io/legitoi.github.io/feed.xml"
FEED_TITLE = "Legit.ng - Actualités traduites en français"

# Limite du nombre d'articles à traiter (économie de ressources)
MAX_ARTICLES = 15

# Délai entre les requêtes (politesse envers le serveur)
MIN_DELAY = 2
MAX_DELAY = 5

# Timeout pour les requêtes HTTP (en secondes)
REQUEST_TIMEOUT = 15

# Longueur maximale du texte à traduire (limite mémoire GPU/CPU)
MAX_TEXT_LENGTH = 512

# User-Agent réaliste pour le fallback
REALISTIC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ==============================================================================
# SECTION 3: Fonction de traduction avec Helsinki-NLP
# ==============================================================================

class Translator:
    """
    Classe pour gérer la traduction anglais -> français
    Utilise le modèle Helsinki-NLP/opus-mt-en-fr de Hugging Face
    """

    def __init__(self):
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self):
        """Charge le modèle de traduction depuis Hugging Face"""
        if not HAS_TRANSFORMERS:
            logger.warning("Transformers non installé, traduction désactivée")
            return

        try:
            model_name = "Helsinki-NLP/opus-mt-en-fr"
            logger.info(f"Chargement du modèle de traduction: {model_name}")

            # Chargement du tokenizer et du modèle
            self.tokenizer = MarianTokenizer.from_pretrained(model_name)
            self.model = MarianMTModel.from_pretrained(model_name)

            logger.info("Modèle de traduction chargé avec succès")

        except Exception as e:
            logger.error(f"Erreur lors du chargement du modèle: {e}")
            self.model = None
            self.tokenizer = None

    def translate(self, text: str) -> str:
        """
        Traduit un texte de l'anglais vers le français
        """
        # Retourne le texte original si le modèle n'est pas disponible
        if self.model is None or self.tokenizer is None:
            return text

        # Retourne le texte vide tel quel
        if not text or not text.strip():
            return text

        try:
            # Limitation de la longueur pour éviter les problèmes de mémoire
            if len(text) > MAX_TEXT_LENGTH:
                text = text[:MAX_TEXT_LENGTH]
                logger.warning(f"Texte tronqué à {MAX_TEXT_LENGTH} caractères")

            # Tokenisation et traduction
            inputs = self.tokenizer(
                text,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=MAX_TEXT_LENGTH
            )

            # Génération de la traduction
            translated = self.model.generate(**inputs)

            # Décodage du résultat
            result = self.tokenizer.decode(
                translated[0],
                skip_special_tokens=True
            )

            return result

        except Exception as e:
            logger.error(f"Erreur de traduction: {e}")
            return text

    def translate_batch(self, texts: List[str]) -> List[str]:
        """Traduit une liste de textes"""
        return [self.translate(text) for text in texts]


# ==============================================================================
# SECTION 4: Fonctions de scraping avec cloudscraper et fallback
# ==============================================================================

def fetch_page(url: str) -> Optional[html.HtmlElement]:
    """
    Récupère le contenu HTML d'une page avec cloudscraper (fallback: requests)
    """
    html_content = None

    if HAS_CLOUDSCRAPER:
        try:
            logger.info(f"Tentative avec cloudscraper: {url}")
            scraper = cloudscraper.create_scraper(browser='chrome')
            response = scraper.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            html_content = response.text
            logger.info("Page récupérée avec succès via cloudscraper")
        except Exception as e:
            logger.warning(f"Échec cloudscraper: {e}")

    if html_content is None:
        try:
            logger.info(f"Tentative avec requests (fallback): {url}")
            headers = {
                'User-Agent': REALISTIC_USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            html_content = response.text
            logger.info("Page récupérée avec succès via requests")
        except Exception as e:
            logger.error(f"Échec complet de la récupération: {e}")
            return None

    if html_content:
        try:
            return html.fromstring(html_content)
        except Exception as e:
            logger.error(f"Erreur lors du parsing lxml: {e}")
            return None

    return None


def scrape_legit_ng() -> List[dict]:
    """
    Scrape les articles de legit.ng en utilisant les XPath fonctionnels.
    """
    articles = []
    tree = fetch_page(SOURCE_URL)
    if tree is None:
        logger.error("Impossible de récupérer la page principale")
        return articles

    article_nodes = tree.xpath('//article[@data-post-id]')
    logger.info(f"Éléments article trouvés avec XPath : {len(article_nodes)}")

    if not article_nodes:
        logger.warning("Aucun article avec data-post-id, tentative avec //article")
        article_nodes = tree.xpath('//article')
        logger.info(f"Éléments article trouvés (fallback) : {len(article_nodes)}")

    for node in article_nodes[:MAX_ARTICLES]:
        try:
            title_elem = node.xpath('.//a[contains(@class, "headline")]/span[contains(@class, "hover-inner")]/text()')
            title = title_elem[0].strip() if title_elem else None

            url_elem = node.xpath('.//a[contains(@class, "headline")]/@href')
            url = url_elem[0] if url_elem else None

            img_elem = node.xpath('.//div[contains(@class, "thumbnail-picture")]//img/@src')
            image = img_elem[0] if img_elem else ''

            desc_elem = node.xpath('.//p[contains(@class, "description")]/text()')
            description = desc_elem[0].strip() if desc_elem else ''

            date_elem = node.xpath('.//time[contains(@class, "time")]/text()')
            date = date_elem[0].strip() if date_elem else ''

            if not title or not url:
                continue

            if url.startswith('/'):
                url = 'https://www.legit.ng' + url

            articles.append({
                'title': title,
                'url': url,
                'image': image,
                'description': description,
                'date': date
            })

            logger.info(f"Article {len(articles)} : {title[:50]}...")

            # Pause entre les articles pour être gentil avec le serveur
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        except Exception as e:
            logger.error(f"Erreur lors du parsing d'un article: {e}")
            continue

    return articles


# ==============================================================================
# SECTION 5: Génération du flux RSS avec FeedGen
# ==============================================================================

def generate_rss_feed(articles: List[dict], translator: Translator) -> str:
    """
    Génère un flux RSS à partir des articles scrapés
    """
    fg = FeedGenerator()

    fg.id(FEED_URL)
    fg.title(FEED_TITLE)
    fg.link(href=FEED_URL, rel='self')
    fg.link(href=SOURCE_URL, rel='alternate')
    fg.description("Actualités de Legit.ng traduites automatiquement en français")
    fg.language('fr')
    
    # Utilisation de datetime avec timezone UTC pour feedgen
    now = datetime.now(timezone.utc)
    fg.lastBuildDate(now)

    for article in articles:
        entry = fg.add_entry()

        if translator:
            translated_title = translator.translate(article['title'])
        else:
            translated_title = article['title']

        entry.title(translated_title)

        description = article.get('description', '')
        if translator and description:
            translated_desc = translator.translate(description)
        else:
            translated_desc = description

        content = f"""
        <p><strong>{translated_title}</strong></p>
        <p>{translated_desc}</p>
        <p><em>Source: <a href="{article['url']}">{article['url']}</a></em></p>
        """

        entry.content(content, type='html')
        entry.link(href=article['url'])
        entry.id(article['url'])
        
        # Utilisation de la date de l'article si disponible, sinon now
        try:
            if article.get('date'):
                # Essayer de parser la date
                article_date = datetime.strptime(article['date'], '%Y-%m-%d %H:%M')
                entry.published(article_date.replace(tzinfo=timezone.utc))
            else:
                entry.published(now)
        except:
            entry.published(now)

    rss_feed = fg.rss_str(pretty=True)

    if isinstance(rss_feed, bytes):
        rss_feed = rss_feed.decode('utf-8')

    return rss_feed


# ==============================================================================
# SECTION 6: Fonction principale
# ==============================================================================

def main():
    logger.info("=" * 60)
    logger.info("Démarrage du scraper Legit.ng")
    logger.info("=" * 60)

    logger.info("Initialisation du traducteur...")
    translator = Translator()

    logger.info("Récupération des articles...")
    articles = scrape_legit_ng()

    if not articles:
        logger.error("Aucun article récupéré")
        sys.exit(1)

    logger.info(f"Articles récupérés: {len(articles)}")

    logger.info("Génération du flux RSS...")
    rss_content = generate_rss_feed(articles, translator)

    output_file = "feed.xml"

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(rss_content)

        logger.info(f"Flux RSS sauvegardé: {output_file}")
        logger.info(f"Taille du fichier: {len(rss_content)} caractères")

    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde: {e}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Scraping terminé avec succès!")
    logger.info("=" * 60)

    print(f"\nRésumé:")
    print(f"- Articles scrapés: {len(articles)}")
    print(f"- Traduction: {'Activée' if translator.model else 'Désactivée'}")
    print(f"- Fichier généré: {os.path.abspath(output_file)}")


if __name__ == "__main__":
    main()
