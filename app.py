''' 
    author: Dawid Żuchowski
    Program do odpytania listy mailingowej o adresy poprzez API FreshMail.
    Następnie przetwarza wynik api i zapisuje wyniki do records.json
    Następnie wysyła maila z nowym rekordem na adres    
'''

import requests
import time
import os
import zipfile
import csv
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

### POCZĄTEK SEKCJI API FRESHMAIL

authorization = "Bearer xxx" # WPISZ TOKEN API !!!

list_id = "" # WPISZ ID LISTY !!!

def authorize():
    url = "https://api.freshmail.com/rest/some_endpoint"
    headers = {
        "Authorization": authorization
    }
    response = requests.get(url, headers=headers)
    return response.json()

def ping_get():
    url = "https://api.freshmail.com/rest/ping"
    headers = {
        "Authorization": authorization
    }
    response = requests.get(url, headers=headers)
    return response.json()

def ping_post(data):
    url = "https://api.freshmail.com/rest/ping"
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json"
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()

def get_subscriber_lists():
    url = "https://api.freshmail.com/rest/subscribers_list/lists"
    headers = {
        "Authorization": authorization
    }
    response = requests.get(url, headers=headers)
    return response.json()

def export_subscriber_list(list_id):
    url = "https://api.freshmail.com/rest/async_subscribers_list/export"
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json"
    }
    data = {
        "list": list_id,
        # Opcjonalnie można dodać 'state' i 'custom_fields'
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()

def check_export_status(job_id):
    url = "https://api.freshmail.com/rest/async_result/get"
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json"
    }
    data = {
        "id_job": job_id
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()

def get_export_results(job_id, part=1):
    url = "https://api.freshmail.com/rest/async_result/getFile"
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json"
    }
    data = {
        "id_job": job_id,
        "part": part
    }
    response = requests.post(url, headers=headers, json=data)
    
    if response.headers.get('Content-Type') == 'application/zip':
        return response.content
    else:
        return response.json()

def fetch_subscriber_list_zip(list_id, download_dir="downloaded_content"):
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    export_response = export_subscriber_list(list_id)
    job_id = export_response.get("data", {}).get("id_job")

    if not job_id:
        raise Exception("Failed to initiate export.")

    # Sprawdzanie statusu co 5 sekund
    while True:
        status_response = check_export_status(job_id)
        job_status = status_response.get("data", {}).get("job_status")
        if job_status == "2":  # '2' oznacza zakończony sukcesem
            break
        elif job_status == "3":  # '3' oznacza niepowodzenie
            raise Exception("Export failed.")
        elif job_status in ["0", "1"]:  # '0' oczekuje, '1' przetwarzanie
            print("Process is not finished yet. Waiting...")
        time.sleep(5)

    # Pobranie ilości części
    parts = int(status_response.get("data", {}).get("parts", 1))

    # Pobranie wszystkich części wyników
    files = []
    for part in range(1, parts + 1):
        file_content = get_export_results(job_id, part)
        file_name = os.path.join(download_dir, f"result_part_{part}.zip")
        with open(file_name, 'wb') as file:
            file.write(file_content)
        files.append(file_name)
    
    return files

### KONIEC SEKCJI API FRESHMAIL
### POCZĄTEK SEKCJI PRZETWARZANIA

def extract_zip_files(download_dir="downloaded_content", extract_to="extracted_files"):
    if not os.path.exists(extract_to):
        os.makedirs(extract_to)

    for file_name in os.listdir(download_dir):
        if file_name.endswith(".zip"):
            zip_path = os.path.join(download_dir, file_name)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
                print(f"Extracted {file_name} to {extract_to}")
            os.remove(zip_path)
            print(f"Deleted {file_name} from {download_dir}")

def save_records_to_file(records, filename="records.json"):
    with open(filename, 'w', encoding='utf-8') as file:
        json.dump(records, file, ensure_ascii=False, indent=4)

def load_records_from_file(filename="records.json"):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as file:
            return json.load(file)
    return {}

def process_csv_files(extracted_dir="extracted_files", json_file="records.json"):
    records = load_records_from_file(json_file)

    for file_name in os.listdir(extracted_dir):
        if file_name.endswith(".csv"):
            file_path = os.path.join(extracted_dir, file_name)
            with open(file_path, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file, delimiter=';')
                for row in reader:
                    email = row["Email"]
                    if email in records:
                        # Aktualizacja istniejącego rekordu
                        records[email]["Data dodania"] = row["Data dodania"]
                        records[email]["Data usunięcia"] = row["Data usunięcia"]
                        records[email]["Status"] = row["Status"]
                        records[email]["Powód rezygnacji"] = row["Powód rezygnacji"]
                    else:
                        # Dodanie nowego rekordu
                        records[email] = {
                            "Data dodania": row["Data dodania"],
                            "Data usunięcia": row["Data usunięcia"],
                            "Status": row["Status"],
                            "Powód rezygnacji": row["Powód rezygnacji"],
                            "Powiadomienie": 0
                        }
            # Usunięcie przetworzonego pliku CSV
            os.remove(file_path)
            print(f"Deleted {file_name} from {extracted_dir}")

    save_records_to_file(records, json_file)
    return records

def update_records_and_send_emails(json_file, smtp_settings):
    records = load_records_from_file(json_file)
    to_email = smtp_settings['to_email']
    from_email = smtp_settings['from_email']

    for email, data in records.items():
        if data["Powiadomienie"] == 0 and data["Status"] == "Aktywny":
            subject = "Zapis na newsletter!"
            message = f"Użytkownik {email} właśnie został dodany do listy mailingowej ({data['Data dodania']})."
            if send_email(smtp_settings['server'], smtp_settings['port'], smtp_settings['user'], smtp_settings['password'], from_email, to_email, subject, message):
                records[email]["Powiadomienie"] = 1
                print(f"Email sent to {to_email} about {email} at {datetime.now()}")

    save_records_to_file(records, json_file)

### KONIEC SEKCJI PRZETWARZANIA
### SMTP

def send_email(smtp_server, smtp_port, smtp_user, smtp_password, from_email, to_email, subject, message):
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(message, 'plain'))
    
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False


# Test funkcji ping_get
# result_get = ping_get()
# print("Ping GET result:", result_get)

# Test funkcji ping_post
# data = {"data": "pong"}  # Przykładowe dane
# result_post = ping_post(data)
# print("Ping POST result:", result_post)

# Test funkcji i wydrukowanie wyników
# lists = get_subscriber_lists()
# print("Subscriber Lists:", lists)

# Test funkcji i wydrukowanie wyników
# subscriber_list = fetch_subscriber_list(list_id)
# print("Subscriber List:", subscriber_list)

# Testowanie funkcji export_subscriber_list
# export_response = export_subscriber_list(list_id)
# print("Export Response:", export_response)

# Testowanie funkcji check_export_status
# job_id = xxx
# status_response = check_export_status(job_id)
# print("Status Response:", status_response)

# Testowanie funkcji get_export_results
# job_id = xxx
# result_file = get_export_results(job_id)
# print("Result File:", result_file)

# Wykonanie programu
result_file = fetch_subscriber_list_zip(list_id)
print("Result File:", result_file)
extract_zip_files()
records = process_csv_files()
print("Processed Records:", records)
smtp_settings = {
    'server': 'xxx', # PODAJ ADRES SERWERA
    'port': 587,
    'user': 'xxx', # PODAJ LOGIN
    'password': r'xxx', # PODAJ HASŁO
    'from_email': 'xxx',  # Adres e-mail nadawcy
    'to_email': 'xxx' # Adres e-mail odbiorcy
}

update_records_and_send_emails("records.json", smtp_settings)
