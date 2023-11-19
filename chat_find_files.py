import concurrent.futures
from autogen import ConversableAgent
from filesystem import Filesystem, function_specs
from openai_helpers.helpers import MAX_CONTENT_LENGTH
import requests

# model = "gpt-4-0613"
model = "gpt-4-1106-preview"

onFindFilesDef = {
    "name": "submit_files",
    "description": "Submits a list of files to be changed in a PR",
    "parameters": {
        "type": "object",
        "properties": {
            "filenames": {
                "type": "array",
                "items": {
                    "type": "string",
                    "description": "A filename"
                },
                "description": "An array of filenames to submit"
            }
        }
    }
}

function_specs.append(onFindFilesDef)

llm_config={
    "timeout": 600,
    "seed": 42,
    "model": model,  # make sure the endpoint you use supports the model
    "temperature": 0,
    "functions": function_specs
}


class Issue():
    def __init__(self, title, body, repo_name, num=None, pr=None):
        self.title = title
        self.body = body
        self.repo_name = repo_name
        self.pr = pr
        self.num = num

        if pr is not None:
            self.changed_files = pr['changed_files']
        else:
            self.changed_files = None

    def __str__(self):
        return f"Repo: {self.repo_name}\nIssue Title: {self.title}\nIssue Body: {self.body}\n"

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

class ChatFindFiles():
    system_message_filesystem = """
    You are in control of a filesystem API with access to the codebase of a GitHub repository. This API allows you to read summaries of files
    and their contents. You are being asked by an engineer who is working on solving a GitHub issue for this repository. You must satisfy all their requests
    for information about the codebase. Upon given a list of files for a PR, call `submit_files`.
    """
    system_message_user = """
    You are a software engineer working on a GitHub repository. You are professional and terse. You have been assigned an issue to resolve.
    Your task is to locate the files needed to modify to resolve the issue, which you can do by conversing with the filesystem API.
    Provide these files by calling `submit_files` with the filenames as arguments. Once you have done so respond TERMINATE to end the chat, but
    not before you've called `submit_files`!.
    """
    def __init__(self, filesystem, issue):
        self.fs = filesystem
        self.issue = issue
        self.function_map = {
            "get_summaries": filesystem.get_summaries,
            "get_content": filesystem.get_content,
            "get_filename_for_object": filesystem.get_filename_for_object,
            "list_files": filesystem.tree
        }

        self.results = []
        self.filenames = concurrent.futures.Future()
        self.create_chatbots()
        self.done_callback(onFindFilesDef)

    @staticmethod
    def is_terminal(message):
        if message['content'] is None:
            return False
        return 'TERMINATE' in message['content']

    def done_callback(self, method_def):
        def onFindFiles(filenames):
            # strip repo name from filenames
            issue = self.issue
            repo_name = issue.repo_name.split('/')[1]
            filenames = [filename.replace(repo_name + '/', '', 1) for filename in filenames]

            if issue.changed_files:
                actual_filenames = issue.filtered_changed_files()
                test_result = set(actual_filenames) <= set(filenames)
            else:
                actual_filenames = None
                test_result = None

            result = {
                'repo_name': issue.repo_name,
                'issue_num': issue.num,
                'actual_filenames': actual_filenames,
                'proposed_filenames': filenames,
                'correct_files': test_result
            }

            self.results.append(result)

            filenames = [repo_name + '/' + filename for filename in filenames]
            self.filenames.set_result(filenames)

        method_name = method_def['name']
        self.function_map[method_name] = onFindFiles
        llm_config["functions"].append(method_def)

        self.filesystem_bot.llm_config.update(llm_config)
        self.user_bot.register_function(self.function_map)

    def generate_user_prompt(self, issue, fs):
        # TODO: better truncation
        prompt = f"{str(issue)}\n\nHere is the directory structure.\n\n{fs.tree()}\nWhat files need to be changed to fix this issue? Navigate/read the codebase using the filesystem API to determine a list of files (in mardown format) that need modifying."
        if len(prompt) > MAX_CONTENT_LENGTH:
            prompt = prompt[:MAX_CONTENT_LENGTH] + '...'
        return prompt

    def create_chatbots(self):
        self.filesystem_bot = ConversableAgent("filesystem",
            system_message = ChatFindFiles.system_message_filesystem,
            llm_config=llm_config,
            code_execution_config=False,
            is_termination_msg = ChatFindFiles.is_terminal,
            max_consecutive_auto_reply=10,
            human_input_mode="NEVER"
        )

        self.user_bot = ConversableAgent("user",
            system_message = ChatFindFiles.system_message_user,
            llm_config=llm_config,
            is_termination_msg = ChatFindFiles.is_terminal,
            function_map = self.function_map,
            code_execution_config=False,
            max_consecutive_auto_reply=10,
            human_input_mode="NEVER")

    def initiate_chat(self, **kwargs):
        prompt = self.generate_user_prompt(self.issue, self.fs)
        self.user_bot.initiate_chat(self.filesystem_bot, message=prompt, **kwargs)

if __name__ == "__main__":
    owner = "roboflow"
    name = "supervision"
    repo_name = f"{owner}/{name}"

    fs = Filesystem(name, create_meta=True)

    issue_num = 464
    issue_title = "Make `sv.LineZone.trigger` return bool `np.ndarray` informing which detections have crossed the line this frame"
    issue_body = """
    Currently, [`sv.LineZone.trigger`](https://github.com/roboflow/supervision/blob/5b5e0eb88daec92643834b2284e750ad5a1c7dc6/supervision/detection/line_counter.py#L30) updates `in_count` and `out_count` values but does not return information on which object crossed the line. Unlike [`sv.PolygonZone.trigger`](https://github.com/roboflow/supervision/blob/5b5e0eb88daec92643834b2284e750ad5a1c7dc6/supervision/detection/tools/polygon_zone.py#L45), which returns such information.

    Information about who has crossed the line is needed to update `in_count` and `out_count` and is already calculated in the `trigger` method but does not surface. Let's change that.
    """

    issue = Issue(issue_title, issue_body, repo_name, num=issue_num)
    chat = ChatFindFiles(fs, issue)
    chat.initiate_chat()
