import requests
import time
import logging
import os
import re
import copy
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException, ElementNotInteractableException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from datetime import datetime, timedelta




# Allow selenium to ignore SSL errors
chrome_options = Options()
chrome_options.add_argument("--ignore-certificate-errors")


# Global variable to store processed Solana addresses
processed_addresses = set()

# Get the absolute path to the directory of the current script
script_directory = os.path.dirname(os.path.abspath(__file__))

# Set up logging with the log file in the script directory
log_file_path = os.path.join(script_directory, 'sus.log')
logging.basicConfig(filename=log_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Clear the existing log file
with open(log_file_path, 'w'):
    pass

# Add a new handler for debug messages to the console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
logging.getLogger().addHandler(console_handler)

def scroll_down(driver, max_scrolls, min_end_time_hours=24):
    for _ in range(max_scrolls):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)  # Wait for the page to load

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        raffles = soup.select('.p-4.bg-white.dark\\:bg-offbase.transition-all.overflow-hidden.rounded-b-2xl')

        found_valid_raffle = False

        for raffle in raffles:
            end_time_text = raffle.select_one('.bg-gradient-to-t span').text.strip()
            total_hours = convert_to_hours(end_time_text)

            if total_hours >= min_end_time_hours:
                found_valid_raffle = True
                break

        if found_valid_raffle:
            break  # Stop scrolling if a valid raffle is found

    return found_valid_raffle



def close_popup(driver):
    try:
        close_button_xpath = '//button[contains(@class, "absolute -top-10 -right-10 text-white")]'
        close_button = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, close_button_xpath))
        )
        close_button.click()
    except NoSuchElementException:
        logging.info("Close button not found. Popup may not be present.")
    except ElementNotInteractableException:
        logging.warning("Close button is not interactable. The popup may not be in the expected state.")
    except TimeoutException:
        logging.warning("Timeout waiting for the close button to be visible.")
    except Exception as e:
        logging.error(f"Error while closing popup: {type(e).__name__}: {e}")


# Constants for risk values
TIER_1_RISK = 30
TIER_2_RISK = 15
MULTI_RAFFLE_RISK = 20
NEAR_END_TIME_RISK = 35


def calculate_risk(tier, user_name, raffle_data_list, time_frame_hours):
    risk = 0

    # Adjust risk based on tier
    if tier == 'T1':
        risk += 30
    elif tier == 'T2':
        risk += 15
    # ... handle other tiers as needed ...

    # Calculate risk based on multiple raffles by the same user within the time frame
    same_person_raffles = [raffle for raffle in raffle_data_list if raffle.get('user_name') == user_name]

    # Check each raffle for the user and calculate risk
    for raffle in same_person_raffles:
        raffle_end_time_hours = convert_to_hours(raffle.get('end_time_text', ''))

        # Increase risk significantly for raffles ending within 1 hour
        if raffle_end_time_hours <= 1:
            risk += 35
            print(f"High risk added for raffle ending in {raffle_end_time_hours} hours (User: {user_name})")

        # Also check if the raffle is within the specified time frame
        if raffle_end_time_hours <= time_frame_hours:
            risk += 10  # Adjust this value as needed

    return min(risk, 100)


def convert_to_hours(end_time_text):
    # Regular expression to extract hours, minutes, and seconds
    time_pattern = r'(\d+)\s*hrs?|\s*(\d+)\s*mins?|\s*(\d+)\s*s'
    matches = re.findall(time_pattern, end_time_text)

    total_hours = 0
    for hrs, mins, secs in matches:
        # Convert the captured groups to integers and add to total hours
        total_hours += int(hrs) if hrs else 0
        total_hours += int(mins) / 60 if mins else 0  # Convert minutes to hours
        total_hours += int(secs) / 3600 if secs else 0  # Convert seconds to hours

    return total_hours

	
	
def combine_raffle_data(raffle_data_list):
    combined_data = {}
    for data in raffle_data_list:
        user_name = data['user_name'].strip()  # Ensure consistent formatting

        if user_name in combined_data:
            # Increment the count of raffles for this user
            combined_data[user_name]['raffle_count'] += 1

            # Safely get and compare 'end_time'
            if 'end_time' in data and 'end_time' in combined_data[user_name]:
                combined_data[user_name]['end_time'] = max(combined_data[user_name]['end_time'], data['end_time'])

            # Safely get and compare 'spl_token_count'
            if 'spl_token_count' in data and 'spl_token_count' in combined_data[user_name]:
                combined_data[user_name]['spl_token_count'] = max(combined_data[user_name]['spl_token_count'],
                                                                  data['spl_token_count'])

            # Safely get and compare 'risk'
            if 'risk' in data and 'risk' in combined_data[user_name]:
                combined_data[user_name]['risk'] = max(combined_data[user_name]['risk'], data['risk'])

            logging.info(f"Updated data for user: {user_name} - {combined_data[user_name]}")
        else:
            # Initialize raffle count for this new user
            data['raffle_count'] = 1
            combined_data[user_name] = copy.deepcopy(data)

    return list(combined_data.values())

	

def parse_end_time(end_time_text):
    # Regex pattern to extract hours, minutes, and seconds
    time_pattern = r'(\d+)\s*hrs?|\s*(\d+)\s*mins?|\s*(\d+)\s*s'
    matches = re.findall(time_pattern, end_time_text)

    # Initialize total seconds to zero
    total_seconds = 0

    for hrs, mins, secs in matches:
        # Convert the captured groups to integers and calculate total seconds
        total_seconds += int(hrs) * 3600 if hrs else 0
        total_seconds += int(mins) * 60 if mins else 0
        total_seconds += int(secs) if secs else 0

    return total_seconds
	


def get_token_holdings(wallet_address, geckodriver_path):
    max_retries = 3  # Set the number of retries
    attempt = 0
    wait_time = 5  # Initial wait time in seconds

    while attempt < max_retries:
        try:
            firefox_options = FirefoxOptions()
            firefox_options.add_argument("--headless")
            service = FirefoxService(executable_path=geckodriver_path)
            driver = webdriver.Firefox(service=service, options=firefox_options)

            url = f"https://solscan.io/address/{wallet_address}/"
            driver.get(url)
            time.sleep(wait_time)  # Wait for the page to load

            page_source = driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            token_info_div = soup.find('div', string=re.compile(r'\bSPL Token Balance\b'), class_='ant-col ant-col-24 ant-col-md-8')
            
            # Print the relevant HTML for debugging
            print("HTML for token info div:", token_info_div)
            if token_info_div and token_info_div.find_next_sibling('div'):
                token_count_div = token_info_div.find_next_sibling('div')
                print("HTML for token count div:", token_count_div)  # Print the sibling div
                token_count_text = token_count_div.get_text(strip=True)
                print("Extracted token count text:", token_count_text)  # Print the extracted text
                match = re.search(r'(\d+)\s+SPL\s+token(s)?', token_count_text)
                if match:
                    spl_token_count = int(match.group(1))
                    driver.quit()
                    return spl_token_count
                else:
                    raise ValueError("Token count not found in expected format.")
            else:
                raise ValueError("Token info div not found or no sibling element.")

        except Exception as e:
            logging.error(f"Attempt {attempt}: Error while retrieving token holdings - {e}")
            if driver:
                driver.quit()
            attempt += 1
            wait_time *= 3  # Increase wait time for each retry

    logging.error("Failed to retrieve token holdings after maximum retries.")
    return 0  # Default value in case of failure






def extract_raffle_data(raffle):
    try:
        # Existing code for flex_items_center_tag
        flex_items_center_tag = raffle.select_one('.flex.items-center a')

        # Initialize collection_last_word
        collection_last_word = None

        # Check and process based on the href attribute of flex_items_center_tag
        if flex_items_center_tag:
            collection_url = flex_items_center_tag['href']

            if "magiceden.io" in collection_url:
                # Extract the last part of the URL
                collection_last_word = collection_url.split('/')[-1]
            elif "solscan.io" in collection_url:
                # Extract "Verified Token" and "5M BONK" texts
                verified_token_tag = raffle.select_one('.flex.items-center a[href^="https://solscan.io/token/"]')
                title_tag = raffle.select_one('h2')
                verified_token = verified_token_tag.text.strip() if verified_token_tag else ""
                title = title_tag.text.strip() if title_tag else ""
                collection_last_word = f"{verified_token} {title}"

        # Extracting other raffle data
        tier_badge_selector = '.tipcontainer .tierBadgeTooltip + div'
        tier_badge_tag = raffle.select_one(tier_badge_selector)
        tier_badge = tier_badge_tag.text.strip() if tier_badge_tag else None

        end_time_text_tag = raffle.select_one('.bg-gradient-to-t span')
        end_time_text = end_time_text_tag.text.strip() if end_time_text_tag else ""

        raffle_link_selector = '.flex.justify-between.gap-x-3 a'
        raffle_link_tag = raffle.select_one(raffle_link_selector)
        raffle_link = raffle_link_tag['href'] if raffle_link_tag else ""

        user_link_selector = 'a[href^="/profile/"][class="text-purple-500 hover:text-purple-400 font-bold"]'
        user_link_tag = raffle.select_one(user_link_selector)
        user_link = user_link_tag['href'] if user_link_tag else ""

        user_name_tag = raffle.select_one(user_link_selector)
        user_name = user_name_tag.text.strip('@') if user_name_tag else ""

        return {
            'collection_name': collection_last_word,
            'tier_badge': tier_badge,
            'end_time_text': end_time_text,
            'raffle_link': raffle_link,
            'user_link': user_link,
            'user_name': user_name
        }
    except Exception as e:
        logging.exception(f"Error extracting raffle data: {e}")
        return None




def scrape_raffles():
    url = "https://rafffle.famousfoxes.com"
    geckodriver_path = 'C:\\Users\\Deez\\Desktop\\chromedriver_win32\\geckodriver.exe'
    firefox_options = FirefoxOptions()
    firefox_options.add_argument("--headless")  # Optional: if you want to run headless

    driver = None
    raffle_data_list = []

    try:
        # WebDriver initialization
        service = FirefoxService(executable_path=geckodriver_path)
        driver = webdriver.Firefox(service=service, options=firefox_options)

        driver.get(url)
        close_popup(driver)  # Uncomment and define this function if you have it
        logging.info("Webdriver initialized successfully.")

        max_scroll_attempts = 10
        min_end_time_hours = 12  # Set the minimum end time in hours
        skip_list = set()  # Initialize the skip list
        processed_addresses = set()  # Initialize the processed addresses

        if scroll_down(driver, max_scroll_attempts, min_end_time_hours):  # Define scroll_down elsewhere
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            raffles = soup.select('.p-4.bg-white.dark\\:bg-offbase.transition-all.overflow-hidden.rounded-b-2xl')

            for raffle in raffles:
                raffle_data = extract_raffle_data(raffle)  # Define extract_raffle_data elsewhere
                if raffle_data is None or raffle_data['user_name'] in skip_list:
                    continue

                if raffle_data['tier_badge'] not in ['T1', 'T2']:
                    skip_list.add(raffle_data['user_name'])
                    logging.info(f"Skipping raffle for {raffle_data['user_name']} as it is not Tier 1 or Tier 2")
                    continue

                user_address = raffle_data['user_link'].split('/')[-1]
                if user_address not in processed_addresses:
                    spl_token_count = get_token_holdings(user_address, geckodriver_path)  # Define get_token_holdings elsewhere
                    processed_addresses.add(user_address)
                else:
                    spl_token_count = 0

                risk = calculate_risk(raffle_data['tier_badge'], raffle_data['user_name'], raffle_data_list, 3)  # Define calculate_risk elsewhere
                if spl_token_count > 20:
                    risk *= 0.65  # Reduce risk by 35%

                end_time_delta = end_time_to_timedelta(raffle_data['end_time_text'])

                raffle_data_list.append({
                    'risk': risk,
                    'spl_token_count': spl_token_count,
                    'user_name': raffle_data['user_name'],
                    'tier_badge': raffle_data['tier_badge'],
                    'end_time': raffle_data['end_time_text'],
                    'end_time_delta': end_time_delta,
                    'collection_name': raffle_data['collection_name'],
                    'raffle_link': url + raffle_data['raffle_link'],
                    'user_link': url + raffle_data['user_link']
                })
				
				# Combining the raffle data
                raffle_data_list = combine_raffle_data(raffle_data_list)

            raffle_data_list.sort(key=lambda x: (x['risk'], -x['spl_token_count'], -len(set(x['user_name'])), x['end_time_delta']), reverse=True)

        else:
            logging.info("No raffles found within 24 hours after scrolling.")

    except (TimeoutException, WebDriverException) as e:
        logging.error(f"Webdriver error: {e}")
    finally:
        if driver:
            driver.quit()
            logging.info("Webdriver closed successfully.")

        if raffle_data_list:
            webhook_url = 'https://discord.com/api/webhooks/979393556278026272/3poFhlnR8vNte7eqLN7n_EjXqwyFR-RFIG3QhiGnGe665a9M79VaJ8ZMJrItaJFN2uml'  # Replace with your actual Discord webhook URL
            for raffle in raffle_data_list:
                try:
                    send_to_discord_webhook(raffle, webhook_url)  # Define send_to_discord_webhook elsewhere
                except requests.exceptions.HTTPError as e:
                    logging.error(f"Error sending data to Discord: {e}")
					

def end_time_to_timedelta(end_time_text):
    parts = end_time_text.replace('Ends in ', '').split(' ')
    hours, minutes, seconds = 0, 0, 0
    for i in range(0, len(parts), 2):
        value = int(parts[i])
        if 'hr' in parts[i+1]:
            hours = value
        elif 'min' in parts[i+1]:
            minutes = value
        elif 's' in parts[i+1]:
            seconds = value
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)
	

def format_discord_embed(raffle_data):
    """
    Formats the raffle data into a Discord embed structure.

    :param raffle_data: Dictionary containing raffle information.
    :return: A dictionary representing a Discord embed.
    """
    # Extracting user address for Solscan link
    user_address = raffle_data['user_link'].split('/')[-1]
    solscan_link = f"https://solscan.io/account/{user_address}"

    # Safely getting values, using defaults if not present
    end_time_value = raffle_data.get('end_time', 'N/A')
    risk_value = str(raffle_data.get('risk', 'N/A'))
    spl_token_count_value = str(raffle_data.get('spl_token_count', 'N/A'))
    live_raffle_count_value = str(raffle_data.get('raffle_count', 'N/A'))

    embed = {
        "title": f"{raffle_data['collection_name']} Raffle",
        "url": raffle_data['raffle_link'],
        "fields": [
            {"name": "User", "value": raffle_data['user_name'], "inline": True},
            {"name": "Tier Badge", "value": raffle_data.get('tier_badge', 'N/A'), "inline": True},
            {"name": "End Time", "value": end_time_value, "inline": True},
            {"name": "Risk", "value": risk_value, "inline": True},
            {"name": "SPL Token Count", "value": spl_token_count_value, "inline": True},
            {"name": "Live raffle count", "value": live_raffle_count_value, "inline": True},
            {"name": "User Profile", "value": raffle_data['user_link'], "inline": False},
            {"name": "Raffle Link", "value": raffle_data['raffle_link'], "inline": False},
            {"name": "Twitter Profile", "value": f"[{raffle_data['user_name']}](https://twitter.com/{raffle_data['user_name']})", "inline": False},
            {"name": "Solscan Profile", "value": solscan_link, "inline": False}
        ],
        "color": 5814783  # You can change this to a different color code
    }
    return embed



	
def send_to_discord_webhook(raffle_data, webhook_url):
    """
    Sends a formatted Discord webhook message with raffle data.
    
    :param raffle_data: Dictionary containing raffle information.
    :param webhook_url: URL of the Discord webhook.
    """
    try:
        embed = format_discord_embed(raffle_data)
        payload = {
            "username": "Raffle Bot",
            "embeds": [embed],
        }
        headers = {
            "Content-Type": "application/json"
        }
        response = requests.post(webhook_url, json=payload, headers=headers)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logging.error(f"Error sending data to Discord: {e}")


def end_time_to_sortable_format(end_time_str):
    # Convert 'end_time_str' to a sortable format
    try:
        # Assuming the format is like "2 hours, 30 minutes"
        # You might need to adjust the parsing based on the actual format
        return parse_relative_time(end_time_str)
    except ValueError:
        # Fallback in case of parsing error
        return datetime.datetime.max

def parse_relative_time(time_str):
    # Placeholder function to parse relative time strings
    # Replace this with actual parsing logic based on your format
    return datetime.datetime.now()  # Replace with actual parsing
	
	


if __name__ == "__main__":
    success = scrape_raffles()
    if success:
        logging.info("Raffles scraped successfully.")
    else:
        logging.info("Raffles scraping finished with no results.")
		
		

