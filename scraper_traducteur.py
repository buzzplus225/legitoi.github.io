# scraper_traducteur.py
# Version avec XPaths robustes et debug

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
DEBUG = True  # Mode debug pour voir les XPaths

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
        if len(text) > 5000:
            text = text[:5000]
        return translator.translate(text)
    except Exception as e:
        logger.warning(f"Erreur de traduction: {e}")
        return text

# -------------------- FONCTIONS UTILITAIRES --------------------
def fetch_page(url: str) -> Optional[html.HtmlElement]:
    """Télécharge la page et retourne un arbre lxml."""
    try:
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper()
            response = scraper.get(url, timeout=10)
        except ImportError:
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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
    
    date_str = date_str.strip()
    
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

# -------------------- EXTRACTION ROBUSTE --------------------
def extract_text(node, xpath_exprs: List[str]) -> str:
    """Extrait du texte en essayant plusieurs XPaths."""
    for xpath in xpath_exprs:
        try:
            elements = node.xpath(xpath)
            if elements:
                if isinstance(elements[0], str):
                    text = " ".join([e.strip() for e in elements if e.strip()])
                else:
                    text = " ".join([e.text_content().strip() for e in elements if e.text_content().strip()])
                if text:
                    return text
        except:
            continue
    return ""

def extract_attribute(node, xpath_exprs: List[str], attribute: str = 'href') -> str:
    """Extrait un attribut en essayant plusieurs XPaths."""
    for xpath in xpath_exprs:
        try:
            elements = node.xpath(xpath)
            if elements:
                val = elements[0].strip()
                if val:
                    return val
        except:
            continue
    return ""

# -------------------- FONCTION PRINCIPALE DE SCRAPING --------------------
def scrape_legit_ng() -> List[dict]:
    """Parse la page d'accueil de Legit.ng avec des XPaths ultra-robustes."""
    articles = []
    cache_urls = load_cache()
    new_urls = []
    
    tree = fetch_page(SOURCE_URL)
    if tree is None:
        return articles

    # === PREMIER PASSAGE : RECHERCHE D'ARTICLES ===
    # Essayer plusieurs stratégies pour trouver les articles
    nodes = []
    
    # Stratégie 1: Articles HTML5
    nodes = tree.xpath('//article')
    
    # Stratégie 2: Divs avec classes d'article
    if not nodes:
        nodes = tree.xpath('//div[contains(@class, "article") or contains(@class, "post") or contains(@class, "item")]')
    
    # Stratégie 3: Blocs avec lien principal
    if not nodes:
        nodes = tree.xpath('//div[.//a[contains(@href, "/news/") or contains(@href, "/local/") or contains(@href, "/world/")]]')
    
    # Stratégie 4: Tous les éléments contenant un titre
    if not nodes:
        nodes = tree.xpath('//*[.//h1 or .//h2 or .//h3]')
    
    # Si on a trop de nodes, filtrer
    if len(nodes) > 150:
        nodes = nodes[:150]
    
    # En mode debug, afficher un exemple de structure
    if DEBUG and nodes:
        logger.info("🔍 Structure du premier article trouvé:")
        first_node = nodes[0]
        html_preview = html.tostring(first_node, encoding='unicode', method='html')[:500]
        logger.info(html_preview)
        
        # Afficher tous les liens trouvés
        all_links = first_node.xpath('.//a/@href')
        logger.info(f"🔗 Liens trouvés dans le premier article: {all_links[:5]}")
        
        # Afficher tous les titres possibles
        all_titles = first_node.xpath('.//h1/text() | .//h2/text() | .//h3/text() | .//h4/text()')
        logger.info(f"📝 Titres trouvés: {all_titles[:5]}")

    logger.info(f"📌 Nombre d'articles détectés : {len(nodes)}")

    for node in nodes:
        if len(articles) >= MAX_ARTICLES:
            break
        try:
            # === TITRE - Stratégies multiples ===
            title = ""
            
            # Essayer différents sélecteurs de titre
            title_selectors = [
                './/h1/a/text()',
                './/h2/a/text()',
                './/h3/a/text()',
                './/h4/a/text()',
                './/a[contains(@class, "headline")]//text()',
                './/a[contains(@class, "title")]//text()',
                './/a[contains(@class, "link")]//text()',
                './/a[starts-with(@class, "title")]//text()',
                './/div[contains(@class, "title")]/a/text()',
                './/div[contains(@class, "heading")]/a/text()',
                './/header//a/text()',
                './/a/@title',
                './/h1/text()',
                './/h2/text()',
                './/h3/text()',
                './/span[contains(@class, "title")]/text()'
            ]
            
            for selector in title_selectors:
                try:
                    title_elem = node.xpath(selector)
                    if title_elem:
                        title = " ".join([t.strip() for t in title_elem if t.strip()]).strip()
                        if title:
                            break
                except:
                    continue
            
            # Si pas de titre, passer
            if not title or len(title) < 3:
                continue

            # === URL - Stratégies multiples ===
            url = ""
            
            # Essayer de trouver l'URL du lien principal
            url_selectors = [
                './/h1/a/@href',
                './/h2/a/@href',
                './/h3/a/@href',
                './/h4/a/@href',
                './/a[contains(@class, "headline")]/@href',
                './/a[contains(@class, "title")]/@href',
                './/a[contains(@class, "link")]/@href',
                './/a[starts-with(@class, "title")]/@href',
                './/div[contains(@class, "title")]/a/@href',
                './/div[contains(@class, "heading")]/a/@href',
                './/header//a/@href',
                './/a[contains(@href, "/news/")]/@href',
                './/a[contains(@href, "/local/")]/@href',
                './/a[contains(@href, "/world/")]/@href',
                './/a/@href'
            ]
            
            for selector in url_selectors:
                try:
                    url_elem = node.xpath(selector)
                    if url_elem and url_elem[0].strip():
                        url = url_elem[0].strip()
                        # Filtrer les URLs non-articles
                        if any(skip in url for skip in ['#', 'javascript:', 'mailto:', 'tel:', '/search', '/category']):
                            url = ""
                            continue
                        if url:
                            break
                except:
                    continue
            
            if not url:
                continue
                
            # Normaliser l'URL
            if url.startswith('/'):
                url = 'https://www.legit.ng' + url
            elif not url.startswith('http'):
                continue

            # Vérifier le cache
            if url in cache_urls:
                logger.debug(f"⏭️ Article déjà scrapé: {url}")
                continue

            # Anti-doublon
            if any(a['url'] == url for a in articles):
                continue

            # === IMAGE ===
            image = ""
            img_selectors = [
                './/img[contains(@class, "thumbnail")]/@src',
                './/img[contains(@class, "featured")]/@src',
                './/img[contains(@class, "picture")]/@src',
                './/img[contains(@class, "image")]/@src',
                './/picture/img/@src',
                './/img/@src',
                './/img/@data-src',
                './/img/@srcset'
            ]
            
            for selector in img_selectors:
                try:
                    img_src = node.xpath(selector)
                    if img_src:
                        src = img_src[0].split(' ')[0].strip()
                        if src and not any(skip in src for skip in ['base64', 'pixel', '.gif', 'blank']):
                            if src.startswith('/'):
                                src = 'https://www.legit.ng' + src
                            image = src
                            break
                except:
                    continue

            # === DESCRIPTION ===
            desc_selectors = [
                './/p[contains(@class, "description")]/text()',
                './/p[contains(@class, "excerpt")]/text()',
                './/p[contains(@class, "summary")]/text()',
                './/div[contains(@class, "description")]/p/text()',
                './/div[contains(@class, "excerpt")]/text()',
                './/p/text()'
            ]
            
            description = ""
            for selector in desc_selectors:
                try:
                    desc_elem = node.xpath(selector)
                    if desc_elem:
                        desc = " ".join([d.strip() for d in desc_elem if d.strip()]).strip()
                        if desc and len(desc) > 10:
                            description = desc
                            break
                except:
                    continue
            
            if not description:
                description = title

            # === DATE ===
            date_selectors = [
                './/time/@datetime',
                './/time/text()',
                './/span[contains(@class, "date")]/text()',
                './/span[contains(@class, "time")]/text()',
                './/meta[@property="article:published_time"]/@content',
                './/span[contains(@class, "published")]/text()'
            ]
            
            date_str = ""
            for selector in date_selectors:
                try:
                    date_elem = node.xpath(selector)
                    if date_elem:
                        date_str = date_elem[0].strip()
                        if date_str:
                            break
                except:
                    continue
            
            date_obj = clean_date(date_str)

            # === TRADUCTION ===
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
        if len(all_urls) > 500:
            all_urls = all_urls[-500:]
        save_cache(all_urls)

    return articles

# -------------------- GÉNÉRATION DU FEED RSS --------------------
def generate_feed(articles: List[dict], output_file: str = FEED_FILE):
    """Génère un fichier feed.xml à partir des articles."""
    if not articles:
        logger.warning("Aucun article à mettre dans le feed")
        # Créer un feed minimal pour éviter les erreurs
        fg = FeedGenerator()
        fg.title("Legit.ng - Actualités traduites en français")
        fg.description("Aucun article disponible actuellement")
        fg.link(href="https://buzzplus225.github.io/legitoi.github.io/", rel="alternate")
        fg.link(href="https://buzzplus225.github.io/legitoi.github.io/feed.xml", rel="self")
        fg.language("fr")
        fg.lastBuildDate(datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000"))
        
        rss_str = fg.rss_str(pretty=True)
        with open(output_file, 'wb') as f:
            f.write(rss_str)
        logger.info(f"✅ Feed RSS vide créé: {output_file}")
        return

    fg = FeedGenerator()
    fg.title("Legit.ng - Actualités traduites en français")
    fg.description("Flux RSS des actualités de Legit.ng automatiquement traduites en français")
    fg.link(href="https://buzzplus225.github.io/legitoi.github.io/", rel="alternate")
    fg.link(href="https://buzzplus225.github.io/legitoi.github.io/feed.xml", rel="self")
    fg.language("fr")
    fg.lastBuildDate(datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000"))
    fg.generator("Scraper Traducteur Legit.ng v2.0")

    for article in articles[:20]:
        fe = fg.add_entry()
        fe.title(article.get('title_fr', article.get('title', '')))
        fe.link(href=article['url'])
        fe.guid(article['url'], permalink=True)
        fe.description(article.get('description_fr', article.get('description', '')))
        
        content = f"<p>{article.get('description_fr', article.get('description', ''))}</p>"
        if article.get('image'):
            content = f'<img src="{article["image"]}" alt="{article.get("title", "")}" style="max-width:100%;"/><br/>{content}'
        fe.content(content, type="CDATA")
        
        if article.get('date'):
            fe.pubDate(article['date'].strftime("%a, %d %b %Y %H:%M:%S +0000"))
        else:
            fe.pubDate(datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000"))

    rss_str = fg.rss_str(pretty=True)
    with open(output_file, 'wb') as f:
        f.write(rss_str)
    
    logger.info(f"✅ Feed RSS généré: {output_file} ({len(articles)} articles)")

# -------------------- SAUVEGARDE JSON --------------------
def save_json(articles: List[dict], output_file: str = "articles.json"):
    """Sauvegarde les articles en JSON pour débogage."""
    try:
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
        generate_feed(articles)
        save_json(articles)
        print(f"✅ Fichiers générés:")
        print(f"   - {FEED_FILE}")
        print(f"   - articles.json")
    else:
        print("❌ Aucun article trouvé")
        # Créer un feed vide
        generate_feed([], "feed.xml")
        # Ne pas exit en erreur, créer un feed vide
        print("⚠️ Feed vide créé")
