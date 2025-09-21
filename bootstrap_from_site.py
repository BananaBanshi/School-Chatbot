import os, re, csv, time, argparse, json
from urllib.parse import urljoin, urlparse
import tldextract
import requests
from bs4 import BeautifulSoup
from readability import Document
import langdetect
import urllib.robotparser as robotparser

# Optional: OpenAI support for bilingual drafting
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

def same_domain(url, base_netloc):
    u = urlparse(url)
    base = tldextract.extract(base_netloc)
    tgt = tldextract.extract(u.netloc or base_netloc)
    return (base.registered_domain == tgt.registered_domain)

def can_fetch(robots_url, user_agent, target_url):
    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, target_url)
    except Exception:
        return True  # if robots.txt unreadable, allow crawling

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def extract_main(html, url):
    try:
        doc = Document(html)
        content_html = doc.summary(html_partial=True)
    except Exception:
        content_html = html
    soup = BeautifulSoup(content_html, 'html.parser')
    for tag in soup(['script','style','nav','footer','header','form','noscript']):
        tag.decompose()
    blocks = []
    for el in soup.find_all(['h1','h2','h3','p','li','dt','dd']):
        txt = clean_text(el.get_text(separator=' ', strip=True))
        if txt:
            blocks.append(txt)
    return "\n".join(blocks)

def guess_lang(text):
    try:
        return langdetect.detect(text)
    except Exception:
        return 'unknown'

def find_faq_pairs(blocks):
    pairs = []
    for i, line in enumerate(blocks):
        if line.endswith('?') and i+1 < len(blocks):
            q = line
            a = blocks[i+1]
            if not a.endswith('?'):
                pairs.append((q,a))
    return pairs

def refine_with_openai(kb_text, client):
    prompt = f"""You are an assistant extracting bilingual FAQ pairs.
From the context below, create up to 25 useful Q/A pairs for parents in English and Spanish.
Return CSV with header: question_en,answer_en,question_es,answer_es

CONTEXT:
{kb_text}
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role":"system","content":"You create bilingual FAQ CSV data for schools."},
            {"role":"user","content": prompt}
        ]
    )
    return resp.choices[0].message.content

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True, help='Base URL to crawl')
    ap.add_argument('--max-pages', type=int, default=15)
    ap.add_argument('--delay', type=float, default=0.7)
    ap.add_argument('--ignore-robots', action='store_true')
    ap.add_argument('--with-openai', action='store_true')
    args = ap.parse_args()

    base_url = args.url.rstrip('/')
    parsed = urlparse(base_url)
    base_netloc = parsed.netloc or urlparse('https://' + base_url).netloc
    robots_url = f"{parsed.scheme or 'https'}://{base_netloc}/robots.txt"
    ua = 'Mozilla/5.0 (compatible; SchoolBot/1.0)'

    out_dir = 'site_extract'
    os.makedirs(out_dir, exist_ok=True)

    seen, to_visit = set(), [base_url]
    pages = 0
    all_blocks, faq_candidates, source_map = [], [], []

    while to_visit and pages < args.max_pages:
        url = to_visit.pop(0)
        if url in seen:
            continue
        seen.add(url)

        if not args.ignore_robots and not can_fetch(robots_url, ua, url):
            continue

        try:
            resp = requests.get(url, headers={'User-Agent': ua}, timeout=15)
            if 'text/html' not in resp.headers.get('Content-Type',''):
                continue
            html = resp.text
        except Exception:
            continue

        pages += 1
        text = extract_main(html, url)
        lang = guess_lang(text)
        lines = [ln for ln in text.split('\n') if ln.strip()]
        all_blocks.extend(lines)
        source_map.append({'url': url, 'language': lang, 'chars': len(text)})

        faq_pairs = find_faq_pairs(lines)
        for q,a in faq_pairs:
            faq_candidates.append((q,a,url))

        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:'):
                continue
            nxt = urljoin(url, href)
            if same_domain(nxt, base_netloc) and nxt.startswith(base_url) and nxt not in seen:
                to_visit.append(nxt)

        time.sleep(args.delay)

    with open(os.path.join(out_dir, 'context_en.md'), 'w', encoding='utf-8') as f:
        f.write("\n".join(all_blocks))

    with open(os.path.join(out_dir, 'faq_candidates.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['question','answer','source_url'])
        for q,a,u in faq_candidates:
            w.writerow([q,a,u])

    if args.with_openai and OpenAI:
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key:
            client = OpenAI(api_key=api_key)
            try:
                bilingual = refine_with_openai("\n".join(all_blocks), client)
                with open(os.path.join(out_dir,'faq_en_es.csv'), 'w', encoding='utf-8') as f:
                    f.write(bilingual.strip())
            except Exception as e:
                print("OpenAI refinement failed:", e)

if __name__ == '__main__':
    main()
