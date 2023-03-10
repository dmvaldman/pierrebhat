from github import Github
import requests
from bs4 import BeautifulSoup
from git import Repo as GitRepo
from requests_html import HTMLSession
import faiss
import re
import os
import numpy as np
import json
from openai_helpers.helpers import compare_embeddings, compare_text, embed, complete, complete_code, EMBED_DIMS
from filesystem import Filesystem, Folder, File

from dotenv import load_dotenv
load_dotenv()

token = os.getenv('GITHUB_TOKEN')
github = Github(token)
session = HTMLSession()


class Repo:
    extensions = ('.js', '.jsx', '.py', '.json', '.html', '.css', '.scss', '.yml', '.yaml', '.ts', '.tsx', '.ipynb', '.c', '.cc', '.cpp', '.go', '.h', '.hpp', '.java', '.sol', '.sh', '.txt')
    directory_blacklist = ('build', 'dist', '.github', 'site', 'tests')
    def __init__(self, org, name, repo_dir='repos'):
        self.org = org
        self.name = name
        self.dir = repo_dir

        self.remote_path = f'{org}/{name}'
        self.local_path = f'{repo_dir}/{name}'

        # CHANGE THIS FOR DIFFERENT REPO. DYNAMICALLY SAVE.
        self.num_files = 345

        self.filesystem = Filesystem()
        self.filesystem.create_folder(self.local_path, description = 'Twitter nanoGPT')

        self.create_filesystem()

        self.repo = GitRepo(self.local_path)
        self.github = github.get_repo(self.remote_path)

        self.paths= self.get_paths()
        self.descriptions = self.get_descriptions()
        self.embeds = self.get_embeds(self.descriptions)
        self.issue_pr_map = self.get_issue_pr_map()

        self.index = faiss.IndexFlatIP(self.embeds.shape[1])
        self.index.add(self.embeds)

    def save_embeds(self, embeds):
        save_path_embed = f'embeddings/{self.name}_embeds.npy'
        with open(save_path_embed, 'wb') as f:
            np.save(f, np.array(embeds))

    def load_embeds(self):
        save_path = f'embeddings/{self.name}_embeds.npy'
        if not os.path.exists(save_path):
            return None
        with open(save_path, 'rb') as f:
            data = np.load(f)
        return data

    def save_paths(self, paths):
        save_path = f'embeddings/{self.name}_paths.json'
        with open(save_path, 'w') as f:
            json.dump(paths, f)

    def load_paths(self):
        save_path = f'embeddings/{self.name}_paths.json'
        if not os.path.exists(save_path):
            return None
        with open(save_path, 'rb') as f:
            data = json.load(f)
        return data

    def load_descriptions(self):
        save_path = f'embeddings/{self.name}_descriptions.json'
        if not os.path.exists(save_path):
            return None
        with open(save_path, 'rb') as f:
            data = json.load(f)
        return data

    def save_descriptions(self, descriptions):
        save_path = f'embeddings/{self.name}_descriptions.json'
        with open(save_path, 'w') as f:
            json.dump(descriptions, f)

    def walk(self, max_num_files=1000):
        num_files = 0
        for root, dirs, files in os.walk(self.local_path, topdown=True):
            files = [f for f in files if not f[0] == '.' and f.endswith(Repo.extensions)]
            dirs[:] = [d for d in dirs if d[0] != '.' and not d.startswith(Repo.directory_blacklist)]
            for name in files:
                filename = os.path.join(root, name)

                try:
                    with open(filename, 'r') as f:
                        code = f.read()
                except UnicodeDecodeError:
                    continue

                if code.strip() == '': continue

                if num_files >= max_num_files:
                    return

                yield filename, root, dirs, code

                num_files += 1
                self.num_files = num_files

    def create_filesystem(self):
        for root, dirs, files in os.walk(self.local_path, topdown=True):
            files = [f for f in files if f[0] != '.' and f.endswith(Repo.extensions)]
            dirs[:] = [d for d in dirs if d[0] != '.' and not d.startswith(Repo.directory_blacklist)]

            folder = self.filesystem.find_folder(root)
            for dir in dirs:
                folder.add_folder(Folder(dir))
            for file in files:
                folder.add_file(File(file))

    def get_embeds(self, descriptions, batch_size=50, save=True):
        embeds = self.load_embeds()
        if embeds is not None:
            return embeds

        batch = []
        embeds = np.empty((0, EMBED_DIMS), np.float32)
        generator = self.walk()
        for filename, root, dirs, code in generator:
            batch.append(f'File: {filename}\n\n{code}') # 1/2 HyDra

            if len(batch) == batch_size:
                embeds_batch = embed(batch)
                embeds = np.append(embeds, embeds_batch, axis=0)
                batch = []

        if len(batch) > 0:
            embeds_batch = embed(batch)
            embeds = np.append(embeds, embeds_batch, axis=0)
            batch = []

        if save: self.save_embeds(embeds)
        return embeds

    def get_paths(self, save=True):
        paths = self.load_paths()
        if paths is not None:
            return paths

        paths = []
        generator = self.walk()

        for filename, root, dirs, code in generator:
            paths.append(filename)

        if save: self.save_paths(paths)
        return paths

    def get_descriptions(self, save=True, save_every=10):
        descriptions = self.load_descriptions()
        if descriptions is not None and len(descriptions) == self.num_files:
            return descriptions

        if descriptions is None:
            descriptions = {}

        generator = self.walk()
        description_prompt = 'A short summary in plain English of the above code is:'
        num_files = len(descriptions)
        for filename, root, dirs, code in generator:
            # Skip files that already have descriptions
            if filename in descriptions: continue
            extension = filename.split('.')[-1]
            prompt = f'File: {filename}\n\nCode:\n\n```{extension}\n{code}```\n\n{description_prompt}\nThis file'
            description = 'This file ' + complete(prompt)
            descriptions[filename] = description

            if save and (num_files % save_every == 0):
                print(f'Saving descriptions for {num_files} files')
                self.save_descriptions(descriptions)

            num_files += 1

        if save: self.save_descriptions(descriptions)

        return descriptions

    def get_similarity(self, text):
        repo_embeddings = self.embeds
        text_embedding = embed(text)
        similarities = []
        for filename, code_embedding in repo_embeddings.items():
            similarity = compare_embeddings(text_embedding, code_embedding)
            similarities.append((similarity, filename))

        similarities.sort(key=lambda x: x[0], reverse=True)
        return similarities

    def get_issue_pr_map(self):
        issue_pr_map = {}

        response = session.get(f'https://github.com/{self.remote_path}/issues?q=is%3Aissue+is%3Aclosed')
        soup = BeautifulSoup(response.text, 'html.parser')

        # look for aria attribute with the text `linked pull request` as a substring
        pr_els = soup.select('[aria-label^="1 linked pull request"] a')
        for issue_el in pr_els:
            linked_issue_url = issue_el.attrs['href']
            match = re.search(r'\/(\d+)\/', linked_issue_url)
            if match:
                issue_num = match.group(1)
                r = requests.get(f'https://github.com/{linked_issue_url}')
                pr_num = int(r.url.split('/')[-1])
                issue_pr_map[issue_num] = pr_num

        return issue_pr_map

    def get_issue_list(self):
        issues = self.github.get_issues()
        issues = [issue for issue in issues if issue.number == 50]
        return [Issue(issue.number, self) for issue in issues]

    def get_nearest_files(self, issue, num_hits=5):
        issue_embedding = issue.embed
        extensions = issue.allowedExtensions
        pairs = []

        for i, embedding in enumerate(self.embeds):
            similarity = compare_embeddings(embedding, issue_embedding)
            pairs.append((self.paths[i], similarity))
            # extension = f'.{self.paths[i].split(".")[-1]}'
            # # check if any of the blacklisted directories are in the path
            # # if any([blacklisted_dir in self.paths[i] for blacklisted_dir in Repo.directory_blacklist]): continue
            # if extension in extensions:


        pairs.sort(key=lambda x: x[1], reverse=True)
        D, I = self.index.search(np.array([issue_embedding]), num_hits)
        nearest_files = [self.paths[i] for i in I[0]]
        return nearest_files # [pair[0] for pair in pairs[0:num_hits]]

    def filter_files_from_descriptions(self, files, issue):
        pass
        # prompt = 'Choose three of the files below that are most relevant to solving this code issue.\n'
        # prompt += f'Issue: {issue.title}\n'
        # for index, file in enumerate(files):
        #     prompt += f'{index}. {file} - {self.descriptions[file]}\n'

    def calc_similarity_score(self, issue, pr, num_hits=5):
        nearest_files = self.get_nearest_files(issue, num_hits=num_hits)
        print('*******')
        print('Nearest files:', nearest_files)
        print('issue', issue.title, '\n', issue.body)
        print('*******\n\n\n')
        count_hits = 0
        count_misses = 0
        relevant_filepaths = []
        print('changed files', pr.changed_files)
        for file in pr.changed_files:
            file_abs = os.path.join(f'{self.local_path}', file)
            if file_abs in nearest_files:
                count_hits += 1
            else:
                count_misses += 1

        return count_hits, count_misses

    def get_issue_patches(self, issue, num_hits=5):
        def clean_code_block(code_block):
            code_block = code_block.strip()
            if code_block.startswith("```"):
                code_block = code_block[3:]
            if code_block.endswith("```"):
                code_block = code_block[:-3]
            code_block = code_block.strip()
            return code_block

        nearest_files = self.get_nearest_files(issue, num_hits=num_hits)

        patches = []
        for file in nearest_files:
            print(file)
            prompt = f'Below is an issue on for the {self.remote_path} codebase.\n Issue:{issue.title} - {issue.body}\n\n Here is a potential file that may need to be updated to fix the issue:\n'

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
                # prompt += 'Please provide a git patch for the file.\n```'
                # patch = complete(prompt)
                # patches[file] = patch
                # action_prompt2 = 'Do the following: 1. output the code block that needs to be changed and 2. output the change.'
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
    def __init__(self, issue_num, repo):
        self.num = issue_num
        self.issue = repo.github.get_issue(issue_num)
        self.url = self.issue.html_url
        self.title = self.issue.title
        self.body = self.issue.body

        self.conversation = self.parse()
        self.full_text = f'Issue: {self.title}\n{self.body}\nResponses:{self.conversation}'

        enhanced_text, extensions = self.enhanceIssue()
        print('enhanced text', f'Key Focus: {enhanced_text}')

        # self.embed = embed(f'Key Focus: {enhanced_text}')
        self.embed = embed(self.full_text)
        self.allowedExtensions = extensions

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

    def enhanceIssue(self):
        prompt = f"""We're trying to figure out the most relevant files to a Github issue in a codebase

Given the following queries, explain what is being looked for and include as many related keywords/synonyms as possible.

Issue:
\"\"\"
In Bootstrap 5.3 alpha 1 input-group component partialy react to inline data-bs-theme="dark" attribute
 ### Prerequisites

- [X] I have [searched](https://github.com/twbs/bootstrap/issues?utf8=%E2%9C%93&q=is%3Aissue) for duplicate or closed issues
- [X] I have [validated](https://html5.validator.nu/) any HTML to avoid common problems
- [X] I have read the [contributing guidelines](https://github.com/twbs/bootstrap/blob/main/.github/CONTRIBUTING.md)

### Describe the issue

So I set for html tag data-bs-theme="light" attribute and set data-bs-theme="dark" attribute inline for form-group component.

When I switch theme in html tag - color scheme of whole document are changing, but form-control background color also change from white to dark, is it must be fixed in dark color?. I repeat this bug at Bootstrap documentation page by inserting
form-group html code in some examples.

### Reduced test cases

```
<!DOCTYPE html>
<html lang="en" data-bs-theme="light">
<head>
</head>
<body>
    <div class="input-group input-group-lg" data-bs-theme="dark">
        <input type="text" class="form-control" placeholder="Email Address" aria-label="Email address" aria-describedby="button-join">
        <button class="btn btn-success bg-gradient" type="button" id="button-join">Join</button>
    </div>
</body>
</html>
```

### What operating system(s) are you seeing the problem on?

Windows

### What browser(s) are you seeing the problem on?

Chrome

### What version of Bootstrap are you using?

v5.3.0-alpha1
\"\"\"
Key Focus: styling
Accepted File Extensions: [".css", ".scss", ".html", ".jsx", ".tsx"]
Core Concepts: styling, CSS, scss, readability, contrast
Code Examples: .bg-gradient, .data-bs-theme, light, dark, background-color: #ffffff

Issue:
\"\"\"
{self.full_text}
\"\"\"
Key Focus:
        """
        results = complete(prompt)
        # extract extract the extensions from the results using this regex: \[.*\]
        file_extensions = re.findall(r'\[.*\]', results)
        if (len(file_extensions) > 0):
            file_extensions = json.loads(file_extensions[0])
        return results, file_extensions

if __name__ == '__main__':
    # repo_org = 'twbs'
    # repo_name = 'bootstrap'
    repo_org = 'karpathy'
    repo_name = 'nanoGPT'
    num_hits = 5
    repo = Repo(repo_org, repo_name)
    total_hits, total_misses = 0, 0

    # In production, get open issues
    patches = {}
    issues = repo.get_issue_list()
    for issue in issues:
        if issue.num == 50:
            patches = repo.get_issue_patches(issue, num_hits=num_hits)
            nearest_files = repo.get_nearest_files(issue, num_hits=num_hits)
            print('NM', nearest_files)

