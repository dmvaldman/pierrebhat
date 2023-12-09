import concurrent.futures
from autogen import ConversableAgent
from filesystem import Filesystem, function_specs
from openai_helpers.helpers import MAX_CONTENT_LENGTH
from utils.llm_config import llm_config


max_consecutive_auto_reply = 50

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

llm_config_filesystem = llm_config.copy()
llm_config_user = llm_config.copy()

llm_config_filesystem["functions"] = function_specs


class ChatFindFiles():
    system_message_filesystem = """
    You are a software engineer in control of a filesystem API with access to the codebase of a GitHub repository. This API allows you to read summaries of files
    and their contents. You are talking to another software engineer who is looking for some files. When the files are found, call `submit_files` with a list of the filenames.
    Afterwards, respond with TERMINATE to end the chat, but only after calling `submit_files`.
    """
    system_message_user = """
    You are a software engineer working on a GitHub repository. You are professional and terse. You have been assigned an issue to resolve.
    Your task is to locate the files needed to modify to resolve the issue, which you can do by conversing with the filesystem API.
    Once the files are found, the filesystem can submit them. Afterwards, respond with TERMINATE to end the chat, but only after submitting the files.
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
            filenames = [repo_name + '/' + filename for filename in filenames]
            self.filenames.set_result(filenames)

        method_name = method_def['name']
        self.function_map[method_name] = onFindFiles
        llm_config_filesystem["functions"].append(method_def)

        self.filesystem_bot.llm_config.update(llm_config_filesystem)
        self.user_bot.register_function(self.function_map)

    def generate_user_prompt(self, issue, fs):
        # TODO: better truncation
        prompt = f"{str(issue)}\nHere is the directory structure:\n\n{fs.tree()}\nWhat files need to be changed to fix this issue? Navigate/read the codebase using the filesystem API to determine a list of files (in mardown format) that need modifying."
        if len(prompt) > MAX_CONTENT_LENGTH:
            prompt = prompt[:MAX_CONTENT_LENGTH] + '...'
        return prompt

    def create_chatbots(self):
        self.filesystem_bot = ConversableAgent("filesystem",
            system_message = ChatFindFiles.system_message_filesystem,
            llm_config=llm_config_filesystem,
            code_execution_config=False,
            is_termination_msg = ChatFindFiles.is_terminal,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            human_input_mode="NEVER"
        )

        self.user_bot = ConversableAgent("user_find_files",
            system_message = ChatFindFiles.system_message_user,
            llm_config=llm_config_user,
            is_termination_msg = ChatFindFiles.is_terminal,
            function_map = self.function_map,
            code_execution_config=False,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
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
