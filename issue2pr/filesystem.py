import os
import difflib
from summarizer import Summarizer

# TODO: print only relative paths

root_dir = 'repos/'

def find_nearest(corpus, query, num_matches=3):
    matches = difflib.get_close_matches(corpus, query, n=num_matches)
    return matches

class Filesystem():
    extensions = ('.js', '.jsx', '.py', '.json', '.html', '.css', '.scss', '.yml', '.yaml', '.ts', '.tsx', '.ipynb', '.c', '.cc', '.cpp', '.go', '.h', '.hpp', '.java', '.sol', '.sh', '.txt', '.md')
    directory_blacklist = ('build', 'dist', 'test', 'tests', 'log', 'logs', 'docker', 'node_modules', 'venv', 'env', 'assets', 'include', 'docs', 'examples')
    base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), root_dir)
    def __init__(self, curr_dir=None, meta=None, create_meta=False):
        self.current_folder = Folder(curr_dir)
        self.meta = meta
        self.reverse_lookup = None
        if curr_dir:
            self.init(curr_dir)

        if create_meta:
            metadata = Summarizer(curr_dir)
            self.add_metadata(metadata)
            self.reverse_lookup = metadata.reverse_lookup

    def init(self, curr_dir):
        curr_folder = Folder(curr_dir)
        self.current_folder = curr_folder

        path = os.path.join(Filesystem.base_path, curr_dir)

        for curr_dir, folders, files in os.walk(path, topdown=True):
            # remove root_dir prefix using os.path
            curr_dir = ''.join(curr_dir.split(root_dir)[1:])

            if any([folder.startswith('.') for folder in curr_dir.split('/')]):
                continue

            if any([blacklisted == curr_dir for blacklisted in self.directory_blacklist]):
                continue

            curr_folder = self.find_folder(curr_dir)
            if curr_folder is None:
                continue

            for file in files:
                if not file.lower().endswith(self.extensions):
                    continue
                file_path = os.path.join(curr_dir, file)
                curr_folder.add_file(File(file_path))

            for folder in folders:
                if folder.lower() in self.directory_blacklist:
                    continue
                # ignore any directory with beginning with a dot
                if folder.startswith('.'):
                    continue
                folder_path = os.path.join(curr_dir, folder)
                curr_folder.add_folder(Folder(folder_path))

    def add_metadata(self, metadata):
        for folder, file in self.walk():
            if file.name in metadata.overviews:
                file_meta = metadata.overviews[file.name]
                file.set_metadata(file_meta)
            if folder.name in metadata.overviews:
                folder_meta = metadata.overviews[folder.name]
                folder.set_metadata(folder_meta)

    def get_filename_for_object(self, name):
        if self.reverse_lookup is None or name not in self.reverse_lookup:
            keys = list(self.reverse_lookup.keys())
            matches = find_nearest(keys, name, num_matches=3)
            raise Exception(f'Could not find {name}. Did you mean any of {matches}?')
        else:
            return list(self.reverse_lookup[name])

    def walk(self):
        yield from self.current_folder.walk()

    def to_json(self):
        return self.current_folder.to_json()

    def tree(self):
        return self.current_folder.tree()

    def read(self):
        read_str = ''
        if self.meta:
            read_str += str(self.meta) + '\n'
        read_str += self.current_folder.read()
        return read_str

    def create_folder(self, name, meta=''):
        folder = Folder(name, meta)
        self.current_folder = folder
        return folder

    def set_current_folder(self, folder):
        self.current_folder = folder

    def get_current_folder(self):
        return self.current_folder

    def set_metadata(self, meta):
        self.meta = meta

    def find_folder(self, path):
        if not path.startswith(self.current_folder.name):
            raise Exception(f'Could not find directory {path} in {self.current_folder.name}. Did you mean to start the path with {self.current_folder.name}?')
        return self.current_folder.find_folder(path)

    def open(self, directory=None):
        if directory:
            folder = self.find_folder(directory)
            if folder is None:
                raise Exception(f'Could not find directory {directory} in {self.current_folder.name}')
            else:
                folder.open()
        else:
            self.current_folder.open()
        return self

    def close(self, directory=None):
        if directory:
            folder = self.find_folder(directory)
            if folder is None:
                raise Exception(f'Could not find directory {directory} in {self.current_folder.name}')
            else:
                folder.close()
        else:
            self.current_folder.close()
        return self

    def get_content(self, filename):
        file = self.current_folder.find_file(filename)
        if file is None:
            filenames = self.list_files()
            matches = find_nearest(filenames, filename, n=1)
            raise Exception(f'Could not find file {filename} in {self.current_folder.name}. Did you mean {matches[0]}?')
        else:
            return file.get_content()

    def get_summary(self, filename):
        # TODO: find nearest match
        if not filename.startswith(self.current_folder.name):
            raise Exception(f'Could not find file {filename} in {self.current_folder.name}. Did you mean to start the path with {self.current_folder.name}?')

        file = self.current_folder.find_file(filename)
        if file is None:
            # closest matches
            filenames = self.list_files()
            matches = find_nearest(filenames, filename, n=1)
            raise Exception(f'Could not find file {filename} in {self.current_folder.name}. Did you mean {matches[0]}?')
        else:
            return file.get_summary()

    def get_summaries(self, filenames):
        summaries_str = ''
        for filename in filenames:
            if not filename.startswith(self.current_folder.name):
                raise Exception(f'Could not find file {filename} in {self.current_folder.name}. Did you mean to start the path with {self.current_folder.name}?')
            file = self.current_folder.find_file(filename)
            if file is None:
                filenames = self.list_files()
                matches = find_nearest(filenames, filename, n=1)
                raise Exception(f'Could not find file {filename} in {self.current_folder.name}. Did you mean {matches[0]}?')
            else:
                summaries_str += file.get_summary() + '\n\n'
        return summaries_str

class Folder:
    def __init__(self, path, meta=''):
        self.name = path
        self.meta = meta
        self.files = []
        self.folders = []
        self.is_open = False

    def set_metadata(self, meta):
        self.meta = meta

    def walk(self):
        for filename in self.files:
            yield self, filename
        for folder in self.folders:
            yield from folder.walk()

    def to_json(self):
        if self.meta is None:
            meta_json = None
        else:
            meta_json = self.meta.to_json()
        json = {
            "name": self.name,
            "meta": meta_json,
            "files": [file.to_json() for file in self.files],
            "folders": [folder.to_json() for folder in self.folders]
        }
        return json

    def find_folder(self, name):
        if name == self.name:
            return self

        for folder in self.folders:
            if folder.name == name:
                return folder
        for folder in self.folders:
            folder = folder.find_folder(name)
            if folder is not None:
                return folder

        return None

    def find_file(self, name):
        for file in self.files:
            if file.name == name:
                return file
        for folder in self.folders:
            file = folder.find_file(name)
            if file is not None:
                return file

        return None

    def add_file(self, file):
        self.files.append(file)

    def add_folder(self, folder):
        folder.parent = self
        self.folders.append(folder)

    def open(self):
        self.is_open = True

    def close(self):
        self.is_open = False
        for folder in self.folders:
            folder.close()

    def read(self, indent=0):
        read_str = '\t' * indent + str(self)

        if self.is_open:
            indent += 1
            for folder in self.folders:
                read_str += folder.read(indent=indent)

            for file in self.files:
                read_str += '\t' * indent + file.read() + '\n'

        return read_str

    def tree(self, indent=0):
        read_str = '\t' * indent + self.name + '\n'

        indent += 1
        for folder in self.folders:
            read_str += folder.tree(indent=indent)

        for file in self.files:
            read_str += '\t' * indent + file.read(only_name=True) + '\n'

        return read_str

    def list_files(self):
        files = []

        for folder in self.folders:
            files += folder.list_files

        files += self.files

        return files

    def __str__(self):
        return f'Folder: {self.name}: {self.meta}\n'

class File:
    def __init__(self, name, meta=None):
        self.name = name
        self.meta = meta
        self.path = os.path.join(Filesystem.base_path, name)

    def set_metadata(self, meta):
        self.meta = meta

    def to_json(self):
        if self.meta is None:
            meta_json = None
        else:
            meta_json = self.meta.to_json()

        return {
            "name": self.name,
            "meta": meta_json
        }

    def read(self, only_name=False):
        if only_name:
            return self.name
        return str(self)

    def __str__(self):
        return f'File: {self.name}: {self.meta}'

    def get_content(self):
        return open(self.path, 'r').read()

    def get_summary(self):
        return f'Summary for {self.name}\n{self.meta}'

function_specs = [
    {
        "name": "list_files",
        "description": "Returns a prettified list of all files in the codebase",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_summaries",
        "description": "Returns high-level summaries (description, dependencies, classnames) for a given list of filenames",
        "parameters": {
            "type": "object",
            "properties": {
                "filenames": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "description": "A filename"
                    },
                    "description": "An array of filenames to get summaries for"
                }
            }
        },
        "required": ["filenames"]
    },
    {
        "name": "get_content",
        "description": "Returns the content of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename to read"
                }
            }
        },
        "required": ["filename"]
    },
    {
        "name": "get_filename_for_object",
        "description": "Returns an array of filenames for where a given class or class method, class attribute or dependency is defined. Class methods should be namespaced to their class name e.g., `class_name.function_name` but class attributes shouldn't be as instances are often renamed.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The name of the class, method or function"
                }
            }
        },
        "required": ["name"]
    }
]

if __name__ == '__main__':
    directory = "Auto-GPT"
    fs = Filesystem(directory, create_meta=True)
    print(fs.tree())
