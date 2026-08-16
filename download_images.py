import os
import re
import csv
import hashlib
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = ""
OUTPUT_DIR = "/images"
CSV_FILE = "images/image_sources.csv"

# Pages we want to crawl.
START_PAGES = [
    "/",
    "/about-us",
    "/faculties",
    "/admission",
    "/teaching-materials",
    "/contact-us",
]

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".svg",
}


session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151.0 Safari/537.36"
    )
})


os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs("jhss-images", exist_ok=True)


visited_pages = set()
downloaded_hashes = set()
image_sources = []


def is_image_url(url):
    """
    Check whether a URL looks like an image URL.
    """
    parsed = urlparse(url)

    path = parsed.path.lower()

    # Normal image extension
    if any(path.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return True

    # WordPress image URLs sometimes have query parameters.
    if "/wp-content/uploads/" in path:
        return True

    return False


def clean_filename(url, index):
    """
    Create a safe filename from an image URL.
    """

    parsed = urlparse(url)

    filename = os.path.basename(parsed.path)

    # Remove WordPress size suffixes:
    # image-150x150.jpg
    # image-768x1024.jpg
    filename = re.sub(
        r"-\d+x\d+(?=\.[a-zA-Z]+$)",
        "",
        filename
    )

    # Remove weird characters
    filename = re.sub(
        r"[^a-zA-Z0-9._-]",
        "_",
        filename
    )

    if not filename or "." not in filename:
        filename = f"image_{index}.jpg"

    return filename


def download_image(url, page_url, index):
    """
    Download one image and record its source.
    """

    try:
        response = session.get(
            url,
            timeout=20,
            stream=True
        )

        if response.status_code != 200:
            print(
                f"[FAILED] {response.status_code} {url}"
            )
            return

        content_type = response.headers.get(
            "Content-Type",
            ""
        ).lower()

        if (
            not content_type.startswith("image/")
            and not is_image_url(url)
        ):
            return

        data = response.content

        if not data:
            return

        # Hash image to detect duplicates.
        image_hash = hashlib.sha256(data).hexdigest()

        if image_hash in downloaded_hashes:
            print(f"[DUPLICATE] {url}")
            return

        downloaded_hashes.add(image_hash)

        filename = clean_filename(
            url,
            index
        )

        destination = os.path.join(
            OUTPUT_DIR,
            filename
        )

        # Prevent filename collisions.
        if os.path.exists(destination):

            name, extension = os.path.splitext(
                filename
            )

            destination = os.path.join(
                OUTPUT_DIR,
                f"{name}_{index}{extension}"
            )

            filename = os.path.basename(
                destination
            )

        with open(destination, "wb") as file:
            file.write(data)

        image_sources.append({
            "filename": filename,
            "original_url": url,
            "page_found_on": page_url
        })

        print(f"[DOWNLOADED] {filename}")

    except Exception as error:
        print(
            f"[ERROR] {url}\n"
            f"        {error}"
        )


def crawl_page(url):
    """
    Download images from one webpage.
    """

    if url in visited_pages:
        return

    visited_pages.add(url)

    print()
    print("=" * 70)
    print(f"Crawling: {url}")
    print("=" * 70)

    try:

        response = session.get(
            url,
            timeout=20
        )

        response.raise_for_status()

    except Exception as error:

        print(
            f"[PAGE ERROR] {url}\n"
            f"             {error}"
        )

        return

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    images = soup.find_all("img")

    print(
        f"Found {len(images)} <img> elements"
    )

    for index, img in enumerate(
        images,
        start=1
    ):

        # Normal src
        src = img.get("src")

        # Lazy-loaded images
        if not src:
            src = (
                img.get("data-src")
                or img.get("data-lazy-src")
            )

        # srcset
        if not src:
            srcset = img.get("srcset")

            if srcset:
                src = srcset.split(",")[0].strip()
                src = src.split(" ")[0]

        if not src:
            continue

        image_url = urljoin(
            url,
            src
        )

        # Only download JHSS images.
        parsed = urlparse(image_url)

        if parsed.netloc not in {
            "jhss.edu.np",
            "www.jhss.edu.np"
        }:
            continue

        if not is_image_url(image_url):
            continue

        download_image(
            image_url,
            url,
            len(image_sources) + 1
        )


def discover_internal_pages(url):
    """
    Find links to other JHSS pages.
    """

    try:

        response = session.get(
            url,
            timeout=20
        )

        response.raise_for_status()

    except Exception:
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    pages = []

    for link in soup.find_all("a", href=True):

        href = urljoin(
            url,
            link["href"]
        )

        parsed = urlparse(href)

        if parsed.netloc not in {
            "jhss.edu.np",
            "www.jhss.edu.np"
        }:
            continue

        # Remove fragments.
        href = href.split("#")[0]

        # Don't crawl files.
        if any(
            parsed.path.lower().endswith(ext)
            for ext in [
                ".pdf",
                ".doc",
                ".docx",
                ".zip",
                ".mp4",
                ".mp3"
            ]
        ):
            continue

        pages.append(href)

    return list(set(pages))


def save_csv():

    with open(
        CSV_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=[
                "filename",
                "original_url",
                "page_found_on"
            ]
        )

        writer.writeheader()

        writer.writerows(
            image_sources
        )


def main():

    print()
    print("==============================================")
    print("       JHSS IMAGE DOWNLOADER")
    print("==============================================")
    print()

    # First crawl known important pages.
    pages = [
        urljoin(BASE_URL, path)
        for path in START_PAGES
    ]

    # Discover additional pages.
    for page in list(pages):

        discovered = discover_internal_pages(
            page
        )

        pages.extend(discovered)

    # Remove duplicates.
    pages = list(dict.fromkeys(pages))

    print(
        f"Pages discovered: {len(pages)}"
    )

    # Crawl pages.
    for page in pages:

        crawl_page(page)

    save_csv()

    print()
    print("==============================================")
    print("                 COMPLETE")
    print("==============================================")
    print()
    print(
        f"Images downloaded: {len(image_sources)}"
    )
    print(
        f"Images folder: {OUTPUT_DIR}"
    )
    print(
        f"Source CSV: {CSV_FILE}"
    )
    print()


if __name__ == "__main__":
    main()