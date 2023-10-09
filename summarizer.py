import ast
import os
import argparse
import sys
import pkgutil

standard_lib = list(sys.builtin_module_names)
installed_packages = [pkg.name for pkg in pkgutil.iter_modules()]


def parse_python_file(file_path):
    with open(file_path, 'r') as f:
        node = ast.parse(f.read())

    classes = []
    functions = []
    dependencies = []

    for n in node.body:
        if isinstance(n, ast.ClassDef):
            classes.append(n.name)
        elif isinstance(n, ast.FunctionDef):
            functions.append(n.name)
        elif isinstance(n, ast.Import):
            for name in n.names:
                # Check against both standard and external libraries
                if name.name not in standard_lib and name.name not in installed_packages:
                    dependencies.append(name.name)
        elif isinstance(n, ast.ImportFrom):
            module = n.module
            # Check against both standard and external libraries
            if module not in standard_lib and module.split('.')[0] not in installed_packages:
                for name in n.names:
                    dependencies.append(f"{module}.{name.name}")

    return {
        "classes": classes,
        "functions": functions,
        "dependencies": dependencies
    }

def generate_overview_for_directory(directory_path):
    overviews = {}

    for root, _, files in os.walk(directory_path):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                overview = parse_python_file(file_path)
                overviews[file_path] = overview

    return overviews

def print_overview(overviews):
    for file, overview in overviews.items():
        print(f"File: {file}")
        print("Classes:", ", ".join(overview["classes"]) if overview["classes"] else "None")
        print("Functions:", ", ".join(overview["functions"]) if overview["functions"] else "None")
        print("Dependencies:", ", ".join(overview["dependencies"]) if overview["dependencies"] else "None")
        print('-' * 50)

def generate_dot(overviews):
    dot_content = [
        "digraph G {",
        '    ranksep=1;',
        '    nodesep=0.5;'
    ]

    for file, overview in overviews.items():
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

def main():
    parser = argparse.ArgumentParser(description="Generate an overview of a Python codebase.")
    parser.add_argument("directory", help="Path to the Python codebase directory.")

    args = parser.parse_args()

    overviews = generate_overview_for_directory(args.directory)
    print_overview(overviews)

    dot_content = generate_dot(overviews)

    with open("assets/codebase_overview.dot", "w") as f:
        f.write(dot_content)

if __name__ == "__main__":
    main()