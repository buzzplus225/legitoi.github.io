def scrape_legit_ng() -> List[dict]:
    """Parse la page d'accueil de Legit.ng avec des XPaths robustes"""
    articles = []
    tree = fetch_page(SOURCE_URL)
    if tree is None:
        return articles

    # XPath principal : tous les articles, quel que soit leur type
    nodes = tree.xpath('//article[starts-with(@class, "c-article-card") or starts-with(@class, "article-card") or starts-with(@class, "c-article-card-main")]')
    if not nodes:
        # Fallback : si aucun article trouvé, on cherche des divs avec classe article
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

            # Anti-doublon
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
                # Nettoyer les images inutiles
                if "base64" in image or "pixel" in image or image.endswith('.gif'):
                    image = ""

            # ---- DESCRIPTION ----
            desc_raw = node.xpath('.//p[contains(@class, "description") or contains(@class, "c-article-card-main__description") or contains(@class, "article-card-breaking__description")]/text()')
            if not desc_raw:
                desc_raw = node.xpath('.//p[contains(@class, "excerpt") or contains(@class, "lead")]/text()')
            if not desc_raw:
                # Fallback : premier paragraphe après le titre
                desc_raw = node.xpath('.//p/text()')
            description = " ".join([d.strip() for d in desc_raw if d.strip()]).strip()
            if not description:
                description = title  # repli

            # ---- DATE ----
            date_raw = node.xpath('.//time[contains(@class, "article-card-info__time")]/@datetime | .//time[contains(@class, "article-card-info__time")]/text()')
            if not date_raw:
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

            logger.info(f"✨ Article : {title[:40]}...")
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        except Exception as e:
            logger.debug(f"Erreur sur un article : {e}")
            continue

    return articles
