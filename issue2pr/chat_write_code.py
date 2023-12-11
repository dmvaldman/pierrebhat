from autogen import ConversableAgent
from filesystem import function_specs
import concurrent.futures
import difflib
import subprocess
from utils.llm_config import llm_config
import os

max_consecutive_auto_reply = 50

repo_dir = "repos/"
temp_dir = 'temp/'
base_path = os.path.dirname(os.path.abspath(__file__))

llm_config_filesystem = llm_config.copy()
llm_config_user = llm_config.copy()

llm_config_filesystem["functions"] = function_specs

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

def replace_ignore_linebreaks(corpus, query, replaceString):
    # Hack. Since GPT can produce a searchString with single linebreaks instead of multiple,
    query_parts = query.split('\n')
    start_index = -1
    end_index = -1
    current_index = 0

    for part in query_parts:
        # Find each part in the corpus, starting from the current index
        part_index = corpus.find(part, current_index)

        if start_index == -1:
            start_index = part_index  # Record the start of the first part

        # Update current_index to the end of the current part plus potential line breaks
        current_index = part_index + len(part)
        while current_index < len(corpus) and corpus[current_index] == '\n':
            current_index += 1

    end_index = current_index

    # Replace the found section with the replaceString
    return corpus[:start_index] + replaceString + corpus[end_index:]

def apply_patches(patches, snippet_type='diff'):
    original_files = {}
    new_files = {}

    # get unique 'filename' keys in patches
    filenames = set([patch['filename'] for patch in patches])

    for filename in filenames:
        try:
            filepath = os.path.join(base_path, repo_dir, filename)
            with open(filepath, 'r') as f:
                file_content = f.read()
                original_files[filename] = file_content
        except Exception as e:
            print(f"Could not find file: {filepath}. {e}")

    for patch in patches:
        filename = patch['filename']
        content = original_files[filename]

        try:
            new_content = apply_patch_to_file(filename, content, patch['searchString'], patch['replaceString'])
        except Exception as e:
            print(f"Could not apply patch to file {filename}. {e}")
        new_files[filename] = new_content

    snippets = generate_snippets(original_files, new_files, snippet_type=snippet_type)
    return new_files, original_files, snippets

def generate_snippets(original_files, new_files, snippet_type='diff'):
    snippets = {}
    for filename in original_files.keys():
        content_original = original_files[filename]
        content_new = new_files[filename]
        if snippet_type == 'diff':
            snippets[filename] = get_diff_from_patch(content_original, content_new)
        elif snippet_type == 'snippet':
            snippets[filename] = get_snippet_from_patch(content_original, content_new, context=16)
        elif snippet_type == 'all':
            snippets[filename] = content_new

    return snippets

def apply_patch_to_file(filename, file_content, searchString, replaceString):
    if searchString == "":
        file_content_new = file_content + replaceString
        return file_content_new

    if searchString in file_content:
        file_content_new = file_content.replace(searchString, replaceString)
    else:
        # Hack that allows search/replace when number of linebreaks don't match up
        if searchString in file_content.replace('\n\n', '\n'):
            file_content_new = replace_ignore_linebreaks(file_content, searchString, replaceString)
        else:
            raise Exception(f"Search string \"{searchString}\" not found in file {filename}. Check the file contents and/or correct the search string.")

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

    snippets_after = []
    snippets_before = []
    snippet_str = ''
    for group in changed_line_indices_grouped:
        start = max(0, min(group) - context)
        end = min(len(after_lines), max(group) + context + 1)
        snippet_after = ''.join([line[2:] if line.startswith('+ ') or line.startswith('  ') else '' for line in diff[start:end]])
        snippet_before = ''.join([line[2:] if line.startswith('- ') or line.startswith('  ') else '' for line in diff[start:end]])

        snippets_after.append(snippet_after)
        snippets_before.append(snippet_before)

    for snippet_before, snippet_after in zip(snippets_before, snippets_after):
        snippet_str += "<<<START SNIPPET ORIGINAL>>>\n\n" + snippet_before + "\n\n<<<END SNIPPET ORIGINAL>>>\n\n" + "<<<START SNIPPET NEW>>>\n\n" + snippet_after + "\n\n<<<END SNIPPET NEW>>>\n\n"

    return snippet_str

def get_diff_from_patch(file_content_before, file_content_after):
    before_lines = file_content_before.splitlines()
    after_lines = file_content_after.splitlines()
    diff = difflib.unified_diff(before_lines, after_lines, fromfile='before', tofile='after', lineterm='')
    return '\n'.join(diff)

def check_syntax(file_path):
    result = subprocess.run(["pyflakes", file_path], capture_output=True, text=True)
    if result.stdout == '':
        return None
    else:
        response = ''
        error_str = result.stdout
        filename = '/'.join(file_path.split('/')[-1].split('_'))

        for error_str in result.stdout.split('\n'):
            if error_str == '': continue
            [line_num, char_num, error] = error_str.split(':')[1:4]
            error = error.strip()

            with open(file_path, 'r') as f:
                lines = f.readlines()
                affected_lines = ''.join(lines[int(line_num)-2: int(line_num)+1])

            response += f'Error in file {filename}: Line {line_num}, Char {char_num}\nError: {error}\nAffected Lines:\n{affected_lines}\n\n'
        return response

class ChatWriteCode():
    system_message_filesystem = """
    You are an expert programmer. You are in control of a filesystem API with access to the codebase of a GitHub repository.
    This API allows you to read summaries of files and their full contents. You can also lookup what filename any class/method/import comes from.
    You are being asked by an engineer who is working on solving a GitHub issue for this repository. You must satisfy all their requests
    for information about the codebase. When creating a PR, first check its validaty prior to submitting by calling `check_PR`. If the PR is correct,
    submit it by calling `submit_PR`. Otherwise rewrite the patches and check again. Respond with TERMINATE to end the chat after submitting the PR.
    """
    user_system_message = """
    You are a software engineer working on a GitHub repository. You have been assigned an issue to resolve.
    You are given a starting point for the relevant files needed to modify. You can communicate with the filesystem API to read these and other files.
    Your task is to write a PR for the issue. Do this by providing patches for each file that needs to be modified. You must first check the PR before submitting it.
    Respond with TERMINATE to end the chat after successfully submitting the patches.
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
        self.original_files = concurrent.futures.Future()

        self.create_chatbots()
        self.add_callbacks(snippet_type=snippet_type)

    @staticmethod
    def is_terminal(message):
        if message['content'] is None:
            return False
        return 'TERMINATE' in message['content']

    def add_callbacks(self, snippet_type='diff'):
        def onCheckCode(patches):
            try:
                new_files, _, snippets = apply_patches(patches, snippet_type=snippet_type)
            except Exception as e:
                return str(e)

            errors = 'Following errors found:\n\n'
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

            snippets_str = '\n'.join([f'Filename: {filename}:\n\n{snippet}\n\n' for filename, snippet in snippets.items()])

            if has_errors:
                return f"Here are the snippets reflecting your changes\n\n{snippets_str}. The following errors were found:\n\n{errors}\n\nPlease create a new patch (starting from the original files) and check again."

            if snippet_type == 'diff':
                return f"Here is the diff reflecting your changes. Double check its correctness. If the changes are correct proceed to submitting the PR, otherwise explain what's wrong then correct the patch and check it again.\n\n{snippets_str}\n\nDoes this look correct? If not, generate a new patch to be applied to the original file(s). If yes, submit the PR."
            elif snippet_type == 'snippet':
                return f"Here are snippets reflecting your changes. Double check their correctness. If the changes are correct proceed to submitting the PR, otherwise explain what's wrong then correct the patch and check it again.\n\n{snippets_str}\n\nDoes this look correct? If not, generate a new patch to be applied to the original file(s). If yes, submit the PR."
            elif snippet_type == 'all':
                return f"Here are the files reflecting your changes. Double check their correctness. If the changes are correct proceed to submitting the PR, otherwise explain what's wrong then correct the patch and check it again.\n\n{snippets_str}\n\nDoes this look correct? If not, generate a new patch to be applied to the original file(s). If yes, submit the PR."

        def onSubmitCode(patches):
            new_files, original_files, _ = apply_patches(patches)
            self.new_files.set_result(new_files)
            self.patches.set_result(patches)
            self.original_files.set_result(original_files)
            return 'TERMINATE'

        self.add_callback(onCheckCode, onCheckPRDef)
        self.add_callback(onSubmitCode, onSubmitPRDef)

    def add_callback(self, method, method_def):
        method_name = method_def['name']
        self.function_map[method_name] = method
        llm_config_filesystem["functions"].append(method_def)

        self.filesystem_bot.llm_config.update(llm_config_filesystem)
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
            llm_config=llm_config_filesystem,
            code_execution_config=False,
            is_termination_msg = ChatWriteCode.is_terminal,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            human_input_mode="NEVER"
        )

        self.user_bot = ConversableAgent("user_write_code",
            system_message = ChatWriteCode.user_system_message,
            is_termination_msg = ChatWriteCode.is_terminal,
            llm_config=llm_config_user,
            code_execution_config=False,
            function_map = self.function_map,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            human_input_mode="NEVER")

    def initiate_chat(self, **kwargs):
        prompt = self.generate_user_prompt(self.issue, self.filenames)
        self.user_bot.initiate_chat(self.filesystem_bot, message=prompt, **kwargs)
