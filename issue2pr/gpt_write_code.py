from filesystem import function_specs
from openai import OpenAI
from chat_write_code import apply_patches
import concurrent.futures
import time
import json
import subprocess
from utils.llm_config import llm_config
import os


client = OpenAI(api_key = llm_config['api_key'])
repo_dir = 'repos/'

onCheckPRDef = {
    "name": "check_PR",
    "description": "Checks a PR for formatting errors.",
    "parameters": {
        "type": "object",
        "properties": {
            "patches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "The filename to be patched"
                        },
                        "searchString": {
                            "type": "string",
                            "description": "A string in the file to replace with replaceString. If empty, replaceString will be appended to the end of the file."
                        },
                        "replaceString": {
                            "type": "string",
                            "description": "The string to replace the searchString with. If empty, searchString will be removed from the file."
                        }
                    }
                },
                "description": "An array of patches to be applied to the codebase"
            }
        }
    },
    "required": ["patches"]
}

onSubmitPRDef = {
    "name": "submit_PR",
    "description": "Submits a PR by applying patches to files. The patches encode a simple search and replace operation to modify existing files in the codebase where `searchString` is replaced with `replaceString`.",
    "parameters": {
        "type": "object",
        "properties": {
            "patches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "The filename to be patched"
                        },
                        "searchString": {
                            "type": "string",
                            "description": "A string in the file to replace with replaceString. If empty, replaceString will be appended to the end of the file."
                        },
                        "replaceString": {
                            "type": "string",
                            "description": "The string to replace the searchString with. If empty, searchString will be removed from the file."
                        }
                    }
                },
                "description": "An array of patches to be applied to the codebase"
            }
        }
    },
    "required": ["patches"]
}

def print_message(message):
    print(f'Role: {message.role}\n{message.content[0].text.value}')

def check_syntax(file_path):
    result = subprocess.run(["pyflakes", file_path], capture_output=True, text=True)
    if result.stdout == '':
        return None
    return result.stdout

class GPTWriteCode():
    base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), repo_dir)
    user_system_message = """
    You are an expert programmer working on a GitHub repository. You have been assigned an issue to resolve.
    You are given a starting point with the relevant files needed to modify. You are also given access to a filesystem API to read these and other files.
    Your task is to write a PR for the issue. Do this by providing patches for each file that needs to be modified.
    The patches should be minimal and only modify the code necessary to resolve the issue.
    Once finished call the `check_PR` method. This will validate the PR and return any errors if found,
    otherwise it will ask you to confirm the new files with patches applied, which you should still check for correctness.
    If any errors are found, you must revise the patches and call `check_PR` until no errors are found.
    If no errors are found and you are satisfied with the patches then call the `submit_PR` method to finalize the PR.
    """
    def __init__(self, issue, filenames, filesystem, snippet_type='snippet'):
        self.issue = issue
        self.filesystem = filesystem
        self.assistant = self.create_gpt()
        self.file_handlers = self.add_files(filenames)
        self.assistant_file_handlers = self.add_files_to_assistant(self.file_handlers)
        self.user_prompt = self.generate_user_prompt(issue, filenames)

        self.new_files = concurrent.futures.Future()
        self.patches = concurrent.futures.Future()
        self.snippet_type = snippet_type

        self.function_map = {
            "get_summaries": self.filesystem.get_summaries,
            "get_content": self.filesystem.get_content,
            "get_filename_for_object": self.filesystem.get_filename_for_object,
            "list_files": self.filesystem.tree,
            "check_PR": self.onCheckPR,
            "submit_PR": self.onSubmitPR,
        }

    def add_files(self, filenames):
        # create a file handler for each file
        file_handlers = []
        for filename in filenames:
            # TODO: move logic of where the file is elsewhere
            path = os.path.join(GPTWriteCode.base_path, filename)
            file_contents = open(path, "rb")
            # check if contents are empty
            if file_contents.read() == b'':
                continue
            try:
                file_handler = client.files.create(
                    file=file_contents,
                    purpose='assistants'
                )
                file_handlers.append(file_handler.id)
            except Exception as e:
                # Can be an invalid extension
                print(f'Filename: {filename}\n\nError: {e}')
                continue
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
        prompt = f"{str(issue)}\n\nHere is a first pass of some of the files that need modifying. Check if modifying them resolves the issue and if so, provide a patch to each file that does so.\n\n{files_str}\n\nNavigate/read the codebase using the filesystem API to craft and submit a PR."
        return prompt

    def create_gpt(self):
        assistant_functions = {function_spec['name']:function_spec for function_spec in function_specs}

        # TODO: only create when needed. Retrieve otherwise.

        assistant = client.beta.assistants.create(
            name="Python Developer",
            instructions=self.user_system_message,
            model="gpt-4-1106-preview",
            tools=[
                {"type": "code_interpreter"},
                {"type": "retrieval"},
                {"type": "function", "function": assistant_functions['get_summaries']},
                {"type": "function", "function": assistant_functions['get_content']},
                {"type": "function", "function": assistant_functions['get_filename_for_object']},
                {"type": "function", "function": assistant_functions['list_files']},
                {"type": "function", "function": onCheckPRDef},
                {"type": "function", "function": onSubmitPRDef},
            ]
        )

        return assistant

    def delete_gpt(self):
        client.beta.assistants.delete(self.assistant.id)

    def onSubmitPR(self, patches):
        try:
            new_files, snippets = apply_patches(patches, snippet_type=self.snippet_type)
            self.new_files.set_result(new_files)
            self.patches.set_result(patches)
            return 'Patch successfully applied.'
        except Exception as e:
            return str(e)

    def onCheckPR(self, patches):
        try:
            new_files, snippets = apply_patches(patches, snippet_type=self.snippet_type)
        except Exception as e:
            return str(e)

        errors = 'Following errors found:\n\n'
        has_errors = False
        for filename, contents in new_files.items():
            # create temporary file, flatten any directory structure in the name
            temp_filename = f'temp/{"_".join(filename.split("/"))}'
            with open(temp_filename, 'w') as f:
                f.write(contents)
            syntax_errors = check_syntax(temp_filename)
            if syntax_errors is not None:
                has_errors = True
                errors += syntax_errors + '\n\n'

        snippets_str = '\n'.join([f'Filename: {filename}:\n\n{snippet}\n\n' for filename, snippet in snippets.items()])

        if has_errors:
            return f"Here are the snippets reflecting your changes\n\n{snippets_str}\n\nThe following errors were found:\n\n{errors}\n\nPlease correct the patches and check again."

        if self.snippet_type == 'diff':
            return f"Here is the diff reflecting your changes. Double check its correctness. If the changes are correct proceed to submitting the PR, otherwise explain what's wrong then correct the patch and check it again.\n\n{snippets_str}\n\nDoes this look correct?"
        elif self.snippet_type == 'snippet':
            return f"Here are snippets reflecting your changes. Double check their correctness. If the changes are correct proceed to submitting the PR, otherwise explain what's wrong then correct the patch and check it again.\n\n{snippets_str}\n\nDoes this look correct?"
        elif self.snippet_type == 'all':
            return f"Here are the files reflecting your changes. Double check their correctness. If the changes are correct proceed to submitting the PR, otherwise explain what's wrong then correct the patch and check it again.\n\n{snippets_str}\n\nDoes this look correct?"

    def initiate_chat(self, **kwargs):
        last_msg_id = None

        try:
            thread = client.beta.threads.create()

            message = client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=self.user_prompt
            )

            print_message(message)
            last_msg_id = message.id

            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=self.assistant.id
            )

            # long poll the endpoint
            while True:
                # print(run.status)
                messages = client.beta.threads.messages.list(thread_id=thread.id, after=last_msg_id)
                for message in messages.data:
                    print_message(message)
                    last_msg_id = message.id

                run = client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id
                )

                if run.status == "requires_action":
                    if run.required_action.type == "submit_tool_outputs":
                        tool_calls = run.required_action.submit_tool_outputs.tool_calls
                        tool_outputs = []
                        for tool_call in tool_calls:
                            name = tool_call.function.name
                            params = json.loads(tool_call.function.arguments)

                            print('****************')
                            print(f'Calling function {name} with params {params}')
                            print('****************\n\n')

                            if name in self.function_map:
                                # run the function
                                function = self.function_map[name]
                                try:
                                    output = function(**params)
                                except Exception as e:
                                    output = str(e)

                                print('****************')
                                print(f'Response:\n\n{output}')
                                print('****************\n\n')

                                tool_outputs.append({
                                    'tool_call_id': tool_call.id,
                                    'output': output
                                })
                            else:
                                raise Exception(f"Unknown function: {name}")

                        try:
                            client.beta.threads.runs.submit_tool_outputs(
                                thread_id=thread.id,
                                run_id=run.id,
                                tool_outputs=tool_outputs
                            )
                        except Exception as e:
                            print(e)
                            raise Exception("Error submitting tool outputs")

                        time.sleep(0.5)
                    else:
                        print(run.required_action, run.status)

                elif run.status in ["cancelling", "cancelled", "failed", "expired"]:
                    print(f"Run status is {run.status}. Exiting.")
                    break
                elif run.status == "completed":
                    if not self.new_files.done():
                        raise Exception("No patches or new files to submit")
                    break
                elif run.status in ["queued", "in_progress"]:
                    time.sleep(0.5)

            self.cleanup()

        except Exception as e:
            print(e)
            self.cleanup()

    def cleanup(self):
        self.remove_files_from_assistant()
        self.remove_files()
        self.delete_gpt()


if __name__ == "__main__":
    from Issue2PR import ResolvedIssue
    from filesystem import Filesystem
    import difflib

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
    issue = ResolvedIssue(issue_title, issue_body, repo_name, num=issue_num)
    filenames = ["supervision/supervision/detection/line_counter.py","supervision/supervision/detection/tools/polygon_zone.py"]

    code_writer = GPTWriteCode(issue, filenames, fs)
    code_writer.initiate_chat()

    new_files = code_writer.new_files.result()
    new_files_str = '\n\n'.join([f'Filename: {filename}\n\n{contents}' for filename, contents in new_files.items()])
    print(new_files_str)

    pr_info = issue.fetch_pr_info()
    issue.set_pr_info(pr_info)
    actual_files = issue.get_changed_file_contents()
    actual_files_str = '\n\n'.join([f'Filename: {filename}\n\n{contents}' for filename, contents in actual_files.items()])

    # create diff between actual and new files
    diff = difflib.unified_diff(actual_files_str.splitlines(), new_files_str.splitlines(), fromfile='actual', tofile='new', lineterm='')
    print('Diff between files:\n\n')
    print('\n'.join(diff))

