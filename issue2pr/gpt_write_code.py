from filesystem import function_specs
from openai import OpenAI
from chat_write_code import apply_patches, check_syntax, onCheckPRDef, onSubmitPRDef, SNIPPET_TYPE, GET_CONTENT_TYPE
import concurrent.futures
import time
import json
from utils.llm_config import llm_config
import os
import sys


client = OpenAI(api_key = llm_config['api_key'])

repo_dir = 'repos/'
temp_dir = 'temp/'
base_path = os.path.dirname(os.path.abspath(__file__))


class GPTWriteCode():
    base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), repo_dir)
    user_system_message = """You are an expert programmer working on a GitHub repository. You have been assigned an issue to resolve.
    You are given a starting point with the best-guess relevant files needed to modify. You are also given access to a filesystem API to read these and other files.
    Your task is to write a PR for the issue. Do this by providing patches for each file that needs to be modified.
    The patches should only modify the code necessary to resolve the issue.
    Once finished call the `check_PR` method. This will validate the PR and return any errors if found,
    otherwise it will ask you to confirm the new files with patches applied, which you should still check for correctness.
    If any errors are found, you must revise the patches and call `check_PR` until no errors are found.
    If no errors are found and you are satisfied with the patches then call the `submit_PR` method to finalize the PR.
    You must always submit a PR before terminating.
    """
    def __init__(self, issue, filenames, filesystem, snippet_type=SNIPPET_TYPE.SNIPPET, get_content_type=GET_CONTENT_TYPE.FILE):
        self.issue = issue
        self.filesystem = filesystem
        self.file_handlers = []
        self.assistant_file_handlers = []
        self.name = "Python Developer"
        self.messages = []

        self.assistant = self.create_gpt()
        self.user_prompt = self.generate_user_prompt(issue, filenames)
        self.create_files(filenames)
        self.add_files_to_assistant(self.file_handlers)

        self.new_files = concurrent.futures.Future()
        self.patches = concurrent.futures.Future()
        self.original_files = concurrent.futures.Future()
        self.snippet_type = snippet_type

        if get_content_type == GET_CONTENT_TYPE.FILE:
            get_content_fn = self.get_content
        elif get_content_type == GET_CONTENT_TYPE.CONTEXT:
            get_content_fn = self.filesystem.get_content

        self.function_map = {
            "get_summaries": self.filesystem.get_summaries,
            "get_content": get_content_fn,
            "get_filename_for_object": self.filesystem.get_filename_for_object,
            "list_files": self.filesystem.tree,
            "check_PR": self.on_check_pr,
            "submit_PR": self.on_submit_pr,
        }

    def get_content(self, filename):
        try:
            self.filesystem.get_content(filename) # run this to potentially catch error
            file_handle = self.create_file(filename)
            self.add_file_to_assistance(file_handle.id)
            return f"File uploaded to {self.name} GPT assistant."
        except Exception as e:
            return str(e)

    def create_files(self, filenames):
        for filename in (filenames['modify'] + filenames['remove']):
            self.create_file(filename)

    def create_file(self, filename):
        # TODO: move logic of where the file is elsewhere
        path = os.path.join(GPTWriteCode.base_path, filename)
        file_contents = open(path, "rb")
        if file_contents.read() == b'':
            # skip empty files
            return None
        try:
            file_handler = client.files.create(
                file=file_contents,
                purpose='assistants'
            )
            self.file_handlers.append(file_handler.id)
            return file_handler
        except Exception as e:
            # Can be an invalid extension
            print(f'Filename: {filename}\n\nError: {e}')
            return None

    def delete_files(self):
        for file_id in self.file_handlers:
            self.delete_file(file_id)

    def delete_file(self, id):
        client.files.delete(file_id=id)
        self.file_handlers.remove(id)

    def add_files_to_assistant(self, file_ids):
        for file_id in file_ids:
            self.add_file_to_assistance(file_id)

    def add_file_to_assistance(self, file_id):
        assistant_file = client.beta.assistants.files.create(
            assistant_id=self.assistant.id,
            file_id=file_id
        )
        self.assistant_file_handlers.append(assistant_file.id)

    def remove_files_from_assistant(self):
        for file_id in self.assistant_file_handlers.copy():
            self.remove_file_from_assistant(file_id)

    def remove_file_from_assistant(self, file_id):
        client.beta.assistants.files.delete(
            assistant_id=self.assistant.id,
            file_id=file_id
        )
        self.assistant_file_handlers.remove(file_id)

    def generate_user_prompt(self, issue, filenames):
        files_str = ''
        for action, paths in filenames.items():
            files_str += f'Proposed files to {action}:\n\n'
            if len(paths) == 0:
                files_str += 'None\n'
            else:
                for path in paths:
                    files_str += f'- {path}\n'
            files_str += '\n'
        prompt = f"{str(issue)}\n\nHere is a first pass of some of the files that need modifying/adding/removing. Check if modifying them resolves the issue and if so, provide a patch to each file that does so.\n\n{files_str}\n\nNavigate/read the codebase using the filesystem API to craft and submit a PR."
        return prompt

    def create_gpt(self):
        # TODO: retrieve if already exists
        assistant_functions = {function_spec['name']:function_spec for function_spec in function_specs}
        assistant = client.beta.assistants.create(
            name=self.name,
            instructions=self.user_system_message,
            model="gpt-4-1106-preview",
            tools=[
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

    def on_submit_pr(self, patches):
        try:
            new_files, original_files, _ = apply_patches(patches, snippet_type=self.snippet_type)
            self.new_files.set_result(new_files)
            self.patches.set_result(patches)
            self.original_files.set_result(original_files)
            return 'Patch successfully applied.'
        except Exception as e:
            return f'Error submitting PR: {e}'

    def on_check_pr(self, patches):
        try:
            new_files, _, snippets = apply_patches(patches, snippet_type=self.snippet_type)
        except Exception as e:
            return f'Error checking PR: {e}'

        errors = ''
        has_errors = False
        for filename, contents in new_files.items():
            # create temporary file, flatten any directory structure in the name
            temp_path = os.path.join(base_path, temp_dir, f'{"_".join(filename.split("/"))}')
            with open(temp_path, 'w') as f:
                f.write(contents)
            syntax_errors = check_syntax(temp_path)
            if syntax_errors is not None:
                has_errors = True
                errors += syntax_errors + '\n\n'

        snippets_str = '\n'.join([f'Filename: {filename}\n\n{snippet}\n\n' for filename, snippet in snippets.items()])

        if has_errors:
            return f"Here are the snippets reflecting your changes\n\n{snippets_str}\nThe following errors were found in the NEW snippet:\n\n{errors}Correct the patches (relative to the original files) and call `check_PR` again."
        elif self.snippet_type == SNIPPET_TYPE.DIFF:
            return f"Here is the diff reflecting your changes.\n\n{snippets_str}\n\nDoes this change resolve the issue? Unless you notice a glaring error, proceed to submitting the PR. If you do see a glaring error, explain what's wrong then generate and submit a corrected patch (relative to the original files)."
        elif self.snippet_type == SNIPPET_TYPE.SNIPPET:
            return f"Here is the diff reflecting your changes.\n\n{snippets_str}\n\nDoes this change resolve the issue? Unless you notice a glaring error, proceed to submitting the PR. If you do see a glaring error, explain what's wrong then generate and submit a corrected patch (relative to the original files)."
        elif self.snippet_type == SNIPPET_TYPE.ALL:
            return f"Here is the diff reflecting your changes.\n\n{snippets_str}\n\nDoes this change resolve the issue? Unless you notice a glaring error, proceed to submitting the PR. If you do see a glaring error, explain what's wrong then generate and submit a corrected patch (relative to the original files)."

    def initiate_chat(self, **kwargs):
        last_msg_id = None

        def print_message(message):
            message_str = f'Role: {message.role}\n{message.content[0].text.value}'
            print(message_str)
            self.messages.append(message_str)

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
                # print("STATUS:", run.status)
                sys.stdout.flush()

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

                            if tool_call.function.arguments is None or tool_call.function.arguments == '':
                                print('hi')

                            print('TOOL args', tool_call.function.arguments)

                            params = json.loads(tool_call.function.arguments)

                            msg_str = f'Calling function {name} with params {params}'
                            print('*'*10 + '\n' + msg_str + '\n' + '*'*10 + '\n\n')
                            self.messages.append(msg_str)

                            if name in self.function_map:
                                # run the function
                                function = self.function_map[name]
                                try:
                                    output = str(function(**params))
                                except Exception as e:
                                    output = str(e)

                                output = output.strip()
                                if output.startswith("Error: FINISHED") or output.startswith("Unterminated") or output.startswith("'action'") or output.startswith('[Errno 2]') or output.startswith('Expecting value') or output.startswith('Unterminated string') or output.startswith('Expecting property name') or output.startswith('not enough'):
                                    print('hi')

                                msg_str = f'Response:\n\n{output}'
                                print('*'*10 + '\n' + msg_str + '\n' + '*'*10 + '\n\n')
                                self.messages.append(msg_str)

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
                            raise Exception("Error submitting tool outputs")

                        time.sleep(0.5)
                    else:
                        print(run.required_action, run.status)

                elif run.status in ["cancelling", "cancelled", "failed", "expired"]:
                    raise Exception(f"Run status is {run.status}. Exiting.")
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
        self.delete_files()
        self.delete_gpt()


if __name__ == "__main__":
    from issue import ResolvedIssue
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

