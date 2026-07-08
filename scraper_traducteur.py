# scraper_traducteur.py
# Version complète avec génération de feed.xml et traduction

import requests
from lxml import html
import logging
import time
import random
from datetime import datetime, timezone
from typing import List, Optional
import json
import os
from feedgen.feed import FeedGenerator
from deep_translator import GoogleTranslator

# -------------------- CONFIGURATION --------------------
SOURCE_URL = "https://www.legit.ng/"
MAX_ARTICLES = 20
MIN_DELAY = 0.5
MAX_DELAY = 1.5
CACHE_FILE = "articles_cache.json"
FEED_FILE = "feed.xml"

# -------------------- LOGGING --------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# -------------------- TRADUCTION --------------------
def translate_text(text: str, target_lang: str = 'fr') -> str:
    """Traduit un texte en français avec gestion d'erreur."""
    if not text:
        return ""
    try:
        translator = GoogleTranslator(source='auto', target=target_lang)
        # Limiter la longueur pour éviter les erreurs API
        if len(text) > 5000:
            text = text[:5000]
        return translator.translate(text)
    except Exception as e:
        logger.warning(f"Erreur de traduction: {e}")
        return text  # Retourner le texte original en cas d'erreur

# -------------------- FONCTIONS UTILITAIRES --------------------
def fetch_page(url: str) -> Optional[html.HtmlElement]:
    """Télécharge la page et retourne un arbre lxml."""
    try:
        # Utiliser cloudscraper si disponible, sinon requests
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper()
            response = scraper.get(url, timeout=10)
        except ImportError:
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
        response.raise_for_status()
        return html.fromstring(response.content)
    except Exception as e:
        logger.error(f"Erreur lors du fetch de {url}: {e}")
        return None

def clean_date(date_str: str) -> Optional[datetime]:
    """Nettoie une chaîne de date et retourne un objet datetime."""
    if not date_str:
        return datetime.now(timezone.utc)
    
    # Nettoyer la chaîne
    date_str = date_str.strip()
    
    # Essayer différents formats
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%B %d, %Y",
        "%d %B %Y"
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str[:19], fmt)
        except (ValueError, TypeError):
            continue
    
    # Si aucun format ne fonctionne
    logger.debug(f"Format de date non reconnu: {date_str}")
    return datetime.now(timezone.utc)

def load_cache() -> List[str]:
    """Charge les URLs déjà scrapées depuis le cache."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('urls', [])
        except Exception as e:
            logger.warning(f"Erreur de chargement du cache: {e}")
    return []

def save_cache(urls: List[str]):
    """Sauvegarde les URLs scrapées dans le cache."""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'urls': urls, 'updated': datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Erreur de sauvegarde du cache: {e}")

# -------------------- FONCTION PRINCIPALE DE SCRAPING --------------------
def scrape_legit_ng() -> List[dict]:
    """Parse la page d'accueil de Legit.ng avec des XPaths robustes."""
    articles = []
    cache_urls = load_cache()
    new_urls = []
    
    tree = fetch_page(SOURCE_URL)
    if tree is None:
        return articles

    # XPath principal : tous les articles
    nodes = tree.xpath('//article[starts-with(@class, "c-article-card") or starts-with(@class, "article-card") or starts-with(@class, "c-article-card-main")]')
    if not nodes:
        nodes = tree.xpath('//div[contains(@class, "c-article")]')

    logger.info(f"📌 Nombre d'articles détectés : {len(nodes)}")

    for node in nodes:
        if len(articles) >= MAX_ARTICLES:
            break
        try:
            # ---- TITRE ----
            title_elem = node.xpath('.//a[contains(@class, "headline")]/span[contains(@class, "hover-inner")]')
            if not title_elem:
                title_elem = node.xpath('.//a[contains(@class, "headline")]//text()')
            title = " ".join([t.strip() for t in title_elem if t.strip()]).strip()
            if not title:
                continue

            # ---- URL ----
            url_elem = node.xpath('.//a[contains(@class, "headline")]/@href')
            if not url_elem:
                url_elem = node.xpath('.//a/@href')
            url = url_elem[0].strip() if url_elem else None
            if not url:
                continue
            if url.startswith('/'):
                url = 'https://www.legit.ng' + url
            elif not url.startswith('http'):
                continue

            # Vérifier si déjà scrapé
            if url in cache_urls:
                logger.debug(f"⏭️ Article déjà scrapé: {url}")
                continue

            # Anti-doublon dans la session
            if any(a['url'] == url for a in articles):
                continue

            # ---- IMAGE ----
            image = ""
            img_src = node.xpath('.//img[contains(@class, "thumbnail-picture__img")]/@src')
            if not img_src:
                img_src = node.xpath('.//img/@data-src | .//img/@srcset')
            if img_src:
                image = img_src[0].split(' ')[0].strip()
                if image.startswith('/'):
                    image = 'https://www.legit.ng' + image
                if "base64" in image or "pixel" in image or image.endswith('.gif'):
                    image = ""

            # ---- DESCRIPTION ----
            desc_raw = node.xpath('.//p[contains(@class, "description") or contains(@class, "c-article-card-main__description") or contains(@class, "article-card-breaking__description")]/text()')
            if not desc_raw:
                desc_raw = node.xpath('.//p[contains(@class, "excerpt") or contains(@class, "lead")]/text()')
            if not desc_raw:
                desc_raw = node.xpath('.//p/text()')
            description = " ".join([d.strip() for d in desc_raw if d.strip()]).strip()
            if not description:
                description = title

            # ---- DATE ----
            date_raw = node.xpath('.//time[contains(@class, "article-card-info__time")]/@datetime | .//time[contains(@class, "article-card-info__time")]/text()')
            if not date_raw:
                date_raw = node.xpath('.//time/@datetime | .//time/text() | .//span[contains(@class, "date")]/text()')
            date_str = date_raw[0].strip() if date_raw else ""
            date_obj = clean_date(date_str)

            # ---- TRADUCTION ----
            logger.info(f"🌐 Traduction de: {title[:30]}...")
            title_fr = translate_text(title)
            description_fr = translate_text(description)

            article = {
                'title': title,
                'title_fr': title_fr,
                'url': url,
                'image': image,
                'description': description,
                'description_fr': description_fr,
                'date': date_obj,
                'date_str': date_obj.isoformat() if date_obj else ""
            }

            articles.append(article)
            new_urls.append(url)

            logger.info(f"✨ Article ajouté: {title_fr[:40]}...")
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        except Exception as e:
            logger.debug(f"Erreur sur un article : {e}")
            continue

    # Mettre à jour le cache
    if new_urls:
        all_urls = cache_urls + new_urls
        # Garder seulement les 500 dernières URLs
        if len(all_urls) > 500:
            all_urls = all_urls[-500:]
        save_cache(all_urls)

    return articles

# -------------------- GÉNÉRATION DU FEED RSS --------------------
def generate_feed(articles: List[dict], output_file: str = FEED_FILE):
    """Génère un fichier feed.xml à partir des articles."""
    if not articles:
        logger.warning("Aucun article à mettre dans le feed")
        return

    fg = FeedGenerator()
    fg.title("Legit.ng - Actualités traduites en français")
    fg.description("Flux RSS des actualités de Legit.ng automatiquement traduites en français")
    fg.link(href="https://buzzplus225.github.io/legitoi.github.io/", rel="alternate")
    fg.link(href="https://buzzplus225.github.io/legitoi.github.io/feed.xml", rel="self")
    fg.language("fr")
    fg.lastBuildDate(datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000"))
    fg.generator("Scraper Traducteur Legit.ng v2.0")

    for article in articles[:20]:  # Limiter à 20 articles dans le feed
        fe = fg.add_entry()
        fe.title(article.get('title_fr', article.get('title', '')))
        fe.link(href=article['url'])
        fe.guid(article['url'], permalink=True)
        fe.description(article.get('description_fr', article.get('description', '')))
        
        # Créer un contenu enrichi avec l'image
        content = f"<p>{article.get('description_fr', article.get('description', ''))}</p>"
        if article.get('image'):
            content = f'<img src="{article["image"]}" alt="{article.get("title", "")}" /><br/>{content}'
        fe.content(content, type="CDATA")
        
        # Date
        if article.get('date'):
            fe.pubDate(article['date'].strftime("%a, %d %b %Y %H:%M:%S +0000"))
        else:
            fe.pubDate(datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000"))

    # Générer le fichier
    rss_str = fg.rss_str(pretty=True)
    with open(output_file, 'wb') as f:
        f.write(rss_str)
    
    logger.info(f"✅ Feed RSS généré: {output_file} ({len(articles)} articles)")

# -------------------- SAUVEGARDE JSON (pour débogage) --------------------
def save_json(articles: List[dict], output_file: str = "articles.json"):
    """Sauvegarde les articles en JSON pour débogage."""
    try:
        # Convertir les dates en string pour JSON
        articles_serializable = []
        for a in articles:
            a_copy = a.copy()
            if 'date' in a_copy and a_copy['date']:
                a_copy['date'] = a_copy['date'].isoformat()
            articles_serializable.append(a_copy)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(articles_serializable, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ JSON sauvegardé: {output_file}")
    except Exception as e:
        logger.error(f"Erreur de sauvegarde JSON: {e}")

# -------------------- POINT D'ENTRÉE --------------------
if __name__ == "__main__":
    print("🚀 Début du scraping...")
    start_time = time.time()
    
    articles = scrape_legit_ng()
    
    elapsed = time.time() - start_time
    print(f"✅ Scraping terminé. {len(articles)} articles récupérés en {elapsed:.2f}s")
    
    if articles:
        # Générer le feed RSS
        generate_feed(articles)
        
        # Sauvegarder en JSON pour débogage
        save_json(articles)
        
        print(f"✅ Fichiers générés:")
        print(f"   - {FEED_FILE}")
        print(f"   - articles.json")
    else:
        print("❌ Aucun article trouvé")
        # Créer un feed vide pour éviter les erreurs
        generate_feed([], "feed.xml")
        exit(1)
