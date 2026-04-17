"""
Redfin Data Scraper
Fetches real estate listings data from Redfin for days on market analysis.
"""

import requests
import pandas as pd
from io import StringIO
import time
import json
import re


class RedfinScraper:
    """Scraper for Redfin real estate data."""

    BASE_URL = "https://www.redfin.com"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def search_by_zip(self, zip_code: str) -> pd.DataFrame:
        """
        Search Redfin listings by zip code and return as DataFrame.
        """
        print(f"Searching for zip code: {zip_code}")

        # Method 1: Try the direct CSV download with region lookup
        df = self._try_csv_download(zip_code)
        if not df.empty:
            return df

        # Method 2: Try scraping the search page
        df = self._try_page_scrape(zip_code)
        if not df.empty:
            return df

        # Method 3: Try the stingray API directly
        df = self._try_stingray_api(zip_code)
        if not df.empty:
            return df

        print("All methods failed to retrieve data")
        return self._empty_dataframe()

    def _try_csv_download(self, zip_code: str) -> pd.DataFrame:
        """Try to download CSV using Redfin's gis-csv endpoint."""
        try:
            print("Trying CSV download method...")

            # First get region info
            region_url = f"{self.BASE_URL}/stingray/do/location-autocomplete?location={zip_code}&v=2"
            response = self.session.get(region_url)
            time.sleep(0.5)

            if response.status_code != 200:
                print(f"Region lookup failed: {response.status_code}")
                return self._empty_dataframe()

            text = response.text
            if text.startswith("{}&&"):
                text = text[4:]

            data = json.loads(text)

            # Extract region ID - look for zip code type (type 2)
            region_id = None
            if "payload" in data and "sections" in data["payload"]:
                for section in data["payload"]["sections"]:
                    for row in section.get("rows", []):
                        # Type 2 is zip code
                        if str(row.get("type")) == "2":
                            region_id = row.get("id")
                            print(f"Found region ID: {region_id}")
                            break
                    if region_id:
                        break

            if not region_id:
                print("Could not find region ID")
                return self._empty_dataframe()

            # Now fetch CSV
            csv_url = f"{self.BASE_URL}/stingray/api/gis-csv"
            params = {
                "al": "1",
                "num_homes": "500",
                "page_number": "1",
                "region_id": region_id,
                "region_type": "2",
                "sf": "1,2,3,5,6,7",
                "status": "9",
                "uipt": "1,2,3,4,5,6,7,8",
                "v": "8"
            }

            response = self.session.get(csv_url, params=params)
            time.sleep(0.5)

            if response.status_code == 200 and "ADDRESS" in response.text:
                df = pd.read_csv(StringIO(response.text))
                print(f"CSV download successful: {len(df)} listings")
                return self._normalize_dataframe(df)
            else:
                print(f"CSV download failed: {response.status_code}")

        except Exception as e:
            print(f"CSV download error: {e}")

        return self._empty_dataframe()

    def _try_page_scrape(self, zip_code: str) -> pd.DataFrame:
        """Try to scrape the search results page directly."""
        try:
            print("Trying page scrape method...")

            # Go directly to zip code search URL
            search_url = f"{self.BASE_URL}/zipcode/{zip_code}"
            response = self.session.get(search_url)
            time.sleep(1)

            if response.status_code != 200:
                print(f"Page scrape failed: {response.status_code}")
                return self._empty_dataframe()

            # Look for embedded JSON data
            # Redfin embeds property data in a script tag
            patterns = [
                r'window\.__PRELOADED_STATE__\s*=\s*({.*?});',
                r'"homes":\s*(\[.*?\])',
                r'"searchResults":\s*({.*?}),\s*"',
            ]

            for pattern in patterns:
                match = re.search(pattern, response.text, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        listings = self._extract_from_json(data)
                        if listings:
                            print(f"Page scrape successful: {len(listings)} listings")
                            return pd.DataFrame(listings)
                    except json.JSONDecodeError:
                        continue

            # Try to find individual property cards
            listings = self._parse_property_cards(response.text)
            if listings:
                print(f"Property card parse successful: {len(listings)} listings")
                return pd.DataFrame(listings)

        except Exception as e:
            print(f"Page scrape error: {e}")

        return self._empty_dataframe()

    def _try_stingray_api(self, zip_code: str) -> pd.DataFrame:
        """Try the stingray search API."""
        try:
            print("Trying stingray API method...")

            api_url = f"{self.BASE_URL}/stingray/api/gis"
            params = {
                "al": "1",
                "num_homes": "500",
                "page_number": "1",
                "poly": f"-90 30,-90 35,-85 35,-85 30,-90 30",  # Rough polygon
                "sf": "1,2,3,5,6,7",
                "status": "9",
                "uipt": "1,2,3,4,5,6,7,8",
                "v": "8",
                "zl": "12",
            }

            response = self.session.get(api_url, params=params)
            time.sleep(0.5)

            if response.status_code == 200:
                text = response.text
                if text.startswith("{}&&"):
                    text = text[4:]

                data = json.loads(text)
                listings = self._extract_from_gis_response(data)
                if listings:
                    print(f"Stingray API successful: {len(listings)} listings")
                    return pd.DataFrame(listings)

        except Exception as e:
            print(f"Stingray API error: {e}")

        return self._empty_dataframe()

    def _extract_from_json(self, data, listings=None, depth=0):
        """Recursively extract listings from JSON data."""
        if listings is None:
            listings = []
        if depth > 30:
            return listings

        if isinstance(data, dict):
            # Check if this looks like a property
            if self._looks_like_property(data):
                listing = self._extract_property_data(data)
                if listing:
                    listings.append(listing)
            else:
                for value in data.values():
                    self._extract_from_json(value, listings, depth + 1)
        elif isinstance(data, list):
            for item in data:
                self._extract_from_json(item, listings, depth + 1)

        return listings

    def _looks_like_property(self, data):
        """Check if a dict looks like a property listing."""
        property_keys = ["price", "beds", "baths", "sqFt", "listingId", "mlsId"]
        return sum(1 for k in property_keys if k in data) >= 2

    def _extract_property_data(self, data):
        """Extract standardized property data from various formats."""
        try:
            # Handle nested value objects (e.g., {"value": 500000})
            def get_val(obj, key, default=0):
                val = obj.get(key, default)
                if isinstance(val, dict):
                    return val.get("value", default)
                return val if val is not None else default

            address = (data.get("streetLine") or
                      data.get("address") or
                      data.get("streetAddress") or
                      get_val(data, "streetLine") or
                      "Unknown")
            if isinstance(address, dict):
                address = address.get("value", "Unknown")

            return {
                "ADDRESS": str(address),
                "PRICE": get_val(data, "price", 0),
                "BEDS": get_val(data, "beds", 0),
                "BATHS": get_val(data, "baths", 0),
                "SQUARE FEET": get_val(data, "sqFt", 0),
                "LOT SIZE": get_val(data, "lotSize", 0),
                "DAYS ON MARKET": get_val(data, "dom", get_val(data, "timeOnRedfin", 0)),
            }
        except Exception:
            return None

    def _extract_from_gis_response(self, data):
        """Extract listings from GIS API response."""
        listings = []
        try:
            homes = data.get("payload", {}).get("homes", [])
            for home in homes:
                listing = self._extract_property_data(home)
                if listing:
                    listings.append(listing)
        except Exception:
            pass
        return listings

    def _parse_property_cards(self, html):
        """Parse property data from HTML property cards."""
        listings = []
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            # Find property cards
            cards = soup.find_all('div', {'class': re.compile(r'HomeCard|MapHomeCard|homecard', re.I)})

            for card in cards:
                try:
                    listing = {
                        "ADDRESS": "Unknown",
                        "PRICE": 0,
                        "BEDS": 0,
                        "BATHS": 0,
                        "SQUARE FEET": 0,
                        "LOT SIZE": 0,
                        "DAYS ON MARKET": 0,
                    }

                    # Extract price
                    price_el = card.find(class_=re.compile(r'price', re.I))
                    if price_el:
                        price_text = re.sub(r'[^\d]', '', price_el.get_text())
                        if price_text:
                            listing["PRICE"] = int(price_text)

                    # Extract address
                    addr_el = card.find(class_=re.compile(r'address|street', re.I))
                    if addr_el:
                        listing["ADDRESS"] = addr_el.get_text().strip()

                    # Extract beds/baths/sqft
                    stats_el = card.find(class_=re.compile(r'stats|HomeStats', re.I))
                    if stats_el:
                        text = stats_el.get_text()
                        beds_match = re.search(r'(\d+)\s*(?:bd|bed)', text, re.I)
                        baths_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:ba|bath)', text, re.I)
                        sqft_match = re.search(r'([\d,]+)\s*(?:sq|sf)', text, re.I)

                        if beds_match:
                            listing["BEDS"] = int(beds_match.group(1))
                        if baths_match:
                            listing["BATHS"] = float(baths_match.group(1))
                        if sqft_match:
                            listing["SQUARE FEET"] = int(sqft_match.group(1).replace(',', ''))

                    if listing["PRICE"] > 0:
                        listings.append(listing)

                except Exception:
                    continue

        except Exception as e:
            print(f"Property card parse error: {e}")

        return listings

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names and data types."""
        # Redfin CSV uses these column names
        column_mapping = {
            "ADDRESS": "ADDRESS",
            "CITY": "CITY",
            "STATE OR PROVINCE": "STATE",
            "ZIP OR POSTAL CODE": "ZIP",
            "PRICE": "PRICE",
            "BEDS": "BEDS",
            "BATHS": "BATHS",
            "SQUARE FEET": "SQUARE FEET",
            "LOT SIZE": "LOT SIZE",
            "DAYS ON MARKET": "DAYS ON MARKET",
        }

        # Rename columns if they exist
        rename_map = {old: new for old, new in column_mapping.items() if old in df.columns}
        if rename_map:
            df = df.rename(columns=rename_map)

        # Ensure required columns exist
        required_cols = ["ADDRESS", "PRICE", "BEDS", "BATHS", "SQUARE FEET",
                        "LOT SIZE", "DAYS ON MARKET"]
        for col in required_cols:
            if col not in df.columns:
                df[col] = 0 if col != "ADDRESS" else "Unknown"

        # Convert numeric columns
        numeric_cols = ["PRICE", "BEDS", "BATHS", "SQUARE FEET", "LOT SIZE", "DAYS ON MARKET"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        return df

    def _empty_dataframe(self) -> pd.DataFrame:
        """Return an empty DataFrame with the expected schema."""
        return pd.DataFrame(columns=[
            "ADDRESS", "CITY", "STATE", "ZIP", "PRICE", "BEDS", "BATHS",
            "SQUARE FEET", "LOT SIZE", "DAYS ON MARKET", "URL"
        ])


def filter_listings(df: pd.DataFrame,
                   min_price: float = 0,
                   max_price: float = float('inf'),
                   min_sqft: float = 0,
                   max_sqft: float = float('inf'),
                   min_beds: int = 0,
                   max_beds: int = 100,
                   min_baths: float = 0,
                   max_baths: float = 100,
                   min_lot: float = 0,
                   max_lot: float = float('inf')) -> pd.DataFrame:
    """Filter listings DataFrame by the given criteria."""
    if df.empty:
        return df

    mask = (
        (df["PRICE"] >= min_price) &
        (df["PRICE"] <= max_price) &
        (df["SQUARE FEET"] >= min_sqft) &
        (df["SQUARE FEET"] <= max_sqft) &
        (df["BEDS"] >= min_beds) &
        (df["BEDS"] <= max_beds) &
        (df["BATHS"] >= min_baths) &
        (df["BATHS"] <= max_baths) &
        (df["LOT SIZE"] >= min_lot) &
        (df["LOT SIZE"] <= max_lot)
    )

    return df[mask].copy()


def calculate_dom_stats(df: pd.DataFrame) -> dict:
    """Calculate days on market statistics."""
    if df.empty or "DAYS ON MARKET" not in df.columns:
        return {"average": 0, "median": 0, "min": 0, "max": 0, "count": 0}

    dom = df["DAYS ON MARKET"]
    return {
        "average": round(dom.mean(), 1),
        "median": round(dom.median(), 1),
        "min": int(dom.min()),
        "max": int(dom.max()),
        "count": len(dom)
    }


if __name__ == "__main__":
    scraper = RedfinScraper()
    print("Testing Redfin scraper...")
    df = scraper.search_by_zip("39211")
    print(f"Found {len(df)} listings")
    if not df.empty:
        print(df.head())
        stats = calculate_dom_stats(df)
        print(f"DOM Stats: {stats}")
