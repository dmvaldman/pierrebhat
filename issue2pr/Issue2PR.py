from filesystem import Filesystem
from chat_find_files import ChatFindFiles
from chat_write_code import ChatWriteCode, GPTWriteCode, SNIPPET_TYPE
from contextlib import redirect_stdout
from issue import Issue
from repo import Repo
import os
import time
import sys
import tiktoken
from utils.llm_config import model
import difflib
from enum import Enum, auto

class WRITE_CODE_TYPE(Enum):
    AGENT = auto()
    AUTOGEN = auto()

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
    def create_issue(*args, **kwargs):
        issue = Issue(*args, **kwargs)
        return issue

    def _resolve(self):
        issue = self.issue
        fs = self.fs

        snippet_type = SNIPPET_TYPE(self.options['snippet_type'])
        write_code_type = WRITE_CODE_TYPE(self.options['write_code'])
        use_plan = self.options['use_plan']

        chat_find_files = ChatFindFiles(fs, issue, use_plan)
        chat_find_files.initiate_chat(silent=False)

        if not chat_find_files.filenames['modify'].done():
            raise Exception(f'ERROR: ChatFindFiles did not finish. Check the logs at {self.logfile_path}.')

        filenames = {}
        for key, value in chat_find_files.filenames.items():
            filenames[key] = value.result()

        if use_plan:
            plan = chat_find_files.scratchpad.read_plan()
            print('\n\nPLAN:', plan, '\n\n')
        else:
            plan = None

        if write_code_type == WRITE_CODE_TYPE.AGENT:
            chat_write_code_cls = GPTWriteCode
        elif write_code_type == WRITE_CODE_TYPE.AUTOGEN:
            chat_write_code_cls = ChatWriteCode

        chat_write_code = chat_write_code_cls(issue, filenames, fs, plan=plan, snippet_type=snippet_type)
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
            timestamp = time.strftime("%Y%m%d-%H%M")
            filename = f'{self.issue.repo_name}_{self.issue.title[:20]}_{timestamp}.txt'
            # replace spaces and slashes and with underscores
            filename = filename.replace(' ', '_').replace('/', '_')
            logfile_path = os.path.join(curr_dir, 'logs', filename)
            print("Logging to", logfile_path)
            self.logfile_path = logfile_path

            with open(logfile_path, 'w') as file:
                with redirect_stdout(file):
                    print('Config: ', self.options, '\n')
                    print(f'Issue Title: {self.issue.title}\nIssue Num: {self.issue.num}')
                    print('\n---------\n')
                    pr = self._resolve()
        else:
            pr = self._resolve()

        return pr

class PR():
    def __init__(self, issue, patches, original_files, new_files):
        self.issue = issue
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

        filenames_mod = set(new_files.keys()) & set(orig_files.keys())
        filenames_del = set(orig_files.keys()) - set(new_files.keys())
        filenames_add = set(new_files.keys()) - set(orig_files.keys())

        # files to modify
        for filename_mod in filenames_mod:
            orig_file = orig_files[filename_mod]
            new_file = new_files[filename_mod]
            diff = self.create_singlefile_diff(filename_mod, orig_file, filename_mod, new_file)
            diffs.extend(diff + ['\n'])

        # files to delete
        for filename_del in filenames_del:
            orig_file = orig_files[filename_del]
            diff = self.create_singlefile_diff(filename_del, orig_file, filename_del, '')
            diffs.extend(diff + ['\n'])

        # files to add
        for filename_add in filenames_add:
            new_file = new_files[filename_add]
            diff = self.create_singlefile_diff(filename_add, '', filename_add, new_file)
            diffs.extend(diff + ['\n'])

        return diffs

    def to_json(self):
        return {
            "patches": self.patches,
            "diff": self.diff_str,
            "new_files": self.new_files
        }