from filesystem import Filesystem
from chat_find_files import ChatFindFiles
from chat_write_code import ChatWriteCode
from gpt_write_code import GPTWriteCode
from contextlib import redirect_stdout
from issue import Issue
from repo import Repo
import os
import time
import sys
import tiktoken
from utils.llm_config import model
import difflib


curr_dir = os.path.dirname(os.path.abspath(__file__))
tokenizer = tiktoken.encoding_for_model(model)

class Issue2PR:
    def __init__(self, repo=None, issue=None, options=None):
        self.issue = None
        self.repo = None
        self.options = options

        self.fs = None

        self.logfile_path = None
        self.num_tokens = 0

        if issue is not None:
            self.set_issue(issue)

        if repo is not None:
            self.set_repo(repo, download=True)

    @staticmethod
    def config_to_str(config):
        # convert dict to str with underscores between key/val pairs
        config_str = ''
        for key, val in config.items():
            config_str += f'_{key}_{val}'
        config_str = config_str[1:]
        return config_str

    @staticmethod
    def str_to_config(str):
        keyvals = str.split('_')
        config = {}
        for index in range(len(keyvals, 2)):
            key, val = keyvals[index], keyvals[index + 1]
            config[key] = val
        return config

    def set_repo(self, repo, download=True):
        self.repo = repo

        if download:
            print(f'Downloading repo {repo.name}')
            self.repo.download()
            print('Finished downloading repo')

        self.fs = Filesystem(repo.name, create_meta=True)

    def set_issue(self, issue):
        self.issue = issue

    @staticmethod
    def create_repo(repo_name):
        return Repo(repo_name)

    @staticmethod
    def create_repo_from_url(url):
        pass

    @staticmethod
    def create_issue_from_url(url):
        pass

    @staticmethod
    def create_issue(title, body, repo_name, num=None):
        issue = Issue(title, body, repo_name, num=num)
        return issue

    def _resolve(self):
        issue = self.issue
        fs = self.fs
        snippet_type = self.options['snippet_type']

        chat_find_files = ChatFindFiles(fs, issue)
        chat_find_files.initiate_chat(silent=False)

        if not chat_find_files.filenames.done():
            raise Exception(f'ERROR: ChatFindFiles did not finish. Check the logs at {self.logfile_path}.')

        filenames = chat_find_files.filenames.result()

        if self.options['write_code'] == 'agent':
            chat_write_code = GPTWriteCode(issue, filenames, fs, snippet_type=snippet_type)
        elif self.options['write_code'] == 'autogen':
            chat_write_code = ChatWriteCode(issue, filenames, fs, snippet_type=snippet_type)

        chat_write_code.initiate_chat(silent=False)

        if not chat_write_code.new_files.done():
            raise Exception(f'ERROR: ChatWriteCode did not finish. Check the logs at {self.logfile_path}.')

        new_files = chat_write_code.new_files.result()
        original_files = chat_write_code.original_files.result()
        patches = chat_write_code.patches.result()

        pr = PR(issue, patches, original_files, new_files)

        return pr

    def calc_num_tokens(self):
        if self.logfile_path is None:
            raise Exception('ERROR: No logfile_path set. Call resolve(logging=True) first.')

        sys.stdout.flush()
        with open(self.logfile_path, 'r') as file:
            num_tokens = len(tokenizer.encode(file.read()))

        return num_tokens

    def resolve(self, logging=True):
        if logging:
            config_str = Issue2PR.config_to_str(self.options)
            timestamp = time.strftime("%Y%m%d-%H%M")
            filename = f'{self.issue.repo_name}_{self.issue.title[:20]}_{timestamp}.txt'
            # replace spaces and slashes and with underscores
            filename = filename.replace(' ', '_').replace('/', '_')
            logfile_path = os.path.join(curr_dir, 'logs', filename)
            print("Logging to", logfile_path)
            self.logfile_path = logfile_path

            with open(logfile_path, 'w') as file:
                with redirect_stdout(file):
                    print('Config: ', self.options, '\n---------\n')
                    pr = self._resolve()

        else:
            pr = self._resolve()

        return pr

class PR():
    def __init__(self, issue, patches, original_files, new_files):
        self.issue = issue
        self.filenames = list(new_files.keys())
        self.patches = patches
        self.new_files = new_files
        self.original_files = original_files

        self.diff = self.create_multifile_diff(original_files, new_files)
        self.diff_str = ''.join(self.diff)

    def create_singlefile_diff(self, orig_filename, orig_string, new_filename, new_string):
        string1_lines = orig_string.splitlines(keepends=True)
        string2_lines = new_string.splitlines(keepends=True)

        diff = difflib.unified_diff(
            string1_lines, string2_lines,
            fromfile=orig_filename, tofile=new_filename,
            lineterm=''
        )

        return list(diff)

    def create_multifile_diff(self, orig_files, new_files):
        diffs = []
        zipped = {key: (orig_files[key], new_files[key]) for key in orig_files}
        for filename, (orig_file, new_file) in zipped.items():
            diff = self.create_singlefile_diff(filename, orig_file, filename, new_file)
            diffs.extend(diff + ['\n'])

        return diffs

    def to_json(self):
        return {
            "filenames": self.filenames,
            "patches": self.patches,
            "diff": self.diff,
            "new_files": self.new_files
        }