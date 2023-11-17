from autogen import ConversableAgent
from filesystem import function_specs
import concurrent.futures
from collections import defaultdict
import difflib


config_list = [{'model': 'gpt-4'}]
# model = "gpt-4-0613"
model = "gpt-4-1106-preview"
llm_config={
    "timeout": 600,
    "seed": 42,
    "model": model,  # make sure the endpoint you use supports the model
    "temperature": 0,
    "functions": function_specs
}

onCheckCodeDef = {
    "name": "check_PR",
    "description": "Checks a PR for formatting and passing the tests.",
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
            },
            "tests": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The filename of the test file"
                    },
                    "code": {
                        "type": "string",
                        "description": "The code of the test file"
                    }
                }
            }
        }
    },
    "required": ["patches"]
}

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

def apply_patches(patches, snippet_type='diff'):
    original_files = {}
    snippets = defaultdict(str)
    # get unique 'filename' keys in patches
    filenames = set([patch['filename'] for patch in patches])
    for filename in filenames:
        try:
            with open('repos/' + filename, 'r') as f:
                file_content = f.read()
                original_files[filename] = file_content
        except Exception as e:
            print(f"Could not find file repo/{filename}: {e}")

    new_files = original_files.copy()

    for patch in patches:
        filename = patch['filename']
        content = new_files[filename]
        new_content = apply_patch_to_file(filename, content, patch['searchString'], patch['replaceString'])

        new_files[filename] = new_content

    for filename in filenames:
        if snippet_type == 'diff':
            snippets[filename] = get_diff_from_patch(original_files[filename], new_files[filename])
        elif snippet_type == 'snippet':
            snippets[filename] = get_snippet_from_patch(original_files[filename], new_files[filename], context=16)

    return new_files, snippets

def apply_patch_to_file(filename, file_content, searchString, replaceString):
    if searchString == "":
        file_content_new = file_content + replaceString
        return file_content_new

    if searchString in file_content:
        file_content_new = file_content.replace(searchString, replaceString)
    else:
        raise Exception(f"Search string \"{searchString}\" not found in file {filename}.\nCheck the file contents and/or correct the search string.")

    return file_content_new

def get_snippet_from_patch(file_before, file_after, context=10):
    before_lines = file_before.splitlines(keepends=True)
    after_lines = file_after.splitlines(keepends=True)

    diff = list(difflib.ndiff(before_lines, after_lines))
    changed_line_indices = [i for i, line in enumerate(diff) if line.startswith('- ') or line.startswith('+ ')]

    # group changed_line_indices into continuous ranges if they very by less than the context size
    changed_line_indices_grouped = []
    for group in changed_line_indices:
        if len(changed_line_indices_grouped) == 0 or group - changed_line_indices_grouped[-1][-1] > context:
            changed_line_indices_grouped.append([group])
        else:
            changed_line_indices_grouped[-1].append(group)

    snippets = []
    for group in changed_line_indices_grouped:
        start = max(0, min(group) - context)
        end = min(len(after_lines), max(group) + context + 1)
        snippet = ''.join([line[2:] if line.startswith('+ ') or line.startswith('  ') else '' for line in diff[start:end]])
        if snippet.strip():  # Ignore empty snippets
            snippets.append(snippet)

        snippet_str = "# Code above left out as it's unchanged...\n\n" + "\n\n# Code above left out as it's unchanged...\n\n".join(snippets)

    return snippet_str

def get_diff_from_patch(file_content_before, file_content_after):
    before_lines = file_content_before.splitlines()
    after_lines = file_content_after.splitlines()
    diff = difflib.unified_diff(before_lines, after_lines, fromfile='before', tofile='after', lineterm='')
    return '\n'.join(diff)

class ChatWriteCode():
    system_message_filesystem = """
    You are an expert programmer. You are in control of a filesystem API with access to the codebase of a GitHub repository.
    This API allows you to read summaries of files and their full contents. You can also lookup what filename any class/method/import comes from.
    You are being asked by an engineer who is working on solving a GitHub issue for this repository. You must satisfy all their requests
    for information about the codebase. When creating a PR, first check its validaty prior to submitting. If the PR is correct, submit it.
    Respond with TERMINATE to end the chat after submitting the PR.
    """
    user_system_message = """
    You are a software engineer working on a GitHub repository. You have been assigned an issue to resolve.
    You are given a starting point for the relevant files needed to modify. You can communicate with the filesystem API to read these and other files.
    Your task is to write a PR for the issue. Do this by providing patches for each file that needs to be modified. Be careful of subtle whitespace errors.
    Once finished call the `check_PR` method to validate the patches. Errors may be returned from `check_PR` if the PR is not valid, in which case fix them and check the PR again.
    If there are no errors, submit the patches by calling `submit_PR`. Respond with TERMINATE to end the chat after submitting the patches.
    """
    def __init__(self, issue, filenames, filesystem, snippet_type='diff'):
        self.issue = issue
        self.function_map = {
            "get_summaries": filesystem.get_summaries,
            "get_content": filesystem.get_content,
            "get_filename_for_object": filesystem.get_filename_for_object,
            "list_files": filesystem.tree
        }

        self.filenames = filenames
        self.new_files = concurrent.futures.Future()
        self.patches = concurrent.futures.Future()

        self.create_chatbots()
        self.add_callbacks(snippet_type=snippet_type)

    @staticmethod
    def is_terminal(message):
        if message['content'] is None:
            return False
        return 'TERMINATE' in message['content']

    def add_callbacks(self, snippet_type='diff'):
        def onCheckCode(patches, tests=None):
            _, snippets = apply_patches(patches, snippet_type=snippet_type)
            snippets_str = '\n'.join([f'Filename: {filename}:\n\n{snippet}\n\n' for filename, snippet in snippets.items()])
            if snippet_type == 'diff':
                return f"Here is the diff reflecting your changes. Double check its correctness. Be sure to check for subtle whitespace errors. If the changes are correct proceed to submitting the PR, otherwise explain what's wrong then correct the patch and check it again.\n\n{snippets_str}\n\nDoes this look correct?"
            elif snippet_type == 'snippet':
                return f"Here are snippets reflecting your changes. Double check their correctness. Be sure to check for subtle whitespace errors. If the changes are correct proceed to submitting the PR, otherwise explain what's wrong then correct the patch and check it again.\n\n{snippets_str}\n\nDoes this look correct?"

        def onSubmitCode(patches):
            new_files, _ = apply_patches(patches)
            self.new_files.set_result(new_files)
            self.patches.set_result(patches)
            return 'TERMINATE'

        self.add_callback(onCheckCode, onCheckCodeDef)
        self.add_callback(onSubmitCode, onSubmitCodeDef)


    def add_callback(self, method, method_def):
        method_name = method_def['name']
        self.function_map[method_name] = method
        llm_config["functions"].append(method_def)

        self.filesystem_bot.llm_config.update(llm_config)
        self.user_bot.register_function(self.function_map)

    def generate_user_prompt(self, issue, filenames):
        # turn files array into bulletpoint list
        files_str = '\n'.join([f'- {file}' for file in filenames])
        prompt = f"""
        {str(issue)}\n\nHere is a first pass of some of the files that need modifying.
        Check if modifying them resolves the issue and if so, provide a patch to each file that does so.\n\n{files_str}\n\n
        Navigate/read the codebase using the filesystem API to craft and submit a PR.
        """
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
        prompt = self.generate_user_prompt(self.issue, self.filenames)
        self.user_bot.initiate_chat(self.filesystem_bot, message=prompt, **kwargs)
