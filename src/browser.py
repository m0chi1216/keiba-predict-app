"""One Chromium configuration for race listing and prediction data collection."""
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service


def create_chrome_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-dev-shm-usage")
    if os.environ.get("CHROME_NO_SANDBOX", "false").lower() == "true":
        options.add_argument("--no-sandbox")
    if os.environ.get("CHROME_BINARY"):
        options.binary_location = os.environ["CHROME_BINARY"]
    driver = webdriver.Chrome(service=Service(executable_path=os.environ.get("SE_CHROMEDRIVER")), options=options)
    driver.set_page_load_timeout(45)
    return driver
