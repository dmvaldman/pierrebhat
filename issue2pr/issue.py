import hashlib
import requests
from filesystem import Filesystem

class Issue():
    def __init__(self, title, body, repo_name, num=None):
        self.title = title
        self.body = body
        self.repo_name = repo_name
        self.num = num

    @property
    def id(self):
        str = f"{self.repo_name}{self.title}{self.body}"
        m = hashlib.sha256()
        m.update(str.encode('utf-8'))
        return f"{self.repo_name}_{m.hexdigest()}"

    def __str__(self):
        return f"Repo: {self.repo_name}\nIssue Title: {self.title}\nIssue Body: {self.body}\n"

    def to_json(self):
        return {
            "repo_name": self.repo_name,
            "title": self.title,
            "body": self.body,
            "num": self.num
        }


class ResolvedIssue(Issue):
    def __init__(self, title, body, repo_name, num=None, pr=None):
        super().__init__(title, body, repo_name, num=num)
        self.pr = pr

        if pr is not None:
            self.changed_files = pr['changed_files']
        else:
            self.changed_files = None

    def set_pr_info(self, pr_info):
        self.pr = pr_info
        self.changed_files = pr_info['changed_files']

    def filtered_changed_files(self):
        changed_files = self.changed_files
        actual_filenames = [file['filename'] for file in changed_files if file['status'] == 'modified']

        #filter filenames to match extensions in Filesystem.extensions
        actual_filenames = [filename for filename in actual_filenames if filename.endswith(Filesystem.extensions)]

        # filter filenames to remove any directories in Filesystem.directory_blacklist
        actual_filenames = [filename for filename in actual_filenames if not any(directory in filename for directory in Filesystem.directory_blacklist)]

        return actual_filenames

    def get_changed_file_contents(self):
        actual_files = {}
        changed_filenames = self.filtered_changed_files()
        repo_name = self.repo_name
        sha = self.pr['merge_commit_sha']
        for filename in changed_filenames:
            url = f'https://raw.githubusercontent.com/{repo_name}/{sha}/{filename}'
            response = requests.get(url)
            if response.status_code == 200:
                actual_files[filename] = response.text
            else:
                raise Exception("Error getting file from GitHub")
        return actual_files

    def fetch_pr_info(self):
        def fetch_pr_info(repo, pr_num):
            url = f"https://api.github.com/repos/{repo}/pulls/{pr_num}"
            response = requests.get(url)
            return response.json()

        def get_changed_files_from_pr(repo, pr_num):
            url = f"https://api.github.com/repos/{repo}/pulls/{pr_num}/files"
            response = requests.get(url)
            files = response.json()
            files = [{'filename': file['filename'], 'status': file['status']} for file in files]
            return files

        # todo: validate another way of finding the PR by hitting https://github.com/repos/{repo}/issues/{issue_num}/linked_closing_reference?reference_location=REPO_ISSUES_INDEX
        # todo: only support 1 label for now
        url_timeline = f"https://api.github.com/repos/{self.repo_name}/issues/{self.num}/timeline"
        params = {
            "state": "closed",
            "per_page": 100,
            "page": 1
        }

        response = requests.get(url_timeline, params=params)
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
