# -----------------------------------------------------------------------------
# File: xray_backup.py
#
# Copyright (c) 2025 BESA GmbH
#
# Author: Mateusz Rusinak
#
# This file is part of the Xray Test Case Viewer and Exporter.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# -----------------------------------------------------------------------------

import os
import json
import requests
import base64
from pathlib import Path
from typing import Dict, Set, List
import time
import zipfile
from datetime import datetime
from dotenv import load_dotenv


# === CONFIGURATION ===
load_dotenv()  # Automatically loads variables from .env

JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")
XRAY_URL = os.getenv("XRAY_URL")
XRAY_ID = os.getenv("XRAY_ID")
XRAY_SECRET = os.getenv("XRAY_SECRET")

OUTPUT_DIR = Path("h:/")
BACKUP_CACHE_FILE = Path("last_backup.json")
BAKCUP_DIR = f"c:/ps/temp-xray"
BAKCUP_DIR_ATTACHMENT = f"c:/ps/temp-xray-attachment"

def get_auth_header(email: str, api_token: str) -> Dict[str, str]:
    auth_str = f"{email}:{api_token}"
    b64_encoded = base64.b64encode(auth_str.encode()).decode()
    return {
        "Authorization": f"Basic {b64_encoded}",
        "Content-Type": "application/json"
    }

def get_xray_token() -> str:
    response =requests.post(
                            f"{XRAY_URL}/api/v2/authenticate",
                            headers={"Content-Type": "application/json"},
                            data=json.dumps({"client_id": XRAY_ID, "client_secret": XRAY_SECRET})
                        )
    
    if response.status_code == 200:
        return response.text.strip('"')
    else:
        raise Exception(f"Failed to authenticate with Xray: {response.status_code}, {response.text}")

def trigger_backup(token: str, project_ids=None, with_attachment=True, modified_since=None) -> str:
    url = f"{XRAY_URL}/api/v2/backup"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "withAttachment": with_attachment
    }
    if project_ids:
        payload["projectIds"] = project_ids
    if modified_since:
        payload["modifiedSince"] = modified_since

    response = requests.post(url, headers=headers, json=payload)
    #response.raise_for_status()
    return response

def wait_for_backup(token: str, job_id: str, poll_interval=30) -> dict:
    status_url = f"{XRAY_URL}/api/v2/backup/{job_id}/status"
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"Waiting for backup job {job_id} to complete...")
    while True:
        response = requests.get(status_url, headers=headers)
        response.raise_for_status()
        result = response.json()
        status = result.get("status")
        if status == "successful":
            print("Backup completed.")
            return result
        elif status == "working":
            print(f"Progress: {result.get('progressValue', '?')} - waiting...")
            time.sleep(poll_interval)
        else:
            raise Exception(f"Unexpected backup status: {status}")

def download_file(url: str, token: str, dest_path: Path):
    headers = {"Authorization": f"Bearer {token}"}
    with requests.get(url, headers=headers, stream=True) as r:
        r.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print(f"Downloaded: {dest_path}")

def extract_zip(zip_path: Path, extract_to: Path):
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
    print(f"Extracted to: {extract_to}")

def run_backup_flow():
    today_str = datetime.now().strftime("%Y-%m-%d")
    base_zip = OUTPUT_DIR / f"XRAY-{today_str}.zip"
    attachment_zip = OUTPUT_DIR / f"XRAY-{today_str}-attachment.zip"

    token = get_xray_token()
    response = trigger_backup(token, with_attachment=True)
    if response.json().get("jobId",""):
        result = wait_for_backup(token, response.json()["jobId"])
    else:
        print(f"!!!! Backup generation failed - maybe there is already backup to download? Let's try!")

    #file_url = result.get("fileUrl")
    #attachment_url = result.get("attachmentUrl")
    url = f"{XRAY_URL}/api/v2/backup/file"
    download_file(url,token, base_zip)
    url = f"{XRAY_URL}/api/v2/backup/file/attachment"
    download_file(url, token, attachment_zip)

    extract_zip(base_zip, BAKCUP_DIR)



def collect_jira_ids(base_dir: Path) -> Set[str]:
    ids = set()
    patterns = ["tests*.json", "preconditions*.json", "testplans*.json", "testsets*.json"]
    for pattern in patterns:
        for file in base_dir.glob(pattern):
            print(f"Scanning file: {file.name}")
            with open(file, 'r', encoding='utf-8') as f:
                content = json.load(f)
                items = content.get('tests') or content.get('preconditions') or content.get('testPlans') or content.get('testSets') or []
                for item in items:
                    internal_id = item.get("id")
                    if internal_id:
                        ids.add(str(internal_id))
    return ids


def fetch_jira_metadata(jira_url: str, email: str, api_token: str, ids: Set[str]) -> Dict[str, dict]:
    metadata = {}
    id_list = [int(x) for x in ids if x.isdigit()]
    batch_size = 50
    total_batches = (len(id_list) + batch_size - 1) // batch_size

    for i in range(0, len(id_list), batch_size):
        batch = id_list[i:i+batch_size]
        batch_number = (i // batch_size) + 1
        print(f"Fetching batch {batch_number}/{total_batches} ({len(batch)} issues)...")

        search_url = f"{jira_url}/rest/api/2/search"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        jql = f"id in ({', '.join(str(b) for b in batch)})"
        params = {
            "jql": jql,
            "fields": "key,summary,description,status,assignee,reporter,issuelinks,issuetype,comments"
        }

        try:
            response = requests.get(search_url, headers=headers, auth=(email, api_token), params=params)
            if response.status_code == 200:
                try:
                    data = response.json()
                    for issue in data.get("issues", []):
                        issue_id = issue.get("id")
                        fields = issue.get("fields", {})
                       # issuelinks = fields.get("issuelinks",{}) if isinstance(fields.get("issuelinks",{}), list) else []
                        metadata[str(issue_id)] = {
                            "key": issue.get("key", ""),
                            "summary": fields.get("summary", ""),
                            "description": fields.get("description", ""),
                            "status": fields.get("status", {}).get("name", ""),
                            "assignee": (fields.get("assignee") or {}).get("displayName", ""),
                            "reporter": (fields.get("reporter") or {}).get("displayName", ""),
                            "links": fields.get("issuelinks",{}),
                            "issuetype": fields.get("issuetype",{}).get("name",""),
                            "comments": fields.get("comment",{}).get("comments")
                        }
                    
                except Exception as json_err:
                    print(f"Failed to parse JSON in batch {batch_number}, issue: {issue_id}: {json_err}")
                    #print(f"🔎 Raw response: {response.text}")
                    
            else:
                print(f"Failed batch {batch_number}: {response.status_code}")
                print(f"Response content: {response.text}")
        except Exception as e:
            print(f"Error fetching batch {batch_number}: {e}")
            time.sleep(10)
    return metadata
    




def save_metadata(metadata: Dict[str, dict], output_path: Path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"Metadata saved to {output_path}")


def cleanup(backup_dir: str,today_str: str,metadata_file:str):
    for folder in [backup_dir, OUTPUT_DIR / f"{today_str}-attachment"]:
        if folder.exists() and folder.is_dir():
            for child in folder.rglob("*"):
                if child.is_file():
                    child.unlink()
                else:
                    child.rmdir()
            folder.rmdir()
            print(f"Removed folder: {folder}")
    cache_file = Path(metadata_file)
    if cache_file.exists():
        cache_file.unlink()
        print("Deleted jira_lookup_cache.json")
        
def main():
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    metadata_file = Path("c:/ps/jira_lookup_cache.json")
    base_zip = OUTPUT_DIR / f"XRAY-{today_str}.zip"  # <-- NEW
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if base_zip.exists():
        print(f"Backup for today already exists at {base_zip}, skipping download.")
    else:
        print("Downloading latest Xray backups...")
        run_backup_flow()

    if not Path(BAKCUP_DIR).exists():
        print(f"Xray backup directory not found after download: {BAKCUP_DIR}")
        return

    print("Collecting Jira issue IDs from backup...")
    jira_ids = collect_jira_ids(Path(BAKCUP_DIR))
    print(f"Collected {len(jira_ids)} issue IDs from backup")

    print("Fetching metadata from Jira...")
    metadata = fetch_jira_metadata(JIRA_URL, JIRA_EMAIL, JIRA_TOKEN, jira_ids)

    print("Saving metadata to file...")
    save_metadata(metadata, metadata_file)
    
    print(f"Adding metadata to ZIP: {base_zip}")
    with zipfile.ZipFile(base_zip, 'a', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(metadata_file, arcname=metadata_file.name)
        
    print(f"Cleaning up extracted folders...")
    cleanup(Path(BAKCUP_DIR),today_str,metadata_file)
        
    print("Done.")


if __name__ == "__main__":
    main()
