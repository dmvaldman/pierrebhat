import requests
from collections import defaultdict
from datetime import datetime, timedelta
import time
import json
import os
from dotenv import load_dotenv
from utils import filter_path

load_dotenv()
token = os.getenv('GITHUB_TOKEN')

HEADERS = {
    "Authorization": f"token {token}"
}

# code from another file for parsing the paired PR/issues
# def get_issue_pr_map(self):
#     issue_pr_map = {}

#     response = session.get(f'https://github.com/{self.remote_path}/issues?q=is%3Aissue+is%3Aclosed')
#     soup = BeautifulSoup(response.text, 'html.parser')

#     # look for aria attribute with the text `linked pull request` as a substring
#     pr_els = soup.select('[aria-label^="1 linked pull request"] a')
#     for issue_el in pr_els:
#         linked_issue_url = issue_el.attrs['href']
#         match = re.search(r'\/(\d+)\/', linked_issue_url)
#         if match:
#             issue_num = match.group(1)
#             r = requests.get(f'https://github.com/{linked_issue_url}')
#             pr_num = int(r.url.split('/')[-1])
#             issue_pr_map[issue_num] = pr_num

#     return issue_pr_map

def fetch_recent_issues(labels, state, languages=None, max_days=365):
    # Get all issues with the given labels and state (open or closed) in the last max_days days
    url = "https://api.github.com/search/issues"
    labels_query = " ".join(f"label:\"{label}\"" for label in labels)
    languages_query = " ".join(f"language:{language}" for language in languages) if languages else ""

    def get_num_issues():
        # fetch issues from max days from now
        until = datetime.now()
        delta = timedelta(days=max_days)
        since = until - delta
        query = f"is:issue {labels_query} is:{state} created:{since.isoformat()}..{until.isoformat()} {languages_query}"
        params = {
            "q": query,
            "per_page": 1
        }
        response = requests.get(url, params=params, headers=HEADERS)
        issue_count = response.json().get('total_count', 0)
        return issue_count

    num_issues = get_num_issues()
    print('total issues', num_issues)

    # keep calling the API in windows until all issues are fetched
    all_issues = []
    end_date = datetime.now()
    delta = timedelta(days=max_days)
    start_date = end_date - delta

    while len(all_issues) < num_issues and start_date < end_date:
        query = f"is:issue {labels_query} is:{state} created:{start_date.isoformat()}..{end_date.isoformat()} {languages_query}"

        params = {
            "q": query,
            "sort": "created",  # Sorting by creation date
            "order": "desc",    # Sorting in descending order (newest first)
            "per_page": 100,
            "page": 1
        }

        response = requests.get(url, params=params, headers=HEADERS)
        issues = response.json().get('items', [])

        print(len(all_issues), start_date, end_date)

        # Handle rate limits
        remaining_requests = int(response.headers.get('X-RateLimit-Remaining', 0))
        if remaining_requests == 0:
            reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
            sleep_time = max(0, reset_time - int(time.time()))
            print(f"Rate limit exceeded. Waiting for {sleep_time} seconds.")
            time.sleep(sleep_time + 1)  # Adding 1 second to ensure the limit is reset

        if not issues:  # Break the loop if no more issues are returned
            time.sleep(1)
            continue

        last_issue_date_str = issues[-1].get('created_at', '')
        all_issues.extend(issues)

        # Update since_date to the creation date of the last issue fetched
        end_date = datetime.strptime(last_issue_date_str, '%Y-%m-%dT%H:%M:%SZ')

    # convert issues to more minimal format {title, body, num, state}
    return [
        {
            'title': issue['title'],
            'body': issue['body'],
            'num': issue['number'],
            'state': issue['state'],
            'repo_name': issue['repository_url'].split('/')[-2] + '/' + issue['repository_url'].split('/')[-1]
        }
        for issue in all_issues
    ]

def sort_issues_by_repository(issues):
    # sort into repos first, then filter by repo name. don't loop through issues.
    repo_issues = defaultdict(list)
    [repo_issues[issue['repo_name']].append(issue) for issue in issues]

    # turn into a list of [{repo_name, issue_count, issues: []}]
    repo_issues = [{'repo_name': repo_name, 'issue_count': len(issues), 'issues': issues} for repo_name, issues in repo_issues.items()]
    # sort by num issues desc
    repo_issues.sort(key=lambda x: x['issue_count'], reverse=True)

    return repo_issues

def filter_repo_issues(repo_issues, min_stars=100, min_issues=5, max_files=500):
    filtered_repo_issues = {}

    # filter out repos with less than a certain number of issues
    repo_issues = [repo_issue for repo_issue in repo_issues if repo_issue['issue_count'] >= min_issues]

    repo_names = [repo_issue['repo_name'] for repo_issue in repo_issues]
    print('Num repos', len(repo_names))

    filtered_repo_names = filter_repos_by_star_limit(repo_names, min_stars=min_stars)

    ratio = 100 * (len(repo_names) - len(filtered_repo_names)) / len(repo_names)
    print(f"Filtered {len(repo_names) - len(filtered_repo_names)} repos ({ratio:.2f}%) by star count")

    filtered_repo_names = filtered_repos_by_star_limit(filtered_repo_names, max_files=max_files)

    ratio = 100 * (len(filtered_repo_names) - len(filtered_repo_issues)) / len(filtered_repo_names)
    print(f"Filtered {len(filtered_repo_names) - len(filtered_repo_issues)} repos ({ratio:.2f}%) by file count")

    for repo_data in repo_issues:
        repo_name = repo_data['repo_name']
        if repo_name in filtered_repo_names:
            filtered_repo_issues[repo_name] = repo_data['issues']

    return filtered_repo_issues

def filtered_repos_by_star_limit(repo_names, max_files=500):
    filtered_repo_names = []
    for repo_name in repo_names:
        # filter out repos greater than a certain number of files
        if not filter_repo_by_file_limit(repo_name, max_files=max_files):
            filtered_repo_names.append(repo_name)
    return filtered_repo_names


def filter_repo_by_file_limit(repo_name, max_files=500):
    tree_url = f"https://api.github.com/repos/{repo_name}/git/trees/main?recursive=1"
    tree_response = requests.get(tree_url, headers=HEADERS).json()
    file_count = sum(1 for item in tree_response.get('tree', []) if item['type'] == 'blob' and filter_path(item['path']))
    return file_count > max_files or file_count == 0

def filter_repos_by_star_limit(repo_names, min_stars=100):
    repo_star_counts = get_repos_star_count(repo_names)
    filtered_repo_names = []
    for repo_name, star_count in repo_star_counts.items():
        if star_count >= min_stars:
            filtered_repo_names.append(repo_name)
    return filtered_repo_names

def get_changed_files_from_pr(repo, pr_num):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_num}/files"
    response = requests.get(url, headers=HEADERS)
    files = response.json()
    # reformat
    files = [{'filename': file['filename'], 'status': file['status']} for file in files]
    return files

def fetch_pr_info(repo, pr_num):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_num}"
    response = requests.get(url, headers=HEADERS)
    return response.json()

def fetch_pr_from_issue(repo, issue_num, labels):
    # todo: validate another way of finding the PR by hitting https://github.com/repos/{repo}/issues/{issue_num}/linked_closing_reference?reference_location=REPO_ISSUES_INDEX
    # todo: only support 1 label for now
    url_timeline = f"https://api.github.com/repos/{repo}/issues/{issue_num}/timeline"
    params = {
        "state": "closed",
        "labels": labels[0],
        "per_page": 100,
        "page": 1
    }

    response = requests.get(url_timeline, params=params, headers=HEADERS)
    timeline_events = response.json()
    pr_num = None
    pr_info = None

    # loop through timeline events and find the one with a pull request
    for timeline_event in timeline_events:
        if 'source' in timeline_event:
            if 'issue' in timeline_event['source']:
                if 'pull_request' in timeline_event['source']['issue']:
                    url_pull = timeline_event['source']['issue']['pull_request']['url']
                    pr_num = int(url_pull.split('/')[-1])
                    repo = '/'.join(url_pull.split('/')[-4:-2])
                    pr_info = fetch_pr_info(repo, pr_num)

    if pr_num is not None:
        # convert into simpler representaiton {num, merge_commit_sha, base_sha, changed_files}
        changed_files = get_changed_files_from_pr(repo, pr_num)
        if not changed_files:
            return None

        # if none of the files have status "modified" also return None
        if not any(file['status'] == 'modified' for file in changed_files):
            return None

        pr_info = {
            'num': pr_info['number'],
            'merge_commit_sha': pr_info['merge_commit_sha'],
            'base_sha': pr_info['base']['sha'],
            'changed_files': changed_files
        }
        return pr_info
    else:
        return None

def get_repos_star_count(repo_names):
    # chunk this into 100 names at a time
    star_counts = {}
    N = len(repo_names)
    for i in range(0, N, 100):
        repo_names_chunk = repo_names[i:i + 100]
        star_counts_chunk = get_repos_star_count_chunk(repo_names_chunk)
        star_counts.update(star_counts_chunk)
    return star_counts

def get_repos_star_count_chunk(repo_names):
    repo_queries = ' '.join(f'repo_{i}: repository(name: "{repo_name.split("/")[-1]}", owner: "{repo_name.split("/")[0]}") {{ stargazers {{ totalCount }} }}' for i, repo_name in enumerate(repo_names))

    query = f"""
    {{
        {repo_queries}
    }}
    """

    response = requests.post('https://api.github.com/graphql', json={'query': query}, headers=HEADERS)
    response_json = response.json()

    star_counts = {}

    for i, repo_name in enumerate(repo_names):
        alias = f"repo_{i}"
        repo_data = response_json.get('data', {}).get(alias, {})
        stars = repo_data.get('stargazers', {}).get('totalCount', None)

        if stars is not None:
            star_counts[repo_name] = stars

    return star_counts

def fetch_prs_for_repo_issues(repo_issues, labels):
    repo_issues_with_prs = defaultdict(list)
    for repo, issues in repo_issues.items():
        for issue in issues:
            pr = fetch_pr_from_issue(repo, issue['num'], labels)
            if pr is not None:
                issue['pr'] = pr
                repo_issues_with_prs[repo].append(issue)
    return repo_issues_with_prs

if __name__ == '__main__':
    labels = ["good first issue"]
    languages = ['python']
    state = "closed"
    min_stars = 20
    num_days = 30
    max_files = 500
    min_issues = 5
    save = True

    issues = fetch_recent_issues(labels, state, languages=languages, max_days=num_days)
    repo_issues = sort_issues_by_repository(issues)
    repo_issues_filtered = filter_repo_issues(repo_issues, min_stars=min_stars, min_issues=min_issues, max_files=max_files)
    repo_issues_with_prs = fetch_prs_for_repo_issues(repo_issues_filtered, labels)

    # save to json
    if save:
        json.dump(repo_issues_with_prs, open('data/datasets/repo_issues.json', 'w'), indent=2)