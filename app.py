# app.py
import time
import re
from flask import Flask, request, jsonify
from urllib.parse import urlparse, parse_qs, quote_plus
import requests
import undetected_chromedriver as uc

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


API_URL = "https://3.212.143.212/linkedin-job/api/create-job"

app = Flask(__name__)



def build_driver():
    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options)
    return driver



def extract_jk(card):
    try:
        val = card.get_attribute("data-jk")
        if val:
            return val.strip()
    except:
        pass

    # fallback
    try:
        a = card.find_element(By.CSS_SELECTOR, "a")
        href = a.get_attribute("href")
        parsed = urlparse(href)
        q = parse_qs(parsed.query)
        if "jk" in q:
            return q["jk"][0].strip()
    except:
        pass

    return None

def clean_title(title: str) -> str:
    if not title:
        return ""

    # Remove patterns like: "- job post", "– job post", "\n- job post"
    title = re.sub(r"[\n\s]*[-–]\s*job post.*$", "", title, flags=re.IGNORECASE)

    # Remove excessive whitespace
    title = re.sub(r"\s+", " ", title).strip()

    return title

def scrape_right_panel(driver):
    """Scrape from right panel."""
    try:
        WebDriverWait(driver, 5).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, "div#jobDescriptionText, div.jobsearch-JobComponent-description")
            )
        )
    except:
        return "", "", "", ""

    # TITLE — updated selectors
    title = ""
    for sel in [
        "h1.jobsearch-JobInfoHeader-title",
        "h1[data-testid='jobTitle']",
        "div.jobsearch-JobInfoHeader-title-container h1 span",
        "div[data-testid='jobTitle-heading'] span",
        "h2[data-testid='jobsearch-JobInfoHeader-title']",
    ]:
        try:
            t = driver.find_element(By.CSS_SELECTOR, sel).text.strip()
            if t:
                title = t
                break
        except:
            continue

    # COMPANY
    company = ""
    for sel in [
        "div.jobsearch-InlineCompanyRating div:nth-child(1)",
        "div[data-testid='inlineHeader-companyName']",
        "span[data-testid='company-name']",
        "a[data-testid='company-name']"
    ]:
        try:
            t = driver.find_element(By.CSS_SELECTOR, sel).text.strip()
            if t:
                company = t
                break
        except:
            continue

    # LOCATION
    location = ""
    for sel in [
        "div#jobLocationText",
        "div[data-testid='inlineHeader-companyLocation']",
        "span[data-testid='text-location']",
    ]:
        try:
            t = driver.find_element(By.CSS_SELECTOR, sel).text.strip()
            if t:
                location = t
                break
        except:
            continue

    # DESCRIPTION
    description = ""
    for sel in [
        "div#jobDescriptionText",
        "div.jobsearch-JobComponent-description",
        "div.jobsearch-jobDescriptionText"
    ]:
        try:
            t = driver.find_element(By.CSS_SELECTOR, sel).text.strip()
            if t:
                description = t
                break
        except:
            continue

    return title, company, location, description



def send_job_to_api(job):
    """Push job immediately after scraping."""
    try:
        r = requests.post(API_URL, json=job, timeout=10, verify=False)
        print("API Status:", r.status_code)
        return r.status_code
    except Exception as e:
        print("API Error:", e)
        return None



def scrape_and_send(INDEED_SEARCH, QUERY_STRING):
    driver = build_driver()
    driver.get(INDEED_SEARCH)
    time.sleep(3)

    results = []
    seen_jk = set()

    cards = driver.find_elements(By.CSS_SELECTOR, "a.tapItem, div.job_seen_beacon, div.slider_container")

    for i in range(len(cards)):
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, "a.tapItem, div.job_seen_beacon, div.slider_container")
            card = cards[i]

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
            time.sleep(0.4)

            try:
                card.click()
            except:
                driver.execute_script("arguments[0].click();", card)

            time.sleep(1)

            jk = extract_jk(card)
            if not jk or jk in seen_jk:
                continue
            seen_jk.add(jk)

            # Scrape quickly from right panel
            title, company, location, description = scrape_right_panel(driver)
            title = clean_title(title)

            # Fallback: full job page if needed
            if len(description.strip()) < 5:
                url = f"https://www.indeed.com/viewjob?jk={jk}"
                driver.get(url)
                time.sleep(1)
                title, company, location, description = scrape_right_panel(driver)
                title = clean_title(title)
                driver.get(INDEED_SEARCH)
                time.sleep(1)

            job = {
                "title": title,
                "company_name": company,
                "company_location": location,
                "description": description[:2000],
                "source_url": f"https://www.indeed.com/viewjob?jk={jk}",
                "query_string": QUERY_STRING
            }

            # PUSH TO API IMMEDIATELY
            status = send_job_to_api(job)
            job['status'] = status

            results.append(job)

        except Exception as e:
            print("Error:", e)
            continue

    driver.quit()
    return results



@app.route("/run-scraper")
def run_scraper():
    keyword = request.args.get("keyword", "").strip()
    location = request.args.get("location", "")
    fromage = request.args.get("fromage", "1")

    if not keyword:
        return jsonify({"error": "keyword parameter is required"}), 400

    q = quote_plus(keyword)
    l = quote_plus(location)
    INDEED_SEARCH = f"https://www.indeed.com/jobs?q={q}&l={l}&fromage={fromage}"

    data = scrape_and_send(INDEED_SEARCH, keyword)
    return jsonify(data)



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
