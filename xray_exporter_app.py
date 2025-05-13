import streamlit as st
import json
import pandas as pd
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

from typing import List, Tuple, Dict
from pathlib import Path
import csv
import io
import zipfile
import requests
import time
import re
import os
import base64
import shutil
from dotenv import load_dotenv

load_dotenv()  # Automatically loads variables from .env

JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")
XRAY_URL = os.getenv("XRAY_URL")
XRAY_ID = os.getenv("XRAY_ID")
XRAY_SECRET = os.getenv("XRAY_SECRET")
JIRA_HEADERS = headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

# Session state for caching
if "xray_token" not in st.session_state:
    st.session_state.xray_token = None
if "selected_keys" not in st.session_state:
    st.session_state.selected_keys=None
st.set_page_config(page_title="Xray Test Viewer & Exporter", layout="wide")
st.title("Xray Test Case Viewer and Exporter")

# --- Authentication Functions ---

def get_xray_token() -> str:
    """Retrieve or reuse Xray API token using client ID and secret."""
    if st.session_state.xray_token:
        return st.session_state.xray_token
    token = requests.post(
                            f"{XRAY_URL}/api/v2/authenticate",
                            headers={"Content-Type": "application/json"},
                            data=json.dumps({"client_id": XRAY_ID, "client_secret": XRAY_SECRET})
                        ).text.strip('"')
    st.session_state.xray_token = token
    return token

def get_jira_auth_headers() -> Dict[str, str]:
    """Return Jira headers with Basic Auth."""
    auth_string = f"{JIRA_EMAIL}:{JIRA_TOKEN}"
    auth_encoded = base64.b64encode(auth_string.encode()).decode()
    headers = JIRA_HEADERS.copy()
    headers["Authorization"] = f"Basic {auth_encoded}"
    return headers

# --- Data Processing Functions ---

def load_json_files(file_list: List[Path]) -> List[dict]:
    """Load JSON files and extract test data."""
    data = []
    for file in file_list:
        try:
            with open(file, "r", encoding="utf-8") as f:
                j = json.load(f)
                if isinstance(j, dict) and "tests" in j:
                    data.extend(j["tests"])
                else:
                    data.append(j)
        except Exception as e:
            st.warning(f"Could not load {file}: {e}")
    return data
    
def load_attachments_database(file_list: List[Path]) -> Dict[str, dict]:
    result = {}
    for file in file_list:
        try:
            with open(file, "r", encoding="utf-8") as f:
                j = json.load(f)
                result.update(j.get("attachment_metadata", {}))
        except Exception as e:
            st.warning(f"Could not load {file}: {e}")
    return result

def build_test_dataframe(tests: List[dict], jira_metadata: Dict) -> pd.DataFrame:
    """Build a DataFrame from test data for display."""
    test_records = []
    for test in tests:
        test_id = str(test.get("id", ""))
        meta = jira_metadata.get(test_id, {})
        test_key = meta.get("key")
        summary = meta.get("summary") or (test["steps"][0].get("action", "") if test.get("steps") else "")
        step_count = len(test.get("steps", []))
        preconds = ", ".join(test.get("preConditionTargetIssueIds", [])) if test.get("preConditionTargetIssueIds") else ""

        test_records.append({
            "Key": test_key,
            "Summary": summary,
            "Assignee": meta.get("assignee", ""),
            "Reporter": meta.get("reporter", ""),
            "Status": meta.get("status", ""),
            "Step Count": step_count,
            "Preconditions": preconds
        })
    return pd.DataFrame(test_records)

def strip_jira_wiki_markup(text):
    # Remove headings (e.g., h1. Heading)
    text = re.sub(r'h[1-6]\.\s*', '', text)
    # Bold and italic
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    # Monospace
    text = re.sub(r'\{\{(.*?)\}\}', r'\1', text)
    # Links: [label|url]
    text = re.sub(r'\[(.*?)\|(.*?)\]', r'\1', text)
    # Images: !image.jpg!
    text = re.sub(r'!(.*?)!', '', text)
    # Lists
    text = re.sub(r'^[\*#\-]+ ', '', text, flags=re.MULTILINE)
    # Line breaks (\n or \\)
    text = re.sub(r'\\\\', '\n', text)
    # Remove any residual brackets and cleanup
    text = re.sub(r'\[|\]', '', text)
    return text.strip()
    
def find_jira_by_summary(summary: str, description: str) -> List[str]:
    """Search Jira for issues matching summary and description."""
    # Escape quotes and handle description properly
    summary_escaped = summary.replace('"', '\\"')
    description_escaped = description.replace('"','\\"')
    description_escaped = strip_jira_wiki_markup(description)
    #jql= f'summary ~ "{summary_escaped}"'
    if description.strip():
        jql = f'summary ~ "{summary_escaped}" AND description ~ "{description_escaped}"'
    else:
        jql = f'summary ~ "{summary_escaped}" AND description IS EMPTY'

    url = f"{JIRA_URL}/rest/api/2/search"
    headers = get_jira_auth_headers()
    params = {
        "jql": jql,
        "maxResults": 50,
        "fields": "key"
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        issues = response.json().get("issues", [])
        return [issue["key"] for issue in issues]
    except requests.exceptions.RequestException as e:
        st.info(f"Error querying JIRA: {e}")
        return []
        
@st.fragment
def check_and_confirm_test_keys():
    automatic=st.checkbox("Skip manual verification of issue Keys",False)
    automaticWait=0
    if automatic:
        automaticWait=st.number_input("Delay between updates (may be zero)", 0,None,3)
        if 'Automatic_button_clicked' not in st.session_state:
            st.session_state.Automatic_button_clicked = False

        if not st.session_state.Automatic_button_clicked:
            if st.button("Start"):
                st.session_state.Automatic_button_clicked = True
            st.stop()  

    """Confirm or assign Jira keys for tests."""
    if "confirm_index" not in st.session_state:
        st.session_state.confirm_index = 0
    if "Confirmed" not in st.session_state:
        st.session_state.Confirmed = False
    index = st.session_state.confirm_index
    result = st.session_state.test_results
    if index >= len(result):
        if not st.session_state.Confirmed:
            st.session_state.Confirmed=True
            st.rerun()
        return

    test_data = result[index]
    current_key = test_data.get("key", "")
    fields = test_data.get("fields", {})
    summary = fields.get("summary", "")
    description = fields.get("description", "")

    if automatic:
        if current_key:
            response = requests.get(
                f"{JIRA_URL}/rest/api/2/issue/{current_key}",
                headers=get_jira_auth_headers()
            )
            if response.status_code == 200:
                st.info(f"✅ Existing key valid: {current_key}")
                st.session_state.confirm_index += 1
                time.sleep(automaticWait)
                st.rerun(scope="fragment")
                return
        matches = find_jira_by_summary(summary, description)
        if matches:
            test_data["key"] = matches[0]
            st.info(f"🔄 Automatically assigned matched key: {matches[0]}")
        else:
            project_prefix = current_key.split("-")[0] if "-" in current_key else ""
            test_data["key"] = ""
            if project_prefix:
                test_data["fields"]["project"] = {"key": project_prefix}
                st.warning(f"⚠️ No match. Will create new issue in project '{project_prefix}'")
            else:
                st.error("⚠️ No match and cannot detect project prefix. Issue might not be created.")
        result[index] = test_data  
        st.session_state.test_results = result  
        st.session_state.confirm_index += 1
        time.sleep(automaticWait)
        st.rerun(scope="fragment")
        return

    st.subheader(f"🧪 Test {index + 1}/{len(result)}")
    st.markdown(f"**Key:** {current_key}")
    st.markdown(f"**Summary:** {summary}")
    st.markdown(f"**Description:** {description}")
    if current_key:
        response = requests.get(
            f"{JIRA_URL}/rest/api/2/issue/{current_key}",
            headers=get_jira_auth_headers()
        )
        if response.status_code == 200:
            st.success(f"✅ Test key `{current_key}` exists in Jira.")
            st.markdown(f"[🔗 View in Jira]({JIRA_URL}/browse/{current_key})")
        else:
            st.info("🔍 Test key is missing or not found in Jira. Searching by summary/description...")
            matches = find_jira_by_summary(summary, description)

            if matches:
                match_key = matches[0]
                st.markdown(f"🔎 Found matching Jira issue: [{match_key}]({JIRA_URL}/browse/{match_key})")
                if st.button(f"✅ Accept and use {match_key}", key=f"accept_{index}"):
                    test_data["key"] = match_key
            else:
               st.warning("No Matching key found, assing the key manually or create new key")   
        manual_key = st.text_input("✏️ Enter to override/set Jira key manually (or leave empty)", key=f"manual_input_{index}").upper()
        if manual_key:
            check = requests.get(
                f"{JIRA_URL}/rest/api/2/issue/{manual_key}",
                headers=get_jira_auth_headers()
            )
            if check.status_code == 200:
                test_data["key"] = manual_key 
                st.success(f"✅ Valid Jira key set: {manual_key}")
            else:
                st.error("❌ This Jira key does not exist.")
                if st.button("➕ Proceed without key (create new)", key=f"create_new_{index}"):
                    project_prefix = current_key.split("-")[0] if "-" in current_key else ""
                    if not project_prefix:
                        st.error("❌ Cannot detect project prefix from current key. Please check the format.")
                    test_data["key"] = ""
                    test_data["fields"]["project"] = {"key": project_prefix}
                    st.success(f"🆕 New test will be created in project **{project_prefix}**")
             
        if st.button("Next", key=f"next_existing_{index}"):
            result[index] = test_data  
            st.session_state.test_results = result  
            st.session_state.confirm_index += 1
            st.rerun(scope="fragment")
    return

def extract_xray_attachment_ids(description_text: str) -> List[str]:
    """Extract Xray attachment IDs from text."""
    return re.findall(r"!xray-attachment://([a-f0-9\-]+)(?:\|[^!]*)?!", description_text)


def check_missing_attachments(
    data: List[dict],
    token: str,
    attachments_path: str,
) -> Dict[str, str]:
    status_container = st.empty()
    status_container.info("Checking missing attachments in xray online database")
    missing = {}
    for test in data:
        for step in test.get("steps", []):
            for field in ["action", "data", "result"]:
                field_value = step.get(field, "")
                ids = extract_xray_attachment_ids(field_value)
                for att_id in ids:
                    status_container.info(f"Checking: {att_id}")
                    url = f"{XRAY_URL}/api/v2/attachments/{att_id}"
                    headers = {"Authorization": f"Bearer {token}"}
                    response = requests.get(url, headers=headers)
                    if response.status_code == 401:
                        st.error("auth issue!!!!")
                        continue
                    elif response.status_code != 200:
                        missing[att_id] = f"Missing: {att_id}"
                        continue
                    else:
                        status_container.info(f"{att_id} exists")
    status_container.info("Attachments verified")           
    return missing

def upload_attachments_from_backup(missing_ids: List[str], token: str, backup_dir: str, attachments_database: Dict[str, dict]) -> Dict[str, str]:
    """Upload missing attachments from backup directory."""
    uploaded = {}
    url = f"{XRAY_URL}/api/v1/attachments"
    headers = {"Authorization": f"Bearer {token}"}
    status_container = st.empty()
    status_container.info("Uploading missing attachments")
    for old_id in missing_ids:
        # Rename/copy if metadata is available
        if old_id in attachments_database:
            new_name = attachments_database[old_id]["filename"]
            original_path = os.path.join(backup_dir, old_id)
            new_path = os.path.join(backup_dir, new_name)
            try:
                if os.path.exists(original_path):
                    
                    shutil.copyfile(original_path, new_path)
                    if os.path.exists(new_path):
                        with open(new_path, "rb") as f:
                            status_container.info(f"Uploading {old_id} as {new_name}...")
                            files = {"attachment": (new_name, f)}
                            response = requests.post(url, headers=headers, files=files)
                            if response.status_code == 200:
                                new_id = response.json().get("id")
                                uploaded[old_id] = new_id
                   
            except Exception as e:
                status_container.error(f"Error copying {old_id}: {e}")
        else:
            status_container.error(f"Error not exist {old_id} in {attachments_database}")
            
    status_container.success(f"Uploading attachments completed, uploaded {len(uploaded)} attachments")
    return uploaded

def update_attachments_with_new_ids(data: List[dict], uploaded_mapping: Dict[str, str]) -> List[dict]:
    """Update test data with new attachment IDs."""
    for test in data:
        for step in test.get("steps", []):
            for field in ["action", "data", "result"]:
                content = step.get(field, "")
                for old_id, new_id in uploaded_mapping.items():
                    content = content.replace(f"xray-attachment://{old_id}", f"xray-attachment://{new_id}")
                step[field] = content
    return data

def export_to_xray_format(
    selected_keys: List[str], 
    all_tests: List[dict], 
    jira_metadata: Dict, 
    flattened_datasets: List[dict], 
    flattened_testplans: List[dict], 
    flattened_testsets: List[dict]
) -> List[dict]:
    """Export selected tests to Xray format."""
    token = get_xray_token()
    exported = []
    dataset_per_test = {}

    key_to_id = {meta.get("key"): tid for tid, meta in jira_metadata.items() if meta.get("key")}
    id_to_test = {str(test.get("id")): test for test in all_tests if test.get("id") is not None}

    for key in selected_keys:
        test_id = key_to_id.get(key)
        if test_id and test_id in id_to_test:
            test = id_to_test[test_id]
            meta = jira_metadata.get(str(test_id), {})
            testtype = "Manual"
            if test.get("cucumber", ""):
                testtype = "Cucumber"
            elif test.get("generic", ""):
                testtype = "Generic"

            steps = [{"action": s.get("action", ""), "data": s.get("data", ""), "result": s.get("result", "")} for s in test.get("steps", [])]

            test_data = {
                "key": key,
                "type": test.get("type", ""),
                "generic": test.get("generic", ""),
                "cucumber": test.get("cucumber", ""),
                "cucumberType": test.get("cucumberType", ""),
                "id": test.get("id",""),
                "testVersionId": test.get("testVersionId",""),
                "fields": {
                    "summary": meta.get("summary", ""),
                    "description": meta.get("description", "")
                },
                "steps": steps,
                "xray_issue_type": meta.get("issuetype", ""),
                "xray_testtype": testtype
            }    

            pre_ids = test.get("preConditionTargetIssueIds", [])
            meta_preconditions = [jira_metadata.get(pre_id, {}) for pre_id in pre_ids]
            precondition_keys = [meta.get("key", "") for meta in meta_preconditions if "key" in meta]
            test_data["xray_preconditions"] = precondition_keys

            linked_testsets = [ds for ds in flattened_testsets if test_id in ds.get("tests", [])]
            linked_testsets_ids = [testset["id"] for testset in linked_testsets]
            meta_testsets = [jira_metadata.get(id, {}) for id in linked_testsets_ids]
            testsets_keys = [meta.get("key", "") for meta in meta_testsets if "key" in meta]
            if testsets_keys:
                test_data["xray_test_sets"] = testsets_keys

            exported.append(test_data)

    return exported

def prepare_zip_from_datasets(dataset_per_test: Dict[str, dict]) -> io.BytesIO:
    """Prepare a ZIP file containing dataset CSVs."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for key, dataset in dataset_per_test.items():
            parameters = dataset.get("parameters", [])
            rows = dataset.get("rows", [])
            column_titles = []
            param_id_to_col_name = {}
            for param in parameters:
                title = param["name"] + "*" if param.get("combinations") else param["name"]
                column_titles.append(title)
                param_id_to_col_name[param["_id"]] = title

            csv_rows = []
            for row in rows:
                values_dict = row.get("values", {})
                csv_row = {param_id_to_col_name[param_id]: values_dict.get(param_id, "") for param_id in values_dict}
                for col in column_titles:
                    csv_row.setdefault(col, "")
                csv_rows.append(csv_row)

            if csv_rows:
                df_csv = pd.DataFrame(csv_rows)
                csv_bytes = df_csv.to_csv(index=False).encode("utf-8")
                zip_file.writestr(f"dataset_{key}.csv", csv_bytes)
    zip_buffer.seek(0)
    return zip_buffer

def upload_to_xray(json_data: List[dict], api_url: str) -> Tuple[bool, str, str]:
    """Upload test data to Xray."""
    token = get_xray_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    response = requests.post(api_url, headers=headers, data=json.dumps(json_data))
    if response.status_code not in (200, 202):
        return False, f"Upload failed: {response.text}", None
    
    job_id = response.json().get("jobId")
    return True, "Upload submitted", job_id

def check_upload_status(job_id: str, token: str) -> Tuple[str, bool]:
    """Check the status of an Xray upload job."""
    status_url = f"{XRAY_URL}/api/v2/import/test/bulk/{job_id}/status"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(status_url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        status = data.get("status")
        if status == "successful":
            return "✅ Export Completed", True
        elif status == "failed":
            return f"❌ Export Failed: {data}", True
        elif status == "partially_successful":
            return f"Partially Successful: {data}", True
        elif status == "unsuccessful":
            return f"❌ Export unsuccessful: {data}", True
        else:
            return "⏳ Export Status: Still In Progress", False
    return "FATAL XRAY NOT RESPONDING", True

def generate_datasets(test_results, flattened_datasets):
    dataset_per_test = {}
    for test_data in test_results:
        key = test_data.get("key")
        test_id = test_data.get("id", "")
        test_version_id = test_data.get("testVersionId", "")
        linked_dataset = next(
            (
                ds for ds in flattened_datasets
                if str(ds.get("testIssueId")) in {test_id, test_version_id}
            ),
            None
        )

        if key and linked_dataset:
            dataset_per_test[key] = linked_dataset
    return dataset_per_test


# --- Streamlit UI ---

uploaded_dir = st.text_input("Enter path to directory containing all Xray JSON files")
uploaded_dir_attachments = st.text_input("Enter path to directory containing all attachments")

if uploaded_dir and uploaded_dir_attachments:
    base_path = Path(uploaded_dir)
    base_path_att = Path(uploaded_dir_attachments)
    test_files = list(base_path.glob("tests*.json"))
    dataset_files = list(base_path.glob("datasets*.json"))
    precondition_files = list(base_path.glob("preconditions*.json"))
    testplan_files = list(base_path.glob("testPlans*.json"))
    testrepo_files = list(base_path.glob("testRepository*.json"))
    history_files = list(base_path.glob("issueHistory*.json"))
    testsets_files = list(base_path.glob("testSets*.json"))
    attachment_files = list(base_path_att.glob("metadata_*.json"))
    
    tests = load_json_files(test_files)
    datasets = load_json_files(dataset_files)
    flattened_datasets = [ds for d in datasets if "datasets" in d for ds in d["datasets"]]
    preconditions = load_json_files(precondition_files)
    testplans = load_json_files(testplan_files)
    flattened_testplans = [tp for d in testplans if "testPlans" in d for tp in d["testPlans"]]
    testsets = load_json_files(testsets_files)
    flattened_testsets = [ts for d in testsets if "testSets" in d for ts in d["testSets"]]
    testrepos = load_json_files(testrepo_files)
    histories = load_json_files(history_files)
    
    attachments_db=load_attachments_database(attachment_files)
 

    metadata_file = base_path / "jira_lookup_cache.json"
    jira_metadata = {}
    if metadata_file.exists():
        with open(metadata_file, "r", encoding="utf-8") as f:
            jira_metadata = json.load(f)

    df = build_test_dataframe(tests, jira_metadata)

    with st.expander("🔍 Filter Options"):
        valid_keys = df["Key"].dropna().astype(str)
        if not valid_keys.empty:
            id_range = st.slider("Filter by index range", 0, len(valid_keys)-1, (0, len(valid_keys)-1))
            keyword = st.text_input("Search by keyword in summary")
            keyword_key = st.text_input("Search by key")
            filtered_df = df.iloc[id_range[0]:id_range[1]+1]
            if keyword:
                filtered_df = filtered_df[filtered_df["Summary"].str.contains(keyword, case=False, na=False)]
            if keyword_key:
                filtered_df = filtered_df[filtered_df["Key"].str.contains(keyword_key, case=False, na=False)]
            st.dataframe(filtered_df, use_container_width=True)
            selected_keys = st.multiselect("Select Test Keys to Export", options=filtered_df["Key"].tolist())

    result = []
    dataset_per_test = {}

    if selected_keys:
        if st.session_state.selected_keys!=selected_keys:
            st.session_state.confirm_index = 0
            st.session_state.Confirmed = False
            st.session_state.selected_keys=selected_keys
            st.session_state.Automatic_button_clicked =False
            result = export_to_xray_format(
                selected_keys, tests, jira_metadata, flattened_datasets, 
                flattened_testplans, flattened_testsets
            )
            st.session_state.test_results = result
            st.session_state.dataset_per_test =dataset_per_test
        

        check_and_confirm_test_keys()
        result = st.session_state.test_results
        if st.session_state.Confirmed:
            st.success("✅ All test keys prepared")
            token = get_xray_token()
            missing_attachments = check_missing_attachments(result, token,uploaded_dir_attachments)
            missing_attachments_ids = list(missing_attachments.keys())
            dataset_per_test=generate_datasets(result, flattened_datasets)
            
            with st.expander("⬆ Upload to Xray"):
                keys = [item.get("key") for item in result]
                st.text(", ".join(map(str, keys)))
                api_url = f"{XRAY_URL}/api/v2/import/test/bulk"
                if st.button("Upload Xray Data"):
                    
                    if missing_attachments_ids:
                        #st.info(f"Found {len(missing_attachments_ids)} missing attachments. Uploading from {uploaded_dir_attachments}...")
                        uploaded_mapping = upload_attachments_from_backup(missing_attachments_ids, token, uploaded_dir_attachments,attachments_db)
                        if uploaded_mapping:
                            #st.success(f"Uploaded {len(uploaded_mapping)} attachments.")
                            result = update_attachments_with_new_ids(result, uploaded_mapping)
                        else:
                            st.warning("No attachments were uploaded. Proceeding with original attachment IDs.")

                    success, message, job_id = upload_to_xray(result, api_url)
                    if success:
                        status_container = st.empty()
                        for _ in range(100):
                            status_msg, is_final = check_upload_status(job_id, token)
                            status_container.info(status_msg)
                            if is_final:
                                break
                            time.sleep(1)
                        updated_keys = [test.get("key") for test in result if test.get("key")]
                        if updated_keys:
                            key_links = " | ".join([f"[{key}]({JIRA_URL}/browse/{key})" for key in updated_keys])
                            st.markdown(f"**Updated Issues:** {key_links}")
                        else:
                            st.info("No valid Jira keys were confirmed.")
                    else:
                        st.error(message)

            if dataset_per_test:
                zip_buffer = prepare_zip_from_datasets(dataset_per_test)
                st.warning("Some tests contain datasets. You have to upload the datasets manually.")
                st.download_button(
                    "📥 Download Datasets (ZIP)",
                    data=zip_buffer,
                    file_name="xray_datasets.zip",
                    mime="application/zip"
                )
            with st.expander("⬆ Additional data (debug)"):
                st.download_button(
                    "📥 Download JSON Export",
                    data=json.dumps(result, indent=2),
                    file_name="xray_export.json",
                    mime="application/json"
                )
