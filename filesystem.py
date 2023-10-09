import os

class Filesystem():
    extensions = ('.js', '.jsx', '.py', '.json', '.html', '.css', '.scss', '.yml', '.yaml', '.ts', '.tsx', '.ipynb', '.c', '.cc', '.cpp', '.go', '.h', '.hpp', '.java', '.sol', '.sh', '.txt')
    directory_blacklist = ('build', 'dist', '.github', 'site', 'tests', '.git')

    def __init__(self, curr_dir):
        self.current_folder = None
        if curr_dir:
            self.init(curr_dir)

    def init(self, curr_dir):
        curr_folder = Folder(curr_dir)
        self.current_folder = curr_folder

        for curr_dir, folders, files in os.walk(curr_dir, topdown=True):
            curr_folder = self.find_folder(curr_dir)
            if curr_folder is None:
                continue

            for file in files:
                if not file.endswith(self.extensions):
                    continue
                file_path = os.path.join(curr_dir, file)
                curr_folder.add_file(File(file_path))

            for folder in folders:
                if folder in self.directory_blacklist:
                    continue
                folder_path = os.path.join(curr_dir, folder)
                curr_folder.add_folder(Folder(folder_path))

    def read(self):
        return self.current_folder.read()

    def create_folder(self, name, description=''):
        folder = Folder(name, description)
        self.current_folder = folder
        return folder

    def set_current_folder(self, folder):
        self.current_folder = folder

    def get_current_folder(self):
        return self.current_folder

    def set_description(self, description):
        self.description = description

    def find_folder(self, path):
        return self.current_folder.find_folder(path)

    def open(self, directory=None):
        if directory:
            self.find_folder(directory).open()
        else:
            self.current_folder.open()
        return self

    def close(self, directory=None):
        if directory:
            self.find_folder(directory).close()
        else:
            self.current_folder.close()
        return self

class Folder:
    def __init__(self, path, description=''):
        self.name = path
        self.description = description
        self.files = []
        self.folders = []
        self.is_open = True

    def set_description(self, description):
        self.description = description

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
        str = '  ' * indent + f'{self.name}: {self.description}\n'

        if self.is_open:
            indent += 1
            for folder in self.folders:
                str += folder.read(indent)

            for file in self.files:
                str += '  ' * indent + file.read() + '\n'

        return str

class File:
    def __init__(self, name, description=''):
        self.name = name
        self.description = description

    def set_description(self, description):
        self.description = description

    def read(self):
        return f'{self.name}: {self.description}'


if __name__ == '__main__':
    import os

    directory = "repos/nanoGPT"
    fs = Filesystem(directory)
    fs.open()
    print(fs.read())
    print('hi')