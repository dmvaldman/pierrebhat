from autogen import AssistantAgent, ConversableAgent, config_list_from_json
from filesystem import Filesystem, function_spec
from summarizer import Summarizer
from openai_helpers.helpers import MAX_CONTENT_LENGTH


config_list = [{'model': 'gpt-4'}]
llm_config={
    "request_timeout": 600,
    "seed": 42,
    "model": "gpt-4-0613",  # make sure the endpoint you use supports the model
    "temperature": 0,
    "functions": function_spec
}

class ChatWriteCode():
    system_message_filesystem = """
    You are in control of a filesystem API with access to the codebase of a GitHub repository. This API allows you to read summaries of files
    and their full contents. You can also lookup what filename any class/method/import comes from. You are being asked by an engineer who is working on solving a GitHub issue for this repository. You must satisfy all their requests
    for information about the codebase.
    """
    user_system_message = """
    You are a software engineer working on a GitHub repository. You are professional and terse. You have been assigned an issue to resolve.
    You are given a starting point for the relevant files needed to modify. You are also given access to a filesystem API to read these and other files.
    Your task is to write a PR for the issue. Do this by providing a patch for each file that needs to be modified.
    You must also write a test for the PR. Once finished call the `submit_PR` method.
    """
    def __init__(self, issue, files, filesystem, onSubmit):
        self.issue = issue
        self.function_map = {
            "get_summaries": filesystem.get_summaries,
            "get_content": filesystem.get_content,
            "get_filename_for_object": filesystem.get_filename_for_object,
            'submit_PR': onSubmit
        }

        self.user_prompt = self.generate_user_prompt(issue, files)
        self.create_chatbots()

    @staticmethod
    def is_terminal(message):
        if message['content'] is None:
            return False
        return 'TERMINATE' in message['content']

    def generate_user_prompt(self, issue, files):
        # turn files array into bulletpoint list
        files_str = '\n'.join([f'- {file}' for file in files])
        prompt = f"{str(issue)}\n\nHere is a first pass of some of the files that need modifying. Check if modifying them resolves the issue and if so, provide a patch to each file that does so.\n\n{files_str}\nNavigate/read the codebase using the filesystem API to craft and submit a PR."
        return prompt

    def create_chatbots(self):
        self.filesystem_bot = ConversableAgent("filesystem",
            system_message = ChatWriteCode.system_message_filesystem,
            llm_config=llm_config,
            code_execution_config=False,
            is_termination_msg = ChatWriteCode.is_terminal,
            max_consecutive_auto_reply=10,
            human_input_mode="NEVER"
        )

        self.user_bot = ConversableAgent("user",
            system_message = ChatWriteCode.user_system_message,
            is_termination_msg = ChatWriteCode.is_terminal,
            function_map = self.function_map,
            max_consecutive_auto_reply=10,
            human_input_mode="NEVER")

    def initiate_chat(self, **kwargs):
        self.user_bot.initiate_chat(self.filesystem_bot, message=self.user_prompt, **kwargs)
