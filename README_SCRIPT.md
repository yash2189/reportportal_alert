# Report Portal Alert Script

This Python script interacts with the Report Portal API to fetch and analyze test execution launches. It provides various output formats and filtering capabilities to help monitor and analyze test results.

## Features

- Fetch launches from Report Portal with advanced filtering
- Multiple output formats:
  - Table format (default)
  - JSON format
  - HTML Report with detailed launch information
- Attribute-based filtering
- Caching support to improve performance
- Configurable through environment variables or config file

## Prerequisites

- Python 3.6 or higher
- Required Python packages (install via pip):
  - requests
  - tabulate
  - jinja2 (for HTML reports)

## Configuration

The script can be configured in two ways:
1. Using a `.report-portal-config.json` file
2. Using environment variables

### Config File Structure
```json
{
    "base_url": "https://your-reportportal-instance",
    "token": "your-api-token",
    "username": "your-username",
    "password": "your-password"
}
```

## Usage

Basic usage:
```bash
python report_alert.py --project PROJECT_NAME
```

With filters:
```bash
python report_alert.py --project PROJECT_NAME --attributes "key1=value1" "key2=value2"
```

Generate HTML report:
```bash
python report_alert.py --project PROJECT_NAME --output html
```

### Command Line Arguments

- `--project`: (Required) Project name in Report Portal
- `--output`: Output format (table, json, or html)
- `--attributes`: Filter launches by attributes (KEY=VALUE format)
- `--page-size`: Number of launches to fetch per page
- `--no-cache`: Disable caching
- `--clear-cache`: Clear existing cache
- `--config`: Path to config file

## Output Formats

1. Table Format (Default)
   - Displays launches in a formatted table
   - Shows key information like name, status, and attributes

2. JSON Format
   - Outputs raw JSON data
   - Useful for programmatic processing

3. HTML Report
   - Creates a detailed HTML report
   - Includes launch statistics and detailed information
   - Interactive table with sorting capabilities

## Caching

The script implements caching to improve performance:
- Cache duration: 24 hours by default
- Cache location: `~/.report_portal_cache`
- Use `--no-cache` to bypass cache
- Use `--clear-cache` to clear existing cache
