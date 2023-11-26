import ast as py_ast
import os
import sys
import pkgutil
import subprocess
import json
from openai_helpers.helpers import complete

standard_lib = list(sys.builtin_module_names)
installed_packages = [pkg.name for pkg in pkgutil.iter_modules()]

root_dir = 'repos/'

def add_overview_to_reverse_lookup(overview, file_path, reverse_lookup):
    for cls in overview["classes"]:
        reverse_lookup[cls] = file_path
    for func in overview["functions"]:
        reverse_lookup[func] = file_path
    for method in overview["methods"]:
        reverse_lookup[method] = file_path
    for dependency in overview["dependencies"]:
        reverse_lookup[dependency] = file_path
    for attribute in overview["attributes"]:
        reverse_lookup[attribute] = file_path
    return reverse_lookup

class Summary():
    def __init__(self, data):
        self.data = data

    def to_json(self):
        return self.data

    def add(self, key, value):
        self.data[key] = value

    def __str__(self):
        str = ''
        for key, value in self.data.items():
            str += f'{key}: {value}\n'
        return str

class Summarizer():
    extensions = ('.js', '.jsx', '.py', '.json', '.html', '.css', '.scss', '.yml', '.yaml', '.ts', '.tsx', '.ipynb', '.c', '.cc', '.cpp', '.go', '.h', '.hpp', '.java', '.sol', '.sh', '.txt', '.md')
    directory_blacklist = ('build', 'dist', 'test', 'tests', 'log', 'logs', 'docker', 'node_modules', 'venv', 'env', 'assets', 'include', 'docs', 'examples')
    def __init__(self, repo_name):
        self.repo_name = repo_name
        self.overviews, self.reverse_lookup = self.generate_overview_for_directory(repo_name)

    def parse_python_file(self, file_path):
        # TODO: return array of filenames when there are collisions, and don't namespace by classname
        with open(root_dir + file_path, 'r') as f:
            node = py_ast.parse(f.read())

        classes = []
        functions = []
        dependencies = []
        methods = []
        attributes = []

        for n in node.body:
            if isinstance(n, py_ast.ClassDef):
                class_name = n.name
                classes.append(class_name)
                for item in n.body:
                    if isinstance(item, py_ast.FunctionDef):
                        method_name = item.name
                        # Concatenate the class name with the method name
                        qualified_name = f"{class_name}.{method_name}"
                        methods.append(qualified_name)

                        # Analyze the method body for attribute access patterns
                        for stmt in item.body:
                            if isinstance(stmt, py_ast.Expr) and isinstance(stmt.value, py_ast.Attribute):
                                if isinstance(stmt.value.value, py_ast.Name) and stmt.value.value.id == 'self':
                                    attribute_name = stmt.value.attr
                                    attributes.append(f"{class_name}.{attribute_name}")
                            elif isinstance(stmt, py_ast.Assign):
                                for target in stmt.targets:
                                    if isinstance(target, py_ast.Attribute):
                                        if isinstance(target.value, py_ast.Name) and target.value.id == 'self':
                                            attribute_name = target.attr
                                            attributes.append(f"{class_name}.{attribute_name}")
                    elif isinstance(item, py_ast.Assign):
                        # Check for assignments inside the class body
                        for target in item.targets:
                            if isinstance(target, py_ast.Name):
                                attribute_name = target.id
                                # attributes.append(f"{class_name}.{attribute_name}")
                                attributes.append(attribute_name) #TODO: hack since classnames are often renamed
            elif isinstance(n, py_ast.FunctionDef):
                functions.append(n.name)
            elif isinstance(n, py_ast.Import):
                for name in n.names:
                    if name.name not in standard_lib and name.name not in installed_packages:
                        dependencies.append(name.name)
            elif isinstance(n, py_ast.ImportFrom):
                module = n.module
                if module is not None and module not in standard_lib and module.split('.')[0] not in installed_packages:
                    for name in n.names:
                        dependencies.append(f"{module}.{name.name}")

        return {
            "classes": classes,
            "functions": functions,
            "dependencies": dependencies,
            "methods": methods,
            "attributes": attributes
        }

    def parse_js_file(self, file_path):
        result = subprocess.run(["node", "utils/parse.js", root_dir + file_path], capture_output=True, text=True)
        if result.stderr:
            print(f"Error occurred while processing {file_path}:")
            print(result.stderr)
            return {}  # or handle it in another way as per your requirements

        return json.loads(result.stdout)

    def generate_overview_for_directory(self, save=True, save_every=20):
        overviews = {}
        descriptions = self.get_descriptions()
        counter = 0
        reverse_lookup = {} # map of class/method/import to filename

        for root, _, files in os.walk(root_dir + self.repo_name):
            # remove root_dir prefix
            root = ''.join(root.split(root_dir)[1:])

            # Ignore any directory with beginning with a dot. Directory may be anywhere in the path
            if any([folder.lower().startswith('.') for folder in root.split('/')]):
                continue

            # Ignore any directory in the blacklist
            if any([blacklisted.lower() == root for blacklisted in self.directory_blacklist]):
                continue

            if root not in overviews:
                overviews[root] = {'description': None}

            root_file_descriptions = {}

            for file in files:
                file_path = os.path.join(root, file)

                # file is a dotfile so ignore
                if os.path.splitext(file_path)[1] == '':
                    continue

                if file.endswith('.py'):
                    overview = self.parse_python_file(file_path)
                    overviews[file_path] = overview
                    add_overview_to_reverse_lookup(overview, file_path, reverse_lookup)

                # elif file.endswith('.js'):
                #     overview = self.parse_js_file(file_path)
                #     overviews[file_path] = overview

                if file_path not in descriptions:
                    if not file_path.lower().endswith(self.extensions):
                        continue

                    description = self.generate_description_for_file(file_path)
                    descriptions[file_path] = description

                    if save and counter % save_every == 0:
                        self.save_descriptions(descriptions)

                    counter += 1

                root_file_descriptions[file_path] = descriptions[file_path]


            # add description for root based on the descriptions of all the files in it
            has_readme = any('README' in file for file in files)
            if root != self.repo_name or not has_readme:
                descriptions[root] = self.generate_description_for_folder(root, root_file_descriptions)

            if root == self.repo_name and has_readme:
                readme_file = [file for file in files if 'README' in file][0]
                descriptions[root] = self.generate_description_for_repo(root, readme_file)

        if save:
            self.save_descriptions(descriptions)

        # collect all keys from overviews and descriptions
        all_keys = set(list(overviews.keys()) + list(descriptions.keys()))
        summaries = {}
        for key in all_keys:
            if key not in overviews:
                summary = {'description': descriptions[key]}
            if key not in descriptions:
                summary = overviews[key]
            if key in overviews and key in descriptions:
                summary = {'description': descriptions[key], **overviews[key]}
            summaries[key] = Summary(summary)

        return summaries, reverse_lookup

    def get_descriptions(self):
        filepath = f'embeddings/{self.repo_name}/descriptions.json'
        if os.path.exists(filepath):
            return json.load(open(filepath, 'r'))
        else:
            return {}

    def generate_description_for_file(self, file_path):
        # cached result
        descriptions = self.get_descriptions()
        if descriptions is not None and file_path in descriptions and descriptions[file_path]:
            return descriptions[file_path]

        # generate
        description_prompt = 'A short summary in plain English of the above code is:'
        extension = file_path.split('.')[-1]
        try:
            code = open(root_dir + file_path, 'r').read()
        except:
            print(f"Error reading file {file_path}")
            return None

        prompt = f'File: {file_path}\n\nCode:\n\n```{extension}\n{code}```\n\n{description_prompt}\n\n'
        description = complete(prompt)
        return description

    def generate_description_for_folder(self, folder_path, file_descriptions):
        # cached result
        descriptions = self.get_descriptions()
        if descriptions is not None and folder_path in descriptions and descriptions[folder_path]:
            return descriptions[folder_path]

        # generate
        description_prompt = f'Here are the descriptions of all files in the folder {folder_path}:\n'
        for filename, description in file_descriptions.items():
            description_prompt += f'\nFile: {filename} - {description}'

        description_prompt += '\n\nA short summary in plain English of the above directory is:'
        description = complete(description_prompt)
        return description

    def generate_description_for_repo(self, root_path, readme_file):
        # cached result
        descriptions = self.get_descriptions()
        if descriptions is not None and root_path in descriptions and descriptions[root_path]:
            return descriptions[root_path]

        # generate
        description_prompt = f'Here is the README file for the repository {root_path}:\n'
        description_prompt += f'\nFile: {readme_file} - {open(os.path.join(root_dir + root_path, readme_file), "r").read()}'
        description_prompt += '\n\nA short summary in plain English of what the repository is about is:'
        description = complete(description_prompt)
        return description

    def save_descriptions(self, descriptions):
        filepath = f'embeddings/{self.repo_name}/descriptions.json'

        # create folder if doesn't exist
        if not os.path.exists(f'embeddings/{self.repo_name}'):
            os.makedirs(f'embeddings/{self.repo_name}')

        json.dump(descriptions, open(filepath, 'w'))

    def print(self):
        for file, overview in self.overviews.items():
            print(f"File: {file}")
            print("Classes:", ", ".join(overview["classes"]) if overview["classes"] else "None")
            print("Functions:", ", ".join(overview["functions"]) if overview["functions"] else "None")
            print("Dependencies:", ", ".join(overview["dependencies"]) if overview["dependencies"] else "None")
            print('-' * 50)

    def generate_dot(self):
        dot_content = [
            "digraph G {",
            '    ranksep=1;',
            '    nodesep=0.5;'
        ]

        for file, overview in self.overviews.items():
            # Start a cluster for each file
            dot_content.append(f'    subgraph cluster_{file.replace(".", "_")} {{')
            dot_content.append(f'        label="{file}";')
            # dot_content.append(f'        style=filled;')
            # dot_content.append(f'        color=lightgrey;')
            dot_content.append(f'        "{file}" [shape=box, color=black];')

            # Connect the file to its dependencies
            for dependency in overview["dependencies"]:
                dot_content.append(f'        "{file}" -> "{dependency}" [style=dotted];')

            # Connect the file to its classes and functions
            for cls in overview["classes"]:
                dot_content.append(f'        "{file}" -> "{cls}" [label="class", color=blue];')
            for func in overview["functions"]:
                dot_content.append(f'        "{file}" -> "{func}" [label="function", color=green];')

            # Close the cluster
            dot_content.append('    }')

        dot_content.append("}")

        return "\n".join(dot_content)