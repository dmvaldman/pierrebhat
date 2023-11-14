from filesystem import Filesystem, function_specs
import openai

client = openai()

class ChatWriteCode():
    user_system_message = """
    You are a software engineer working on a GitHub repository. You are professional and terse. You have been assigned an issue to resolve.
    You are given a starting point for the relevant files needed to modify. You are also given access to a filesystem API to read these and other files.
    Your task is to write a PR for the issue. Do this by providing a patch for each file that needs to be modified.
    Once finished call the `submit_PR` method. Errors may be returned from `submit_PR` if the PR is not valid, in which case you must fix them and resubmit.
    """
    def __init__(self, issue, filenames, filesystem, onSubmit):
        self.issue = issue
        self.filesystem = filesystem
        self.assistant = self.create_gpt()
        self.file_handlers = self.add_files(filenames)
        self.assistant_file_handlers = self.add_files_to_assistant(self.file_handlers)
        self.user_prompt = self.generate_user_prompt(issue, filenames)

    def add_files(self, filenames):
        # create a file handler for each file
        file_handlers = []
        for file in filenames:
            file_contents = open(file, "rb")
            file_handler = client.files.create(
                file=file_contents,
                purpose='assistants'
            )
            file_handlers.append(file_handler.id)
        return file_handlers

    def remove_files(self):
        for file_id in self.file_handlers:
            client.files.delete(file_id=file_id)

    def add_files_to_assistant(self, file_ids):
        assistant_file_handlers = []
        for file_id in file_ids:
            assistant_file = client.beta.assistants.files.create(
                assistant_id=self.assistant.id,
                file_id=file_id
            )
            assistant_file_handlers.append(assistant_file.id)
        return assistant_file_handlers

    def remove_files_from_assistant(self):
        for file_id in self.assistant_file_handlers:
            client.beta.assistants.files.delete(
                assistant_id=self.assistant.id,
                file_id=file_id
            )
        self.assistant_file_handlers = []

    def generate_user_prompt(self, issue, filenames):
        files_str = '\n'.join([f'- {filename}' for filename in filenames])
        prompt = f"{str(issue)}\n\nHere is a first pass of some of the files that need modifying. Check if modifying them resolves the issue and if so, provide a patch to each file that does so.\n\n{files_str}\nNavigate/read the codebase using the filesystem API to craft and submit a PR."
        return prompt

    def create_gpt(self):
        assistant_functions = {function_spec['name']:function_spec for function_spec in function_specs}

        assistant = client.beta.assistants.create(
            name="Python Developer",
            description=self.user_system_message,
            model="gpt-4-1106-preview",
            tools=[
                {"type": "code_interpreter"},
                {"type": "retrieval"},
                {"type": "function", "function": assistant_functions['submit_PR']},
                {"type": "function", "function": assistant_functions['get_summaries']},
                {"type": "function", "function": assistant_functions['get_content']},
                {"type": "function", "function": assistant_functions['get_filename_for_object']},
                {"type": "function", "function": assistant_functions['list_files']},
            ]
        )

        return assistant

    def delete_gpt(self):
        client.beta.assistants.delete(self.assistant.id)

    def initiate_chat(self, **kwargs):
        thread = client.beta.threads.create()

        message = client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=self.user_prompt
        )

        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=self.assistant.id
        )

        # long poll the endpoint
        while True:
            run = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )

            if run.status == "completed" or run.status == "requires_action":
                messages = client.beta.threads.messages.list(thread_id=thread.id)
                print(messages)
                break
            else:
                time.sleep(0.5)

        self.cleanup()

    def cleanup(self):
        self.remove_files_from_assistant()
        self.remove_files()
        self.delete_gpt()








#
from openai import OpenAI
import os
import time

client = OpenAI()







