import argparse
import json
import os
import requests
import logging
from typing import Dict, List, Optional, Any
from tabulate import tabulate
from datetime import datetime, timedelta
import shelve
import hashlib
import time
from pathlib import Path
import datetime
import csv

class ReportPortalClient:
    """
    A wrapper client for interacting with Report Portal Server API with advanced attribute filtering
    """
    

    def __init__(self, base_url: str, token: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None):
        """
        Initialize the Report Portal client
        
        :param base_url: Base URL of the Report Portal server
        :param username: User's username for authentication
        :param password: User's password for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.username = username
        self.password = password
        
        # Configure logging
        logging.basicConfig(level=logging.INFO, 
                            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
    
    def authenticate(self) -> bool:
        """
        Authenticate with the Report Portal server and obtain an access token if not already set
        
        :return: Boolean indicating successful authentication
        """
        if self.token:
            self.logger.info("Using pre-obtained token for authentication")
            return True
        
        if not (self.username and self.password):
            self.logger.error("Missing credentials for authentication")
            return False
        
        try:
            auth_endpoint = f"{self.base_url}/uat/sso/oauth/token"
            
            payload = {
                'grant_type': 'password',
                'username': self.username,
                'password': self.password
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            }
            
            response = requests.post(
                auth_endpoint, 
                data=payload, 
                headers=headers, 
                auth=('ui', 'uiman')
            )
            
            response.raise_for_status()
            
            auth_data = response.json()
            self.token = auth_data.get('access_token')
            
            self.logger.info("Successfully authenticated with Report Portal")
            return True
        
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Authentication failed: {e}")
            return False
    
    def fetch_launches(self, 
                       project_name: str, 
                       page_num: int = 1, 
                       page_size: int = 50, 
                       filter_options: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """
        Fetch launches for a specific project with advanced filtering options
        
        :param project_name: Name of the project to fetch launches from
        :param page_num: Page number for pagination
        :param page_size: Number of launches per page
        :param filter_options: Dictionary of filter criteria-
        :return: List of launch details
        """
        if not self.token:
            if not self.authenticate():
                raise ValueError("Authentication failed")
        
        try:
            launches_endpoint = f"{self.base_url}/api/v1/{project_name}/launch"
            
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/json'
            }
            
            # Prepare query parameters
            params = {
                'page.page': page_num,
                'page.size': page_size,
                'page.sort': 'startTime,DESC'  # Sort by most recent first
            }
            
            # Add filtering parameters
            if filter_options:    
                # Status filter

                if 'status' in filter_options:
                    if "FAILED" in filter_options['status']:
                        params['filter.gte.statistics$executions$failed'] = 1
                    elif "PASSED" in filter_options['status']:
                        params['filter.eq.statistics$executions$failed'] = 0
                
                # Start time range filters
                if 'start_time_from' in filter_options:
                    params['filter.gt.startTime'] = filter_options['start_time_from']
                 
                if 'start_time_to' in filter_options:
                    params['filter.lt.startTime'] = filter_options['start_time_to']
                
                # Tags filter
                if 'tags' in filter_options:
                    # For multiple tags, convert to comma-separated string
                    tags = filter_options['tags']
                    if isinstance(tags, list):
                        tags = ','.join(tags)
                    params['filter.has.tags'] = tags
                
                # Attribute filters
                if 'attributes' in filter_options:
                    attributes = filter_options['attributes']
                    for i, (key, value) in enumerate(attributes.items(), 1):
                        # Support exact match and partial match
                        params[f'filter.has.compositeAttribute'] = f"{key}:{value}"
                # Name filter
                if 'name' in filter_options:
                    params['filter.!cnt.name'] = filter_options['name']
            response = requests.get(
                launches_endpoint, 
                headers=headers, 
                params=params
            )
            self.logger.info(response.request.url)
            response.raise_for_status()
            
            launches_data = response.json()
            
            self.logger.info(f"Successfully fetched {len(launches_data.get('content', []))} launches")
            return launches_data.get('content', [])
        
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to fetch launches: {e}")
            return []
    
    def fetch_failed_test_cases(self, 
                              project_name: str, 
                              launch_id: str = None,
                              launch_name: str = None, 
                              page_num: int = 1,
                              page_size: int = 50,
                              filter_options: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
        """
        Fetch all failed test cases with IDs and URLs for specific launch(es).
        Uses fetch_launches to get launches based on provided filters.
        
        :param project_name: Name of the project
        :param launch_id: Optional ID of the specific launch. If not provided, fetches launches based on filters
        :param page_num: Page number for launch pagination
        :param page_size: Number of launches per page
        :param filter_options: Dictionary of filter criteria for launches (start_time, attributes, etc.)
        :return: List of dictionaries containing test case details including suite information
        """
        if not self.token and not self.authenticate():
            raise ValueError("Authentication failed")
        
        failed_tests = []
        try:
            # If no specific launch_id provided, get launches based on filters
            launches_to_check = []
            if launch_id:
                launches_to_check = [{'id': launch_id, 'name': launch_name}]
            else:
                # Ensure we're only getting failed launches
                if filter_options is None:
                    filter_options = {}
                filter_options['status'] = 'FAILED'
                
                # Get launches based on all provided filters
                launches_to_check = self.fetch_launches(
                    project_name=project_name,
                    page_num=page_num,
                    page_size=page_size,
                    filter_options=filter_options
                )
                
                if not launches_to_check:
                    self.logger.info("No failed launches found matching the filter criteria")
                    return []
            
            # Process each launch
            for launch in launches_to_check:   
                current_launch_id = launch['id']
                launch_name = launch.get('name', 'Unknown Launch')
                self.logger.info(f"Processing failed tests for launch {launch_name} (ID: {current_launch_id})")
                
                # Get all test suites for this launch
                suites_endpoint = f"{self.base_url}/api/v1/{project_name}/item"
                headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
                suite_params = {
                    'filter.eq.launchId': current_launch_id,
                    'filter.eq.type': 'SUITE',
                    'page.size': 100
                }
                
                suites_response = requests.get(suites_endpoint, headers=headers, params=suite_params)
                suites_response.raise_for_status()
                suites_data = suites_response.json()
                # Iterate through each suite
                for suite in suites_data.get('content', []):
                    suite_id = suite.get('id')
                    suite_name = suite.get('name', 'Unknown Suite')
                    
                    # Get failed tests for this suite
                    test_params = {
                        'filter.eq.launchId': current_launch_id,
                        'filter.eq.parentId': suite_id,
                        'filter.in.status': 'FAILED',
                        'page.size': 100
                    }
                    if 'test_name' in filter_options:
                        test_params['filter.cnt.name'] = filter_options['test_name']
                    tests_response = requests.get(suites_endpoint, headers=headers, params=test_params)
                    tests_response.raise_for_status()
                    tests_data = tests_response.json()
                    
                    if tests_data.get('content'):
                        self.logger.info(f"For Test Suite {suite_name}:")
                        # Add failed tests with suite and launch information
                        for test in tests_data.get('content', []):
                            failed_tests.append({
                                'id': test.get('id'),
                                'name': test.get('name'),
                                'suite_name': suite_name,
                                'suite_id': suite_id,
                                'launch_id': current_launch_id,
                                'launch_name': launch_name,
                                'status': test.get('status'),
                                'url': f"{self.base_url}/ui/#{project_name}/launches/-1/{current_launch_id}/{suite_id}/{test.get('id')}/log",
                                'start_time': test.get('startTime'),
                                'end_time': test.get('endTime'),
                                'description': test.get('description', '')
                            })
                            self.logger.info(f"Test Case ID: {test.get('id')} - {test.get('status')}")
            
            if 'test_name' in filter_options:
                self.logger.info(f"Found {len(failed_tests)} failed tests across {len(launches_to_check)} launches for test name {filter_options['test_name']}") 
            else:
                self.logger.info(f"Found {len(failed_tests)} failed tests across {len(launches_to_check)} launches")
            return failed_tests
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to fetch test cases: {e}")
            return []
    
    def __repr__(self):
        return f"ReportPortalClient(base_url={self.base_url}, username={self.username})"

def get_cache_key(project: str, args: argparse.Namespace, filter_options: Dict) -> str:
    """Generate a unique cache key based on CLI arguments and filters"""
    # Create a string representation of all relevant parameters
    key_parts = [
        project,
        str(args.page),
        str(args.limit),
        str(filter_options)
    ]
    if hasattr(args, 'failed_tests'):
        key_parts.append(str(args.failed_tests))
    
    # Create a hash of the parameters
    key_string = '_'.join(key_parts)
    return hashlib.md5(key_string.encode()).hexdigest()

def get_cache_path() -> Path:
    """Get the cache directory path"""
    cache_dir = Path.home() / '.reportportal_cache'
    cache_dir.mkdir(exist_ok=True)
    return cache_dir / 'rp_cache'

def clear_cache():
    """Clear the entire cache"""
    cache_path = get_cache_path()
    if cache_path.exists():
        with shelve.open(str(cache_path)) as cache:
            cache.clear()

def get_cached_data(cache_key: str, max_age_hours: int = 24):
    """Retrieve cached data if it exists and is not expired"""
    with shelve.open(str(get_cache_path())) as cache:
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            # Check if cache is expired (default 24 hours)
            if time.time() - timestamp < max_age_hours * 3600:
                return data
    return None

def cache_data(cache_key: str, data):
    """Cache the data with current timestamp"""
    with shelve.open(str(get_cache_path())) as cache:
        cache[cache_key] = (data, time.time())

def parse_config() -> Dict[str, str]:
    """
    Parse configuration from environment variables or config file
    
    :return: Dictionary of configuration parameters
    """
    config = {}
    
    # Check environment variables
    config['base_url'] = os.environ.get('REPORT_PORTAL_URL')
    config['username'] = os.environ.get('REPORT_PORTAL_USERNAME')
    config['password'] = os.environ.get('REPORT_PORTAL_PASSWORD')
    config['token'] = os.environ.get('REPORT_PORTAL_TOKEN')
    
    # If config is missing, try config file
    config_file_path = os.path.expanduser('.report-portal-config.json')
    if not any(config.values()) and os.path.exists(config_file_path):
        try:
            with open(config_file_path, 'r') as config_file:
                file_config = json.load(config_file)
                for key in ['base_url', 'username', 'password', 'token']:
                    if not config.get(key):
                        config[key] = file_config.get(key)
        except json.JSONDecodeError:
            pass
    
    # Validate configuration
    if not config.get('base_url'):
        raise ValueError("Missing Report Portal URL in configuration.")
    
    if not config.get('token') and not (config.get('username') and config.get('password')):
        raise ValueError("""
        Missing authentication credentials. Provide either:
        1. An access token via:
           - Environment variable: REPORT_PORTAL_TOKEN
           - Config file with key: "token"
        2. OR username and password via:
           - Environment variables: REPORT_PORTAL_USERNAME, REPORT_PORTAL_PASSWORD
           - Config file with keys: "username", "password"
        """)
    
    return config

def create_cli_parser() -> argparse.ArgumentParser:
    """
    Create CLI argument parser
    
    :return: Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(description='Report Portal Launch Retrieval Tool')
    
    # Required arguments
    parser.add_argument('project', 
                        help='Report Portal project name')
    parser.add_argument('--token', help='Authentication token')
    # Optional filtering arguments
    parser.add_argument('-n', '--name', 
                        help='Filter launches by name (partial match)')
    
    parser.add_argument('-s', '--status', 
                        nargs='+', 
                        choices=['PASSED', 'FAILED', 'STOPPED', 'INTERRUPTED', 'IN_PROGRESS'],
                        help='Filter launches by status (multiple statuses allowed)')
    
    parser.add_argument('-t', '--tags', 
                        nargs='+', 
                        help='Filter launches by tags')
    
    parser.add_argument('--start-from', 
                        help='Fetch launches from this date (YYYY-MM-DD)')
    
    parser.add_argument('--start-to', 
                        help='Fetch launches up to this date (YYYY-MM-DD)')
    
    # Attribute filtering
    parser.add_argument('--attr', 
                        nargs='+', 
                        help='Filter by attributes in KEY=VALUE format. '
                             'Multiple attributes can be specified.')
    
    # Pagination and output arguments
    parser.add_argument('-p', '--page', 
                        type=int, 
                        default=1, 
                        help='Page number (default: 1)')
    
    parser.add_argument('-l', '--limit', 
                        type=int, 
                        default=50, 
                        help='Number of launches per page (default: 50)')
    
    parser.add_argument('-o', '--output', 
                        choices=['json', 'table', 'summary', 'detailed', 'csv'], 
                        default='table', 
                        help='Output format (default: table)')
    parser.add_argument('--failed-tests', action='store_true', help='Fetch failed test cases with links from launches')  # Added CLI argument
    parser.add_argument('-tn', '--test-name', 
                        help='Filter launches by test name (partial match)')
    
    # Cache management
    parser.add_argument('--reset-cache', action='store_true', help='Clear the cache and fetch fresh data')
    parser.add_argument('--cache-hours', type=int, default=24, help='Cache expiry time in hours (default: 24)')
    
    return parser

def parse_attributes(attr_args: Optional[List[str]]) -> Dict[str, str]:
    """
    Parse attribute arguments into a dictionary
    
    :param attr_args: List of attribute arguments in KEY=VALUE format
    :return: Dictionary of attributes
    """
    if not attr_args:
        return {}
    
    attributes = {}
    for attr in attr_args:
        try:
            key, value = attr.split('=', 1)
            attributes[key] = value
        except ValueError:
            raise ValueError(f"Invalid attribute format: {attr}. Use KEY=VALUE")
    
    return attributes

def format_output(launches: List[Dict], output_format: str, project_name: Optional[str] = None):
    """
    Format and print launches based on output format
    
    :param launches: List of launch dictionaries
    :param output_format: Output format
    :param project_name: Project name for generating launch URLs
    """
    status_summary = {}
    
    if output_format == 'json':
        print(json.dumps(launches, indent=2))
    elif output_format == 'table':
        headers = ["Launch ID", "Launch Name", "Status", "Start Time", "Failed Tests", "Link to Launch"]
        rows = []
        
        for launch in launches:
            status = launch.get('status', 'UNKNOWN')
            status_summary[status] = status_summary.get(status, 0) + 1
            start_time = convert_timestamp_to_human_readable(launch.get('startTime'))
            
            # Generate launch URL
            url = f"{parse_config()['base_url']}/ui/#{project_name}/launches/{launch.get('id')}"
            
            rows.append([
                launch.get('id', ''),
                launch.get('name', 'Unknown'),
                status,
                start_time,
                launch.get('statistics', {}).get('executions', {}).get('failed', 0),
                url
            ])
        
        print("\nFailed Launches:")
        print(tabulate(rows, headers=headers, tablefmt='grid'))
        
        print("\nStatus Summary:")
        for status, count in status_summary.items():
            print(f"{status}: {count}")
    elif output_format == 'csv':
        with open('launches.csv', 'w', newline='') as csvfile:
            csvwriter = csv.writer(csvfile)
            csvwriter.writerow(["Launch ID", "Launch Name", "Status", "Start Time", "Failed Tests", "Link to Launch"])
            for launch in launches:
                status = launch.get('status', 'UNKNOWN')
                start_time = convert_timestamp_to_human_readable(launch.get('startTime'))
                url = f"{parse_config()['base_url']}/ui/#{project_name}/launches/{launch.get('id')}"
                csvwriter.writerow([
                    launch.get('id', ''),
                    launch.get('name', 'Unknown'),
                    status,
                    start_time,
                    launch.get('statistics', {}).get('executions', {}).get('failed', 0),
                    url
                ])
        print("CSV file 'launches.csv' has been created.")
    
    elif output_format == 'detailed':
        for launch in launches:
            print("\n--- Launch Details ---")
            print(f"ID: {launch.get('id', 'N/A')}")
            print(f"Name: {launch.get('name', 'N/A')}")
            print(f"Status: {launch.get('status', 'N/A')}")
            print(f"Start Time: {launch.get('startTime', 'N/A')}")
            print(f"Tags: {', '.join(launch.get('tags', []))}")
            
            # Print attributes
            attributes = launch.get('attributes', [])
            if attributes:
                print("\nAttributes:")
                for attr in attributes:
                    print(f"  {attr.get('key', 'N/A')}: {attr.get('value', 'N/A')}")

def convert_timestamp_to_human_readable(timestamp):
    """Converts a Unix timestamp (in milliseconds) to a human-readable format.

    Args:
        timestamp: The Unix timestamp in milliseconds.

    Returns:
        A string representing the human-readable date and time.
    """

    dt_object = datetime.datetime.fromtimestamp(timestamp / 1000)  # Convert to seconds
    formatted_time = dt_object.strftime('%Y-%m-%d %H:%M:%S')
    return formatted_time

def main():
    """
    Main CLI entry point
    """
    parser = create_cli_parser()
    args = parser.parse_args()
    
    # Handle cache reset if requested
    if args.reset_cache:
        clear_cache()
        print("Cache cleared successfully.")
    
    config = parse_config()
    
    # Override config with CLI arguments
    if args.token:
        config['token'] = args.token
    
    # Create ReportPortal client
    rp_client = ReportPortalClient(
        base_url=config['base_url'],
        token=config.get('token'),
        username=config.get('username'),
        password=config.get('password')
    )
    
    # Prepare filter options
    filter_options = {}
    
    if args.name:
        filter_options['name'] = args.name

    if args.test_name:
        filter_options['test_name'] = args.test_name
    
    if args.status:
        filter_options['status'] = args.status
    
    if args.tags:
        filter_options['tags'] = args.tags
    
    # Handle date filters
    if args.start_from:
        filter_options['start_time_from'] = f"{args.start_from}T00:00:00Z"
    
    if args.start_to:
        filter_options['start_time_to'] = f"{args.start_to}T23:59:59Z"
    
    # Handle attribute filters
    if args.attr:
        filter_options['attributes'] = parse_attributes(args.attr)
    
    # Fetch launches
    cache_key = get_cache_key(args.project, args, filter_options)
    cached_launches = get_cached_data(cache_key, max_age_hours=args.cache_hours)
    if cached_launches is not None:
        launches = cached_launches
    else:
        launches = rp_client.fetch_launches(
            project_name=args.project,
            page_num=args.page,
            page_size=args.limit,
            filter_options=filter_options
        )
        cache_data(cache_key, launches)

    if args.failed_tests:
        all_failed_tests = []
        for launch in launches:
            launch_id = launch.get('id')
            launch_name = launch.get('name')
            if launch_id:
                failed_tests = rp_client.fetch_failed_test_cases(args.project, launch_id, launch_name, page_num=args.page, page_size=args.limit, filter_options=filter_options)
                all_failed_tests.extend(failed_tests)
        
        if all_failed_tests:
            # Prepare table data
            if args.test_name:
                print(f"Failed Filtered Test Cases that contains: {args.test_name}")
            headers = ["Launch ID", "Test ID", "Test Name", "Suite Name", "URL"]
            rows = []
            for test in all_failed_tests:
                rows.append([
                    test.get('launch_id', ''),
                    test.get('id', ''),
                    test.get('name', ''),
                    test.get('suite_name', ''),
                    test.get('url', '')
                ])
            
            print("\nFailed Test Cases: {}".format(len(all_failed_tests)))
            print(tabulate(rows, headers=headers, tablefmt='grid'))
        else:
            print("\nNo failed test cases found for filter criteria.")
    # Output launches
    format_output(launches, args.output, args.project)

if __name__ == "__main__":
    main()