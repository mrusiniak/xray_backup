# Xray Backup and Exporter

This repository contains two Python scripts designed to manage Xray test case backups and facilitate exporting test cases to another Xray instance. The scripts interact with Jira and Xray APIs to automate backup, metadata collection, and test case export processes.

## Overview

- **`xray_backup.py`**: Automates the backup of Xray test data and attachments, collects Jira issue metadata, and organizes the output into a structured ZIP file.
- **`xray_exporter_app.py`**: A Streamlit-based web application that allows users to view, filter, and export Xray test cases to another Xray instance, including handling attachments and datasets.

If you found this useful:
 
<a href="https://coff.ee/mrusiniak" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-blue.png" alt="Buy Me A Coffee" height="41" width="174"></a>

## Features

### xray_backup.py
- **Authentication**: Uses Jira and Xray API credentials stored in a `.env` file for secure access.
- **Backup Triggering**: Initiates Xray backups with options for including attachments and filtering by project or modification date.
- **Backup Monitoring**: Polls the backup job status until completion and downloads the resulting ZIP files.
- **Metadata Collection**: Extracts Jira issue IDs from backup files and fetches corresponding metadata (e.g., summary, status, assignee) from Jira.
- **File Management**: Extracts backups, adds metadata to the ZIP file, and cleans up temporary files.
- **Output**: Produces a ZIP file containing Xray test data and a JSON file with Jira metadata.

### xray_exporter_app.py
- **Streamlit Interface**: Provides a user-friendly web UI for viewing and managing Xray test cases.
- **Data Loading**: Loads JSON files from a specified directory containing Xray test data, datasets, test plans, test sets, and attachments metadata.
- **Test Case Filtering**: Allows filtering by index range, summary keywords, or Jira keys, with a tabular display of test case details.
- **Key Verification**: Validates or assigns Jira issue keys for test cases, with options for manual input or automatic matching based on summary and description.
- **Attachment Handling**: Checks for missing attachments in the target Xray instance and uploads them from a backup directory.
- **Export to Xray**: Formats selected test cases into Xray-compatible JSON and uploads them to a specified Xray instance.
- **Dataset Support**: Generates downloadable ZIP files containing CSV datasets for tests with associated datasets. due to limitation of XRAY datasets cannot be uploaded by JSON. you need to import them manually. the csv are named using JIRA issue key to make it easier
- **Debugging**: Offers JSON export of test data for troubleshooting. this JSON can be also used in XRAY test case importer

## Prerequisites

- **Python**: Version 3.8 or higher.
- **Dependencies**: Install required packages using:
  ```bash
  pip install -r requirements.txt
  ```
- **Environment Variables**: Create a `.env` file in the project root with the following variables:
  ```plaintext
  JIRA_URL=https://your-jira-instance
  JIRA_EMAIL=your-email
  JIRA_TOKEN=your-jira-api-token
  XRAY_URL=https://your-xray-instance
  XRAY_ID=your-xray-client-id
  XRAY_SECRET=your-xray-client-secret
  ```
- **Jira and Xray Access**: Valid API credentials for both Jira and Xray.
- **Directory Setup**: Ensure directories for backups and attachments exist and are accessible.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/xray-backup-exporter.git
   cd xray-backup-exporter
   ```
2. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Set up the `.env` file with your credentials.
5. Ensure the output directories specified in `xray_backup.py` (e.g., `h:/`, `c:/ps/temp-xray`) are accessible.

## Usage

### xray_backup.py
1. Run the script to generate a backup:
   ```bash
   python xray_backup.py
   ```
2. The script will:
   - Authenticate with Xray and trigger a backup.
   - Download the backup ZIP files (test data and attachments).
   - Extract test data and collect Jira issue IDs.
   - Fetch metadata from Jira and save it to `jira_lookup_cache.json`.
   - Add metadata to the backup ZIP and clean up temporary files.
3. Output files are saved to the directory specified in `OUTPUT_DIR` (e.g., `h:/XRAY-YYYY-MM-DD.zip`).

### xray_exporter_app.py
1. Launch the Streamlit app:
   ```bash
   streamlit run xray_exporter_app.py
   ```
2. Open the provided URL (e.g., `http://localhost:8501`) in a web browser.
3. In the UI:
   - Enter the paths to the directories containing Xray JSON files and attachments.
   - Filter test cases using sliders, keyword search, or key search.
   - Select test cases to export using the multiselect widget.
   - Verify or assign Jira keys for each test case (manually or automatically).
   - Upload test cases to Xray, including any missing attachments.
   - Download datasets as a ZIP file if applicable. Datasets cannot be unfortunately submited by API you need to import them manually - they are named with proper key. 
   - optionally download the JSON export for debugging. this json can also be used in XRAY test case importer.
4. Monitor the upload status in the UI, with links to updated Jira issues upon completion.

```

## Notes

- **Security**: Keep the `.env` file secure and do not commit it to version control. Use `.gitignore` to exclude it.
- **Error Handling**: Both scripts include error handling for API failures, file issues, and JSON parsing errors. Check console output or Streamlit UI for detailed error messages.
- **Performance**: The backup script may take time for large projects due to API polling and metadata fetching. The exporter app processes data in batches to handle large datasets.
- **Limitations**:
  - The backup script assumes the output directories are writable and have sufficient space.
  - The exporter app requires a stable internet connection for API calls and may need manual intervention for key assignment if automatic matching fails.
- **Customization**: Modify directory paths, batch sizes, or API endpoints in the scripts as needed for your environment.

## Contributing

Contributions are welcome! Please follow these steps:
1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/your-feature`).
3. Commit your changes (`git commit -m "Add your feature"`).
4. Push to the branch (`git push origin feature/your-feature`).
5. Open a pull request with a description of your changes.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Contact

For questions or issues, please open an issue on GitHub or contact the repository maintainer.
