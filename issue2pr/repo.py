from bs4 import BeautifulSoup
from requests_html import HTMLSession
import os
from openai_helpers.helpers import embed, EMBED_DIMS
import subprocess

session = HTMLSession()

class Repo:
    def __init__(self, repo_name, repo_dir='repos'):
        [org, name] = repo_name.split('/')
        self.org = org
        self.name = name

        curr_dir = os.path.dirname(os.path.abspath(__file__))
        self.local_path = os.path.join(curr_dir, repo_dir, name)
        self.remote_path = f'{org}/{name}'

    def download(self):
        if not os.path.exists(self.local_path):
            # download using subprocess
            command = ['git', 'clone', f'https://github.com/{self.remote_path}.git', self.local_path]
            try:
                result = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,  # Capture the output
                    stderr=subprocess.PIPE,  # Capture the error output
                    text=True  # Output as string, not bytes
                )

                if result.returncode == 0:
                    print("Command executed successfully.")
                    print(result.stdout)
                else:
                    print("An error occurred.")
                    print(result.stderr)

            except Exception as e:
                print(f"An error occurred while executing the clone command: {e}")
        else:
            print(f"Repo {self.remote_path} already exists")


    def checkout(self, sha):
        command = ['git', 'checkout', sha]
        try:
            result = subprocess.run(
                command,
                cwd=self.local_path,
                stdout=subprocess.PIPE,  # Capture the output
                stderr=subprocess.STDOUT,  # Capture the error output
                text=True  # Output as string, not bytes
            )

            if result.returncode == 0:
                print("Command executed successfully.")
                print(result.stdout)
            else:
                print("An error occurred.")
                print(result.stderr)
        except Exception as e:
            print(f"An error occurred while executing the checkout command: {e}")


class PR:
    def __init__(self, pr_num, repo):
        self.num = pr_num
        self.pr = repo.github.get_pull(pr_num)
        self.url = self.pr.html_url
        self.num_changed_files = self.pr.changed_files

        self.parent_commit = self.get_parent_commit()
        self.changed_files = self.get_changed_files()

        if len(self.changed_files) != self.num_changed_files:
            print(f"changed files for {self.url} don't match")

    def get_changed_files(self):
        resp = session.get(f"{self.url}/files")
        resp.html.render()
        soup = BeautifulSoup(resp.html.html, 'html.parser')
        file_els = soup.select('.file-info a[title]')
        if file_els is None:
            return []

        return [el.attrs['title'] for el in file_els]

    def get_parent_commit(self):
        return self.pr.get_commits()[0].parents[0].sha


class Issue:
    def __init__(self, issue):
        self.num = issue.number
        self.issue = issue
        self.url = issue.html_url
        self.title = issue.title
        self.body = issue.body

        self.conversation = self.parse()
        self.full_text = f'Issue: {self.title}\n{self.body}\nResponses:{self.conversation}'

        self.embed = embed(self.full_text)

    def get_comments(self):
        return [comment.body for comment in self.issue.get_comments()]

    def parse(self):
        # Get conversation from the issue
        issue = self.issue
        conversation = ''
        for comment in issue.get_comments():
            name = comment.user.login
            body = comment.body
            conversation += 'From {name}\n: {body}\n'.format(name=name, body=body)
        return conversation


if __name__ == "__main__":
    repo_name = "OpenSignLabs/OpenSign"
    sha = "4b7d66e4e3273e7d8404301fd14c0dfe65d8534d"
    repo = Repo("OpenSignLabs/OpenSign")
    repo.download()
    repo.checkout(sha)