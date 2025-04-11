from flask import Flask, request, send_file, jsonify, render_template
import os
import requests
from bs4 import BeautifulSoup
import wget
import shutil
from urllib.parse import urljoin, urlparse, urlunparse
import time
import uuid
import re
import json
import mimetypes
import hashlib
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import chardet

app = Flask(__name__)
app.logger.setLevel('INFO')  # Set the logging level

def get_file_extension(url, content_type=None):
    """Get file extension from URL or content type"""
    # Try to get extension from URL first
    ext = os.path.splitext(urlparse(url).path)[1]
    if ext:
        return ext.lower()

    # If no extension in URL, try to get from content type
    if content_type:
        ext = mimetypes.guess_extension(content_type)
        if ext:
            return ext.lower()

    # Default extensions based on content type patterns
    if content_type:
        if 'image' in content_type:
            return '.jpg'
        if 'video' in content_type:
            return '.mp4'
        if 'javascript' in content_type:
            return '.js'
        if 'css' in content_type:
            return '.css'
        if 'font' in content_type:
            return '.woff2'
    
    return '.bin'  # Default extension if nothing else works

def safe_filename(url):
    """Convert URL to a safe filename while preserving the original name"""
    try:
        # Get the original filename from URL
        parsed_url = urlparse(url)
        original_name = os.path.basename(parsed_url.path)
        
        # If no filename in URL, use the last part of the path
        if not original_name:
            original_name = parsed_url.netloc
        
        # Remove query parameters
        original_name = original_name.split('?')[0]
        
        # If still no name, generate one from the URL hash
        if not original_name:
            return hashlib.md5(url.encode()).hexdigest()[:10]
            
        # Clean the filename
        # Remove invalid characters but keep the original name structure
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', original_name)
        
        # Ensure the filename isn't too long
        if len(safe_name) > 255:
            name, ext = os.path.splitext(safe_name)
            safe_name = name[:240] + ext
            
        return safe_name
    except:
        return hashlib.md5(url.encode()).hexdigest()[:10]

def safe_download(url, save_path):
    try:
        # Ensure the URL is valid
        parsed_url = urlparse(url)
        if not parsed_url.scheme:
            url = 'https://' + url
        if not parsed_url.scheme and not parsed_url.netloc:
            return None

        # Download with timeout and proper headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, stream=True, timeout=(10, 30), headers=headers, allow_redirects=True)
        response.raise_for_status()

        # Get content type and extension
        content_type = response.headers.get('Content-Type', '').split(';')[0]
        ext = get_file_extension(url, content_type)

        # Create unique filename using hash of URL
        url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
        filename = f"{url_hash}{ext}"
        full_path = os.path.join(save_path, filename)

        # Save file with proper encoding to handle unicode characters
        with open(full_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return filename
    except Exception as e:
        print(f'Error downloading {url}: {str(e)}')
        return None

def replace_domain_in_url(url, original_domains, new_domains, base_url):
    try:
        # Handle relative URLs and decode URL-encoded characters
        full_url = urljoin(base_url, url)
        parsed = urlparse(full_url)
        
        # Skip if it's a relative URL without domain
        if not parsed.netloc:
            return url
            
        # Remove www. from current domain
        current_domain = parsed.netloc.replace('www.', '')
        
        # Try each domain pair for replacement
        for orig_domain, new_domain in zip(original_domains, new_domains):
            # Remove www. from domains for comparison
            orig_domain = orig_domain.strip().lower().replace('www.', '')
            new_domain = new_domain.strip().lower().replace('www.', '')
            
            # Only replace if it matches the original domain
            if current_domain == orig_domain:
                # Create new URL with replaced domain, preserving the path encoding
                new_url = full_url.replace(parsed.netloc, new_domain)
                return new_url
    except:
        pass
    return url

def replace_text_content(text, original_domains, replacement_domains):
    if not text:
        return text
    
    # Process each domain pair
    for orig_domain, repl_domain in zip(original_domains, replacement_domains):
        orig_domain = orig_domain.strip().lower()
        repl_domain = repl_domain.strip().lower()
        
        # Replace both www and non-www versions
        text = text.replace(f'www.{orig_domain}', repl_domain)
        text = text.replace(orig_domain, repl_domain)
        
        # Replace encoded versions (for JavaScript/JSON content)
        text = text.replace(f'\\"{orig_domain}\\"', f'\\"{repl_domain}\\"')
        text = text.replace(f"\\'{orig_domain}\\'", f"\\'{repl_domain}\\'")
        
        # Replace URL-encoded versions
        text = text.replace(f'%22{orig_domain}%22', f'%22{repl_domain}%22')
    
    return text

def download_and_save_asset(url, base_url, save_path, asset_type):
    """Download asset and return local path"""
    try:
        # Handle URL-encoded paths and make URL absolute
        full_url = urljoin(base_url, url.strip())
        if not urlparse(full_url).scheme:
            full_url = 'https://' + full_url

        asset_dir = os.path.join(save_path, asset_type)
        os.makedirs(asset_dir, exist_ok=True)

        # Get the original filename
        original_filename = safe_filename(full_url)
        
        # Get content type and extension
        response = requests.get(full_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }, stream=True)
        content_type = response.headers.get('Content-Type', '').split(';')[0]
        
        # If no extension in original filename, try to get it from content type
        if not os.path.splitext(original_filename)[1]:
            ext = get_file_extension(full_url, content_type)
            original_filename = original_filename + ext

        # Save the file
        full_path = os.path.join(asset_dir, original_filename)
        with open(full_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return f'{asset_type}/{original_filename}'
    except Exception as e:
        print(f'Error downloading asset {url}: {str(e)}')
        return url  # Return original URL if download fails

def remove_tracking_scripts(soup, remove_tracking=True, remove_custom_tracking=True, remove_redirects=False):
    """Remove various tracking scripts from the HTML"""
    if not (remove_tracking or remove_custom_tracking or remove_redirects):
        return

    # Common tracking script patterns
    tracking_patterns = [
        # Meta Pixel
        r'connect\.facebook\.net/[^/]+/fbevents\.js',
        r'facebook-jssdk',
        r'fb-root',
        # Google Analytics
        r'google-analytics\.com/analytics\.js',
        r'googletagmanager\.com/gtag/js',
        r'ga\.js',
        r'gtag',
        # Google Tag Manager
        r'googletagmanager\.com/gtm\.js',
        r'gtm\.js',
        # Ringba
        r'ringba\.com',
        r'ringba\.js',
        # Other common trackers
        r'analytics',
        r'pixel\.js',
        r'tracking\.js',
        r'mixpanel',
        r'segment\.com',
        r'hotjar\.com',
    ]

    # Custom track.js patterns
    custom_tracking_patterns = [
        r'track\.js',
        r'tracking\.js',
        r'tracker\.js',
    ]

    def matches_patterns(src, patterns):
        if not src:
            return False
        return any(re.search(pattern, src, re.IGNORECASE) for pattern in patterns)

    # Remove script tags
    for script in soup.find_all('script'):
        src = script.get('src', '')
        content = script.string or ''
        
        should_remove = False
        
        if remove_tracking:
            should_remove = should_remove or matches_patterns(src, tracking_patterns)
            should_remove = should_remove or any(p in content.lower() for p in ['fbq(', 'gtag(', 'ga(', '_ringba', 'mixpanel'])
            
        if remove_custom_tracking:
            should_remove = should_remove or matches_patterns(src, custom_tracking_patterns)
            should_remove = should_remove or 'track' in content.lower()
        
        if should_remove:
            script.decompose()

    # Remove meta tags related to tracking
    if remove_tracking:
        for meta in soup.find_all('meta'):
            if meta.get('name') in ['facebook-domain-verification', 'google-site-verification']:
                meta.decompose()

    # Remove noscript tags that might contain tracking pixels
    for noscript in soup.find_all('noscript'):
        content = str(noscript).lower()
        if any(tracker in content for tracker in ['facebook', 'gtm', 'google-analytics']):
            noscript.decompose()

    # Remove inline tracking scripts from onclick and other event handlers
    for element in soup.find_all(True):
        for attr in list(element.attrs):
            if attr.startswith('on'):
                value = element[attr].lower()
                if 'track' in value or any(tracker in value for tracker in ['gtag', 'ga', 'fbq']):
                    del element[attr]

    # Remove links that redirect to external sites
    if remove_redirects:
        for link in soup.find_all('a', href=True):
            href = link['href']
            if urlparse(href).netloc and urlparse(href).netloc != urlparse(base_url).netloc:
                link.decompose()  # Remove the link if it redirects to an external site

    # Remove script tags that redirect to external sites
    if remove_redirects:
        for script in soup.find_all('script'):
            src = script.get('src', '')
            if src and urlparse(src).netloc and urlparse(src).netloc != urlparse(base_url).netloc:
                script.decompose()  # Remove the script if it redirects to an external site

def detect_encoding(content):
    """Detects the correct encoding of a webpage."""
    # First try to detect encoding from the content
    detected = chardet.detect(content)
    encoding = detected.get("encoding", "utf-8")
    
    # If confidence is low, try to find encoding in meta tags
    if detected.get("confidence", 0) < 0.8:
        soup = BeautifulSoup(content, 'html.parser')
        meta_charset = soup.find('meta', charset=True)
        if meta_charset:
            return meta_charset['charset']
        
        # Look for content-type meta tag
        meta_content_type = soup.find('meta', attrs={'http-equiv': 'Content-Type'})
        if meta_content_type and 'charset=' in meta_content_type.get('content', ''):
            return meta_content_type['content'].split('charset=')[-1]
    
    return encoding

def download_assets(url, original_domains=None, replacement_domains=None, save_dir=None, remove_tracking=False, remove_custom_tracking=False, remove_redirects=False):
    driver = None
    try:
        # Get the website name for the save directory
        website_name = urlparse(url).netloc.replace('www.', '')
        if not save_dir:
            save_dir = f'{website_name}_{int(time.time())}'
        
        # Set up Selenium WebDriver with improved options
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-infobars')
        options.add_argument('--remote-debugging-port=9222')
        options.add_argument('--window-size=1920,1080')
        
        # Add user agent to avoid detection
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        try:
            # Initialize ChromeDriver with error handling
            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(30)  # Set page load timeout
        except Exception as e:
            print(f"Error initializing WebDriver: {str(e)}")
            # Fallback to using requests if WebDriver fails
            response = requests.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            html_content = response.content  # Get raw content instead of text
        else:
            # Use Selenium to load the page and check content type
            driver.get(url)
            
            # Wait for page to load with improved error handling
            try:
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
            except Exception as e:
                print(f"Timeout waiting for page load: {str(e)}")
                # Get the page source even if timeout occurs
                html_content = driver.page_source.encode('utf-8')
            else:
                html_content = driver.page_source.encode('utf-8')
        
        # Close the browser if it was successfully created
        if driver:
            try:
                driver.quit()
            except Exception as e:
                print(f"Error closing WebDriver: {str(e)}")
        
        # Detect the correct encoding
        encoding = detect_encoding(html_content)
        print(f"Detected encoding: {encoding}")  # Debug log
        
        # Decode the content with the detected encoding
        try:
            html_content = html_content.decode(encoding)
        except UnicodeDecodeError:
            # If the detected encoding fails, try common encodings
            for enc in ['utf-8', 'latin1', 'iso-8859-1', 'cp1252']:
                try:
                    html_content = html_content.decode(enc)
                    encoding = enc
                    print(f"Fallback encoding used: {enc}")  # Debug log
                    break
                except UnicodeDecodeError:
                    continue
        
        # Create directories for different asset types
        asset_types = {
            'images': ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'],
            'css': ['.css'],
            'js': ['.js'],
            'videos': ['.mp4', '.webm', '.ogg'],
            'fonts': ['.woff', '.woff2', '.ttf', '.eot', '.otf'],
            'icons': ['.ico', '.png'],
            'others': []
        }
        
        for asset_type in asset_types:
            os.makedirs(os.path.join(save_dir, asset_type), exist_ok=True)
        
        # Ensure content is extracted properly with the correct encoding
        soup = BeautifulSoup(html_content, 'html.parser', from_encoding=encoding)
        
        # Remove tracking scripts if requested and remove redirects if enabled
        if remove_tracking or remove_custom_tracking or remove_redirects:
            remove_tracking_scripts(soup, remove_tracking, remove_custom_tracking, remove_redirects)
        
        # Save the cleaned HTML content to a file with proper encoding
        html_file_path = os.path.join(save_dir, 'index.html')
        with open(html_file_path, 'w', encoding=encoding, errors='replace') as html_file:
            html_file.write(soup.prettify())
            
        # Continue with the rest of the asset downloading process
        # Dictionary to store downloaded files and their local paths
        downloaded_files = {}

        # Step 2: First download all assets
        def download_all_assets():
            # Process all elements with URL attributes
            url_attributes = {
                'img': ['src', 'data-src', 'data-srcset'],
                'script': ['src'],
                'link': ['href'],
                'video': ['src', 'poster'],
                'source': ['src'],
                'audio': ['src'],
                'iframe': ['src'],
                'embed': ['src'],
                'object': ['data'],
                'input': ['src'],
                'meta': ['content']
            }

            for tag, attrs in url_attributes.items():
                for element in soup.find_all(tag):
                    for attr in attrs:
                        if element.has_attr(attr):
                            original_url = element[attr]
                            if original_url.startswith('data:'):
                                continue
                                
                            try:
                                # Make URL absolute
                                absolute_url = urljoin(url, original_url)
                                
                                # Skip if already downloaded
                                if absolute_url in downloaded_files:
                                    element[attr] = downloaded_files[absolute_url]
                                    continue

                                # Determine asset type and download
                                ext = os.path.splitext(urlparse(absolute_url).path)[1].lower()
                                asset_type = 'others'
                                for type_name, extensions in asset_types.items():
                                    if ext in extensions:
                                        asset_type = type_name
                                        break

                                local_path = download_and_save_asset(absolute_url, url, save_dir, asset_type)
                                if local_path:
                                    downloaded_files[absolute_url] = local_path
                                    element[attr] = local_path
                            except Exception as e:
                                print(f'Error processing URL {original_url}: {str(e)}')

            # Download and process CSS files
            for link in soup.find_all('link', rel='stylesheet'):
                if link.get('href'):
                    try:
                        css_url = urljoin(url, link['href'])
                        if css_url in downloaded_files:
                            link['href'] = downloaded_files[css_url]
                            continue

                        css_response = requests.get(css_url, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                        })
                        if css_response.ok:
                            css_content = css_response.text
                            
                            # Download assets referenced in CSS
                            url_pattern = r'url\((.*?)\)'
                            for match in re.finditer(url_pattern, css_content):
                                css_asset_url = match.group(1)
                                if not css_asset_url.startswith('data:'):
                                    absolute_url = urljoin(css_url, css_asset_url)
                                    if absolute_url not in downloaded_files:
                                        local_path = download_and_save_asset(absolute_url, url, save_dir, 'images')
                                        if local_path:
                                            downloaded_files[absolute_url] = local_path
                                            css_content = css_content.replace(css_asset_url, f'../{local_path}')

                            # Save CSS with original filename
                            css_filename = safe_filename(css_url)
                            if not css_filename.endswith('.css'):
                                css_filename += '.css'
                            css_path = os.path.join(save_dir, 'css', css_filename)
                            with open(css_path, 'w', encoding='utf-8', errors='ignore') as f:
                                f.write(css_content)
                            
                            downloaded_files[css_url] = f'css/{css_filename}'
                            link['href'] = f'css/{css_filename}'
                    except Exception as e:
                        print(f'Error processing CSS file: {str(e)}')

            # Download JavaScript files
            for script in soup.find_all('script', src=True):
                if script.get('src'):
                    try:
                        js_url = urljoin(url, script['src'])
                        if js_url in downloaded_files:
                            script['src'] = downloaded_files[js_url]
                            continue

                        js_response = requests.get(js_url, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                        })
                        if js_response.ok:
                            js_content = js_response.text
                            
                            # Save JavaScript with original filename
                            js_filename = safe_filename(js_url)
                            if not js_filename.endswith('.js'):
                                js_filename += '.js'
                            js_path = os.path.join(save_dir, 'js', js_filename)
                            with open(js_path, 'w', encoding='utf-8', errors='ignore') as f:
                                f.write(js_content)
                            
                            downloaded_files[js_url] = f'js/{js_filename}'
                            script['src'] = f'js/{js_filename}'
                    except Exception as e:
                        print(f'Error processing JavaScript file: {str(e)}')

        # Step 3: Download all assets first
        download_all_assets()

        # Download background images from styles and update paths in the CSS
        def download_background_images(soup, base_url, save_dir):
            """Download background images from styles and update paths in the soup object."""
            styles = soup.find_all('style')
            image_formats = ['.png', '.jpeg', '.jpg', '.gif', '.webp', '.webm']
            for style in styles:
                css_content = style.string
                if css_content:
                    # Find all URLs in the CSS content
                    urls = re.findall(r'url\((.*?)\)', css_content)
                    for url in urls:
                        url = url.strip('"')  # Clean URL
                        # Convert relative URLs to absolute URLs
                        full_url = urljoin(base_url, url)
                        # Check if the URL ends with an image format
                        if any(full_url.endswith(fmt) for fmt in image_formats):
                            print(f'Downloading image from: {full_url}')  # Debug log
                            local_path = download_and_save_asset(full_url, base_url, save_dir, 'images')
                            if local_path:
                                # Update the CSS content with the local path
                                css_content = css_content.replace(url, f'../{local_path}')
                    # Update the style tag with modified CSS
                    style.string = css_content

            # Check for background images in all elements with inline styles
            for element in soup.find_all(style=True):
                inline_style = element['style']
                urls = re.findall(r'background-image:\s*url\((.*?)\)', inline_style)
                for url in urls:
                    url = url.strip('"')  # Clean URL
                    full_url = urljoin(base_url, url)
                    if any(full_url.endswith(fmt) for fmt in image_formats):
                        print(f'Downloading background image from: {full_url}')  # Debug log
                        local_path = download_and_save_asset(full_url, base_url, save_dir, 'images')
                        if local_path:
                            # Update the inline style with the local path
                            inline_style = inline_style.replace(url, f'../{local_path}')
                element['style'] = inline_style

        download_background_images(soup, url, save_dir)  # Call to download background images

        # Download images from srcset attributes
        def download_images_from_srcset(soup, base_url, save_dir):
            """Download images from srcset attributes and update paths in the soup object."""
            image_formats = ['.png', '.jpeg', '.jpg', '.gif', '.webp', '.webm']
            for img in soup.find_all('img'):
                srcset = img.get('srcset')
                if srcset:
                    # Split the srcset into individual URLs
                    sources = [src.strip() for src in srcset.split(',')]
                    for source in sources:
                        url = source.split(' ')[0]  # Get the URL before any size descriptor
                        full_url = urljoin(base_url, url)
                        # Check if the URL ends with an image format
                        if any(full_url.endswith(fmt) for fmt in image_formats):
                            print(f'Downloading image from srcset: {full_url}')  # Debug log
                            local_path = download_and_save_asset(full_url, base_url, save_dir, 'images')
                            if local_path:
                                # Update the srcset with the local path
                                srcset = srcset.replace(url, local_path)
                    # Update the img tag with modified srcset
                    img['srcset'] = srcset

        download_images_from_srcset(soup, url, save_dir)

        # Download images from picture tags
        def download_images_from_picture_tags(soup, base_url, save_dir):
            """Download images from srcset attributes in picture tags and update paths in the soup object."""
            image_formats = ['.png', '.jpeg', '.jpg', '.gif', '.webp', '.webm']
            for picture in soup.find_all('picture'):
                for source in picture.find_all('source'):
                    srcset = source.get('srcset')
                    if srcset:
                        # Split the srcset into individual URLs
                        sources = [src.strip() for src in srcset.split(',')]
                        for source_url in sources:
                            url = source_url.split(' ')[0]  # Get the URL before any size descriptor
                            full_url = urljoin(base_url, url)
                            # Check if the URL ends with an image format
                            if any(full_url.endswith(fmt) for fmt in image_formats):
                                print(f'Downloading image from picture tag srcset: {full_url}')  # Debug log
                                local_path = download_and_save_asset(full_url, base_url, save_dir, 'images')
                                if local_path:
                                    # Update the srcset with the local path
                                    srcset = srcset.replace(url, local_path)
                        # Update the source tag with modified srcset
                        source['srcset'] = srcset

        download_images_from_picture_tags(soup, url, save_dir)

        # Step 4: Now perform domain replacements if needed
        if original_domains and replacement_domains:
            # Replace domains in HTML content
            html_content = str(soup)
            html_content = replace_text_content(html_content, original_domains, replacement_domains)
            soup = BeautifulSoup(html_content, 'html.parser')

            # Replace domains in all downloaded JavaScript files
            for js_file in os.listdir(os.path.join(save_dir, 'js')):
                js_path = os.path.join(save_dir, 'js', js_file)
                try:
                    with open(js_path, 'r', encoding='utf-8', errors='ignore') as f:
                        js_content = f.read()
                    js_content = replace_text_content(js_content, original_domains, replacement_domains)
                    with open(js_path, 'w', encoding='utf-8', errors='ignore') as f:
                        f.write(js_content)
                except Exception as e:
                    print(f'Error processing JavaScript file {js_file}: {str(e)}')

            # Replace domains in all downloaded CSS files
            for css_file in os.listdir(os.path.join(save_dir, 'css')):
                css_path = os.path.join(save_dir, 'css', css_file)
                try:
                    with open(css_path, 'r', encoding='utf-8', errors='ignore') as f:
                        css_content = f.read()
                    css_content = replace_text_content(css_content, original_domains, replacement_domains)
                    with open(css_path, 'w', encoding='utf-8', errors='ignore') as f:
                        f.write(css_content)
                except Exception as e:
                    print(f'Error processing CSS file {css_file}: {str(e)}')

        # Save the final modified HTML file
        with open(os.path.join(save_dir, 'index.html'), 'w', encoding='utf-8', errors='ignore') as f:
            f.write(str(soup.prettify()))

        # Create zip file
        zip_name = f'website_{int(time.time())}.zip'
        shutil.make_archive(os.path.splitext(zip_name)[0], 'zip', save_dir)

        # Clean up the temporary directory
        try:
            shutil.rmtree(save_dir)
        except Exception as e:
            print(f'Error cleaning up temporary directory: {str(e)}')

        return zip_name
    except requests.RequestException as e:
        return f"Error accessing the website: {str(e)}"
    except Exception as e:
        # Log the error message
        print(f'Error occurred: {str(e)}')  # Debug log
        
        # Check content type to ensure we're getting HTML
        content_type = e.response.headers.get('Content-Type', '').lower()
        print(f'Content-Type: {content_type}')  # Debug log
        if 'text/html' not in content_type and 'application/xhtml+xml' not in content_type:
            print(f'Unexpected content type: {content_type}')  # Log unexpected content types
            return "Error: URL does not return HTML content"
        return f"An unexpected error occurred: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download_website():
    try:
        data = request.json
        app.logger.error('Received data: %s', data)
        if not data:
            app.logger.error('Invalid JSON data')
            return jsonify({'error': 'Invalid JSON data'}), 400

        url = data.get('url')
        app.logger.info('URL provided: %s', url)
        if not url:
            app.logger.error('URL is required')
            return jsonify({'error': 'URL is required'}), 400

        # Handle optional domain replacement
        original_domains = [d.strip() for d in data.get('originalDomain', '').split(',') if d.strip()]
        replacement_domains = [d.strip() for d in data.get('replacementDomain', '').split(',') if d.strip()]
        app.logger.info('Original domains: %s', original_domains)
        app.logger.info('Replacement domains: %s', replacement_domains)
        
        # Get optional tracking removal settings
        remove_tracking = data.get('removeTracking', False)
        remove_custom_tracking = data.get('removeCustomTracking', False)
        remove_redirects = data.get('removeRedirects', False)  # New parameter for removing redirects
        app.logger.info('Remove tracking: %s, Remove custom tracking: %s, Remove redirects: %s', remove_tracking, remove_custom_tracking, remove_redirects)
        
        # Validate domains if they are provided
        if original_domains or replacement_domains:
            if not original_domains:
                app.logger.error('Original domains are required when using domain replacement')
                return jsonify({'error': 'Original domains are required when using domain replacement'}), 400
            if not replacement_domains:
                app.logger.error('Replacement domains are required when using domain replacement')
                return jsonify({'error': 'Replacement domains are required when using domain replacement'}), 400
            if len(original_domains) != len(replacement_domains):
                app.logger.error('Number of original domains must match number of replacement domains')
                return jsonify({'error': 'Number of original domains must match number of replacement domains'}), 400
            
            # Clean up domain inputs
            original_domains = [d.strip().lower().replace('www.', '') for d in original_domains]
            replacement_domains = [d.strip().lower().replace('www.', '') for d in replacement_domains]
            app.logger.info('Cleaned original domains: %s', original_domains)
            app.logger.info('Cleaned replacement domains: %s', replacement_domains)
        
        save_dir = f'temp_website_{int(time.time())}'
        zip_file = download_assets(
            url=url,
            original_domains=original_domains,
            replacement_domains=replacement_domains,
            save_dir=save_dir,
            remove_tracking=remove_tracking,
            remove_custom_tracking=remove_custom_tracking,
            remove_redirects=remove_redirects  # Pass the new parameter
        )
        app.logger.info('Zip file generated: %s', zip_file)
        
        if zip_file.endswith('.zip'):
            response = send_file(zip_file, as_attachment=True, mimetype='application/zip')
            # Clean up zip file after sending
            try:
                os.remove(zip_file)
                app.logger.info('Zip file removed after sending')
            except Exception as e:
                app.logger.error('Error removing zip file: %s', str(e))
            return response
        else:
            app.logger.error('Error in zip file generation: %s', zip_file)
            return jsonify({'error': zip_file}), 500
    except Exception as e:
        app.logger.error('Exception occurred: %s', str(e))
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000)