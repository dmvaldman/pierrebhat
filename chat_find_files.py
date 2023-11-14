from autogen import ConversableAgent
from filesystem import Filesystem, function_specs
from openai_helpers.helpers import MAX_CONTENT_LENGTH

# model = "gpt-4-0613"
model = "gpt-4-1106-preview"
llm_config={
    "request_timeout": 600,
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

class ChatFindFiles():
    system_message_filesystem = """
    You are in control of a filesystem API with access to the codebase of a GitHub repository. This API allows you to read summaries of files
    and their contents. You are being asked by an engineer who is working on solving a GitHub issue for this repository. You must satisfy all their requests
    for information about the codebase.
    """
    user_system_message = """
    You are a software engineer working on a GitHub repository. You are professional and terse. You have been assigned an issue to resolve.
    Your task is to locate the files needed to modify to resolve the issue, which you can do by conversing with the filesystem API.
    Provide these files to the filesystem using `submit_files`. Once you have done so respond TERMINATE to end the chat.
    """
    def __init__(self, filesystem, issue, onSubmit):
        self.fs = filesystem
        self.issue = issue
        self.function_map = {
            "get_summaries": filesystem.get_summaries,
            "get_content": filesystem.get_content,
            "get_filename_for_object": filesystem.get_filename_for_object,
            "list_files": filesystem.tree,
            'submit_files': onSubmit
        }

        self.user_prompt = self.generate_user_prompt(issue, filesystem)
        self.create_chatbots()

    @staticmethod
    def is_terminal(message):
        if message['content'] is None:
            return False
        return 'TERMINATE' in message['content']

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
            system_message = ChatFindFiles.user_system_message,
            is_termination_msg = ChatFindFiles.is_terminal,
            function_map = self.function_map,
            max_consecutive_auto_reply=10,
            human_input_mode="NEVER")

    def initiate_chat(self, **kwargs):
        self.user_bot.initiate_chat(self.filesystem_bot, message=self.user_prompt, **kwargs)

if __name__ == "__main__":
    repo_name = "Auto-GPT"
    fs = Filesystem(repo_name, create_meta=True)

    issue_title = "The model: gpt-4 does not exist / fixing defaults in llm_utils.py"
    issue_body = """
    the defaults need to be adapted for people without access to GPT4 - or the corresponding functions won't work.
    The default model for people without GPT4 access should be cfg.fast_llm_model and not cfg.smart_llm_model

    It would probably make sense to check once during startup what model is available and then set up the default accordingly.
    In general, GPT4 should only be a default setting once it is verified to be available.
    """

    issue = Issue(issue_title, issue_body, repo_name)
    chat = ChatFindFiles(fs, issue)
    chat.initiate_chat()
