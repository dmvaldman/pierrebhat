from filesystem import function_specs
from openai import OpenAI
from chat_write_code import apply_patches
import concurrent.futures
import time
import json

client = OpenAI()

onSubmitCodeDef = {
    "name": "submit_PR",
    "description": "Submits a PR by applying patched to files.",
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

class GPTWriteCode():
    user_system_message = """
    You are a software engineer working on a GitHub repository. You have been assigned an issue to resolve.
    You are given a starting point for the relevant files needed to modify. You are also given access to a filesystem API to read these and other files.
    Your task is to write a PR for the issue. Do this by providing patches for each file that needs to be modified.
    Once finished call the `submit_PR` method. Errors may be returned from `submit_PR` if the PR is not valid, in which case you must fix them and resubmit.
    """
    def __init__(self, issue, filenames, filesystem, snippet_type='diff'):
        self.issue = issue
        self.filesystem = filesystem
        self.assistant = self.create_gpt()
        self.file_handlers = self.add_files(filenames)
        self.assistant_file_handlers = self.add_files_to_assistant(self.file_handlers)
        self.user_prompt = self.generate_user_prompt(issue, filenames)

        self.new_files = concurrent.futures.Future()
        self.patches = concurrent.futures.Future()

        self.function_map = {
            "get_summaries": self.filesystem.get_summaries,
            "get_content": self.filesystem.get_content,
            "get_filename_for_object": self.filesystem.get_filename_for_object,
            "list_files": self.filesystem.tree,
            "submit_PR": self.onSubmitPR,
        }

    def add_files(self, filenames):
        # create a file handler for each file
        file_handlers = []
        for file in filenames:
            # TODO: move logic of where the file is elsewhere
            file_contents = open('repos/' + file, "rb")
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
                {"type": "function", "function": onSubmitCodeDef},
            ]
        )

        return assistant

    def delete_gpt(self):
        client.beta.assistants.delete(self.assistant.id)

    def onSubmitPR(self, patches):
        try:
            new_files, snippets = apply_patches(patches, snippet_type='diff')
            self.new_files.set_result(new_files)
            self.patches.set_result(patches)
            return 'Patch successfully applied.'
        except Exception as e:
            return str(e)

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
                            print('****************')
                            if name in self.function_map:
                                # run the function
                                function = self.function_map[name]
                                try:
                                    output = function(**params)
                                except Exception as e:
                                    output = str(e)
                                tool_outputs.append({
                                    'tool_call_id': tool_call.id,
                                    'output': output
                                })
                            else:
                                raise Exception(f"Unknown function: {tool_call.name}")

                        client.beta.threads.runs.submit_tool_outputs(
                            thread_id=thread.id,
                            run_id=run.id,
                            tool_outputs=tool_outputs
                        )

                        time.sleep(0.5)
                    else:
                        raise Exception(f"Unknown required action: {run.required_action.type}")

                if run.status == "completed":
                    if not self.new_files.done():
                        raise Exception("No patches or new files to submit")
                    break
                else:
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
    from chat_find_files import Issue
    from filesystem import Filesystem

    owner = "roboflow"
    name = "supervision"
    repo_name = f"{owner}/{name}"

    fs = Filesystem(name, create_meta=True)

    issue_title = "Make `sv.LineZone.trigger` return bool `np.ndarray` informing which detections have crossed the line this frame"
    issue_body = """
    Currently, [`sv.LineZone.trigger`](https://github.com/roboflow/supervision/blob/5b5e0eb88daec92643834b2284e750ad5a1c7dc6/supervision/detection/line_counter.py#L30) updates `in_count` and `out_count` values but does not return information on which object crossed the line. Unlike [`sv.PolygonZone.trigger`](https://github.com/roboflow/supervision/blob/5b5e0eb88daec92643834b2284e750ad5a1c7dc6/supervision/detection/tools/polygon_zone.py#L45), which returns such information.
    Information about who has crossed the line is needed to update `in_count` and `out_count` and is already calculated in the `trigger` method but does not surface. Let's change that.
    """
    issue = Issue(issue_title, issue_body, repo_name)
    filenames = ["supervision/supervision/detection/line_counter.py","supervision/supervision/detection/tools/polygon_zone.py"]

    code_writer = GPTWriteCode(issue, filenames, fs, snippet_type="diff")
    code_writer.initiate_chat()