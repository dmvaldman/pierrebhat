from github import Github
from openai_helpers.helpers import compare_embeddings, compare_text, embed, complete, complete_code
from multiprocessing import Pool
from functools import reduce
import os
from utils.utils import clean_code_block

from repo import Repo, Issue, PR

# TODO: should create a branch before making a PR?

class SubmittedPR:
    def __init__(self, issue, changes):
        # changes is a dict of {filename: (prev_content, new_content)}
        self.changes = changes
        self.issue = issue
        self.title = self.create_title(changes, issue)
        self.body = self.create_body(changes, issue)

    def create_title(self, changes, issue):
        changed_files = [x['file_name'] for x in changes]
        prompt = f'What is a 1-liner description for the github PR that fixes this issue? The issue title is {issue.title} and the body is {issue.body}. The fix modified these files: {changed_files}.\nTitle:'
        title = complete(prompt)
        return title

    def create_body(self, changes, issue):
        # TODO: diff the changes and use that to create a better description
        changed_files = [x['file_name'] for x in changes]
        prompt = f'What is a description of the github PR that fixes this issue? The issue title is {issue.title} and the issue body is {issue.body}. The fix modified these files: {changed_files}.\nDescription:'
        prompt += 'Respond in markdown format and break down the fix into steps.'
        description = complete(prompt)
        return f'Fixes {issue.url}.\n\n{description}'

class PRBot:

    extensions = ('.js', '.jsx', '.py', '.md', '.json', '.html', '.css', '.yml', '.yaml', '.ts', '.tsx', '.ipynb', '.c', '.cc', '.cpp', '.go', '.h', '.hpp', '.java', '.sol', '.sh', '.txt')
    directory_blacklist = ('build', 'dist', '.github')

    def __init__(self, repo_name):
        github = Github(os.getenv('PIERRE_BOT_TOKEN'))
        self.user = github.get_user()
        self.upstream_repo = github.get_repo(repo_name)
        self.forked_repo = self.fork_repo(self.upstream_repo)

    def fork_repo(self, repo):
        if repo.name not in [r.name for r in self.user.get_repos()]:
            return self.user.create_fork(repo)
        else:
            return self.user.get_repo(repo.name)

    def create_pr(self, pr: SubmittedPR):
        self.apply_changes(pr.changes)
        # self.upstream_repo.create_pull(pr.title, pr.body, base=self.upstream_repo.default_branch, head="pierrebhat:master")

    def apply_changes(self, changes):
        for change in changes:
            file_path = str(change["file_name"]).replace('repos/nanoGPT/', '')
            new = change["new_content"]
            file = self.forked_repo.get_contents(file_path)
            self.forked_repo.update_file(file_path, f'Updated {file.path}', new, file.sha)

    def generate_patches(self, files, issue):
        patches = []
        for file in files:
            print(file)
            prompt = f'Below is an issue on for the {self.upstream_repo} codebase.\n Issue:{issue.title} - {issue.body}\n\n Here is a potential file that may need to be updated to fix the issue:\n'

            prompt += file + '```\n'
            with open(file, 'r') as f:
                file_content = f.read()
                prompt += file_content
            prompt += '```\n'

            action_prompt1 = 'Does this file need to be changed to resolve the issue? Respond with only `Yes` or `No`.'
            needs_patch = complete(prompt + action_prompt1)
            needs_patch = 'Yes'

            if needs_patch == 'No':
                continue
            else:
                action_prompt2 = "Identify which code block needs to be changed (mark it up with \"Before:\") and output the change (mark it up with \"After:\"). Make your change match the coding style of the original file."
                change = complete(prompt + action_prompt2)
                if "Before:" not in change or "After:" not in change:
                    print("Warning: incorrect output format")
                    continue
                before_and_after = change.split("Before:", 1)[1]
                before, after = before_and_after.split("After:", 1)
                before = clean_code_block(before)
                after = clean_code_block(after)
                if before in file_content:
                    new_file_content = file_content.replace(before, after)
                    # Create a patch
                    patch = {
                        "file_name": file,
                        "content": file_content,
                        "new_content": new_file_content
                    }
                    patches.append(patch)
                else:
                    print("Warning: cannot locate `Before` block")

        print(f"Sending {len(patches)} files in the patch")

        return patches
